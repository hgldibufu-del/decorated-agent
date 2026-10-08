"""端到端：HTTP → HealthService → 真实 Postgres / Redis / Kafka 探针。

与 tests/api/test_health_routes.py 的区别：那里用受控探针验证分支语义，
这里用真实中间件验证「接线」是否正确。
"""

from __future__ import annotations

import pytest
from dw_api.app import API_PREFIX, create_app
from dw_infrastructure.config import Settings
from dw_schemas.health import SystemStatus
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    application = create_app(
        Settings(
            app_env="testing", log_json=False, log_level="WARNING", health_probe_timeout_ms=5000
        )
    )
    with TestClient(application) as test_client:
        yield test_client


@pytest.mark.integration
def test_health_reports_every_component(client):
    response = client.get(f"{API_PREFIX}/health")
    body = response.json()
    assert {component["name"] for component in body["components"]} == {
        "postgres",
        "redis",
        "kafka",
    }
    # 基础设施齐备时不允许出现降级
    assert body["status"] == SystemStatus.HEALTHY.value, body


@pytest.mark.integration
def test_readiness_only_probes_postgres(client):
    response = client.get(f"{API_PREFIX}/ready")
    assert response.status_code == 200
    assert [c["name"] for c in response.json()["components"]] == ["postgres"]


@pytest.mark.integration
def test_pgvector_is_available(client):
    body = client.get(f"{API_PREFIX}/health").json()
    postgres = next(c for c in body["components"] if c["name"] == "postgres")
    assert postgres["metadata"]["pgvector"] != "not-installed"
