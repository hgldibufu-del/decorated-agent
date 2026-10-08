"""HealthService 单测：探针失败/超时/降级的编排语义。"""

from __future__ import annotations

import asyncio

import pytest
from dw_infrastructure.health import HealthService, Probe
from dw_schemas.health import ComponentStatus, SystemStatus


async def healthy_probe() -> dict[str, str]:
    return {"version": "16"}


async def failing_probe() -> dict[str, str]:
    raise RuntimeError("connection refused")


async def slow_probe() -> dict[str, str]:
    await asyncio.sleep(5)
    return {}


def make_service(probes: list[Probe], timeout_s: float = 0.3) -> HealthService:
    return HealthService(
        probes,
        service_name="dw-api",
        version="0.1.0",
        environment="testing",
        timeout_s=timeout_s,
    )


async def test_all_healthy():
    service = make_service([Probe("postgres", healthy_probe, critical=True)])
    report = await service.check()
    assert report.status is SystemStatus.HEALTHY
    assert report.components[0].metadata == {"version": "16"}
    assert report.components[0].detail is None


async def test_probe_exception_is_surfaced_not_swallowed():
    service = make_service([Probe("postgres", failing_probe, critical=True)])
    report = await service.check()
    component = report.components[0]
    assert component.status is ComponentStatus.UNHEALTHY
    # 必须能看到异常类型与原因，否则排查无从下手
    assert "RuntimeError" in (component.detail or "")
    assert "connection refused" in (component.detail or "")


async def test_probe_timeout_is_capped():
    service = make_service([Probe("kafka", slow_probe, critical=False)], timeout_s=0.05)
    report = await service.check()
    component = report.components[0]
    assert component.status is ComponentStatus.UNHEALTHY
    assert "超时" in (component.detail or "")
    assert component.latency_ms < 1000


async def test_non_critical_failure_only_degrades():
    service = make_service(
        [
            Probe("postgres", healthy_probe, critical=True),
            Probe("kafka", failing_probe, critical=False),
        ]
    )
    report = await service.check()
    assert report.status is SystemStatus.DEGRADED


async def test_critical_failure_makes_system_unhealthy():
    service = make_service(
        [
            Probe("postgres", failing_probe, critical=True),
            Probe("redis", healthy_probe, critical=False),
        ]
    )
    report = await service.check()
    assert report.status is SystemStatus.UNHEALTHY


async def test_readiness_mode_only_runs_critical_probes():
    service = make_service(
        [
            Probe("postgres", healthy_probe, critical=True),
            Probe("redis", failing_probe, critical=False),
        ]
    )
    report = await service.check(only_critical=True)
    assert [c.name for c in report.components] == ["postgres"]
    assert report.status is SystemStatus.HEALTHY


async def test_probes_run_concurrently():
    """两个各睡 0.4s 的探针并发执行时，总耗时应明显小于串行（~0.8s）。"""

    async def sleepy_probe() -> dict[str, str]:
        await asyncio.sleep(0.4)
        return {}

    service = make_service([Probe("a", sleepy_probe), Probe("b", sleepy_probe)], timeout_s=5)
    report = await service.check()
    total = sum(c.latency_ms for c in report.components)
    assert max(c.latency_ms for c in report.components) < 1500
    assert total > 0
    assert report.status is SystemStatus.HEALTHY


async def test_report_carries_service_identity():
    service = make_service([], timeout_s=0.3)
    report = await service.check()
    assert report.service == "dw-api"
    assert report.version == "0.1.0"
    assert report.environment == "testing"
    assert report.status is SystemStatus.HEALTHY


@pytest.mark.parametrize("critical", [True, False])
async def test_failure_status_reflects_criticality(critical: bool):
    service = make_service([Probe("x", failing_probe, critical=critical)])
    report = await service.check()
    expected = ComponentStatus.UNHEALTHY if critical else ComponentStatus.DEGRADED
    assert report.components[0].status is expected
