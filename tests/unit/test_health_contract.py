"""健康状态聚合规则单测 —— 纯逻辑，不依赖 IO。"""

from __future__ import annotations

import pytest
from dw_schemas.health import (
    ComponentHealth,
    ComponentStatus,
    HealthReport,
    SystemStatus,
    aggregate_status,
)


def component(status: ComponentStatus, *, critical: bool = True) -> ComponentHealth:
    return ComponentHealth(name="probe", status=status, critical=critical)


def test_all_healthy_is_healthy():
    assert (
        aggregate_status([component(ComponentStatus.HEALTHY), component(ComponentStatus.HEALTHY)])
        is SystemStatus.HEALTHY
    )


def test_critical_unhealthy_means_system_unhealthy():
    components = [
        component(ComponentStatus.HEALTHY),
        component(ComponentStatus.UNHEALTHY, critical=True),
        component(ComponentStatus.UNHEALTHY, critical=False),
    ]
    assert aggregate_status(components) is SystemStatus.UNHEALTHY


def test_non_critical_unhealthy_only_degrades():
    """Redis / Kafka 不可用不应摘除实例，只降级。"""
    components = [
        component(ComponentStatus.HEALTHY, critical=True),
        component(ComponentStatus.UNHEALTHY, critical=False),
    ]
    assert aggregate_status(components) is SystemStatus.DEGRADED


def test_degraded_component_degrades_system():
    assert aggregate_status([component(ComponentStatus.DEGRADED)]) is SystemStatus.DEGRADED


def test_empty_component_list_is_healthy():
    assert aggregate_status([]) is SystemStatus.HEALTHY


def test_report_exposes_unhealthy_components():
    report = HealthReport(
        status=SystemStatus.DEGRADED,
        service="dw-api",
        version="0.1.0",
        environment="testing",
        components=[
            ComponentHealth(name="redis", status=ComponentStatus.UNHEALTHY, critical=False),
            ComponentHealth(name="postgres", status=ComponentStatus.HEALTHY),
        ],
    )
    assert [c.name for c in report.unhealthy_components] == ["redis"]


def test_component_latency_must_be_non_negative():
    with pytest.raises(ValueError):
        ComponentHealth(name="x", status=ComponentStatus.HEALTHY, latency_ms=-1)
