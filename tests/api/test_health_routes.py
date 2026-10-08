"""健康路由 / 中间件集成测试（HTTP 层，不依赖真实中间件）。"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from dw_api.app import API_PREFIX, create_app
from dw_infrastructure.config import Settings
from dw_infrastructure.health import HealthService, Probe
from dw_schemas.health import ComponentStatus, SystemStatus
from fastapi.testclient import TestClient


async def healthy_probe() -> dict[str, str]:
    return {"server_version": "16.4"}


async def failing_probe() -> dict[str, str]:
    raise RuntimeError("down")


async def slow_probe() -> dict[str, str]:
    await asyncio.sleep(5)
    return {}


PROBE_REGISTRY: dict[str, Probe] = {
    "postgres_ok": Probe("postgres", healthy_probe, critical=True),
    "postgres_down": Probe("postgres", failing_probe, critical=True),
    "redis_ok": Probe("redis", healthy_probe, critical=False),
    "kafka_down": Probe("kafka", failing_probe, critical=False),
    "kafka_slow": Probe("kafka", slow_probe, critical=False),
}


def health_probes(*names: str) -> list[Probe]:
    return [PROBE_REGISTRY[name] for name in names]


@pytest.fixture
def app_settings() -> Settings:
    return Settings(app_env="testing", log_json=False, log_level="WARNING")


@pytest.fixture
def client_factory(app_settings: Settings):
    """返回工厂函数：启动应用（跑完 lifespan）后用受控探针覆盖健康检查服务，
    使测试不依赖真实 Postgres / Redis / Kafka 是否可达。
    """

    @contextmanager
    def _factory(probes: list[Probe]) -> Iterator[TestClient]:
        application = create_app(app_settings)
        with TestClient(application) as test_client:
            application.state.health_service = HealthService(
                probes,
                service_name="dw-api-test",
                version="0.0.0-test",
                environment="testing",
                timeout_s=0.3,
            )
            yield test_client

    return _factory


def test_liveness_is_always_200(client_factory):
    with client_factory(health_probes("postgres_down")) as client:
        response = client.get(f"{API_PREFIX}/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_health_returns_200_when_healthy(client_factory):
    with client_factory(health_probes("postgres_ok", "redis_ok")) as client:
        response = client.get(f"{API_PREFIX}/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == SystemStatus.HEALTHY.value
    assert {c["name"] for c in body["components"]} == {"postgres", "redis"}
    assert body["service"] == "dw-api-test"


def test_non_critical_dependency_failure_degrades_but_stays_200(client_factory):
    with client_factory(health_probes("postgres_ok", "kafka_down")) as client:
        response = client.get(f"{API_PREFIX}/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == SystemStatus.DEGRADED.value
    kafka = next(c for c in body["components"] if c["name"] == "kafka")
    assert kafka["critical"] is False
    assert kafka["status"] == ComponentStatus.DEGRADED.value


def test_critical_dependency_failure_returns_503(client_factory):
    with client_factory(health_probes("postgres_down", "redis_ok")) as client:
        response = client.get(f"{API_PREFIX}/health")
    assert response.status_code == 503
    assert response.json()["status"] == SystemStatus.UNHEALTHY.value


def test_probe_timeout_is_reported_as_unhealthy(client_factory):
    with client_factory(health_probes("postgres_ok", "kafka_slow")) as client:
        response = client.get(f"{API_PREFIX}/health")
    kafka = next(c for c in response.json()["components"] if c["name"] == "kafka")
    assert kafka["status"] == ComponentStatus.UNHEALTHY.value
    assert "超时" in (kafka["detail"] or "")


def test_readiness_only_reports_critical_dependencies(client_factory):
    with client_factory(health_probes("postgres_ok", "kafka_down")) as client:
        response = client.get(f"{API_PREFIX}/ready")
    assert response.status_code == 200
    body = response.json()
    assert [c["name"] for c in body["components"]] == ["postgres"]


def test_readiness_fails_when_postgres_is_down(client_factory):
    with client_factory(health_probes("postgres_down")) as client:
        response = client.get(f"{API_PREFIX}/ready")
    assert response.status_code == 503


def test_request_id_is_echoed_back(client_factory):
    with client_factory(health_probes("postgres_ok")) as client:
        response = client.get(f"{API_PREFIX}/health", headers={"X-Request-ID": "rid-abc"})
    assert response.headers["x-request-id"] == "rid-abc"
    assert response.headers["x-process-time-ms"]


def test_request_id_is_generated_when_absent(client_factory):
    with client_factory(health_probes("postgres_ok")) as client:
        response = client.get(f"{API_PREFIX}/health")
    generated = response.headers["x-request-id"]
    assert generated and generated != "-"


def test_security_headers_are_injected(client_factory):
    with client_factory(health_probes("postgres_ok")) as client:
        response = client.get(f"{API_PREFIX}/live")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_openapi_is_exposed_under_api_prefix(app_settings):
    application = create_app(app_settings)
    client = TestClient(application)
    assert client.get(f"{API_PREFIX}/openapi.json").status_code == 200
