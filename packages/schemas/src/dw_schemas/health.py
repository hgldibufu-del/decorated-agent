"""健康检查契约 —— 需求文档 §31 质量门控的基础能力。

设计要点：
* 组件级健康（ComponentHealth）与系统级健康（HealthReport）分离；
* `critical` 区分「不可降级」与「可降级」依赖：
  PostgreSQL 是业务事实源 → 不可降级；Redis / Kafka 临时不可用 → 系统降级但仍可服务。
  这样 /ready 不会因为一个缓存抖动而摘掉整个实例。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ComponentStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class SystemStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentHealth(BaseModel):
    """单个下游依赖的健康快照。"""

    name: str = Field(..., description="组件标识，如 postgres / redis / kafka")
    status: ComponentStatus
    critical: bool = Field(default=True, description="该组件不可用是否导致服务整体不可用")
    latency_ms: float = Field(0.0, ge=0, description="探针耗时")
    detail: str | None = Field(default=None, description="人类可读的补充说明")
    metadata: dict[str, Any] = Field(default_factory=dict, description="组件上报的结构化信息")


class HealthReport(BaseModel):
    """一次健康检查的完整结果。"""

    status: SystemStatus
    service: str
    version: str
    environment: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    components: list[ComponentHealth] = Field(default_factory=list)

    @property
    def unhealthy_components(self) -> list[ComponentHealth]:
        return [c for c in self.components if c.status is ComponentStatus.UNHEALTHY]


def aggregate_status(components: Sequence[ComponentHealth]) -> SystemStatus:
    """由组件状态聚合出系统状态。

    规则（可单测的纯函数，不含 IO）：
    1. 任一 critical 组件 unhealthy → UNHEALTHY；
    2. 任一组件 unhealthy（非 critical）或 degraded → DEGRADED；
    3. 其余 → HEALTHY。
    """
    degraded = False
    for component in components:
        if component.status is ComponentStatus.UNHEALTHY:
            if component.critical:
                return SystemStatus.UNHEALTHY
            degraded = True
        elif component.status is ComponentStatus.DEGRADED:
            degraded = True
    return SystemStatus.DEGRADED if degraded else SystemStatus.HEALTHY
