"""健康检查编排 —— 需求文档 §31。

职责边界：本模块只知道「怎么探测」与「如何聚合状态」，
不知道 API 怎么暴露这些结果（那是 `apps/api` 的事）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from dw_schemas.health import (
    ComponentHealth,
    ComponentStatus,
    HealthReport,
    aggregate_status,
)

from dw_infrastructure.config import Settings
from dw_infrastructure.db import Database
from dw_infrastructure.kafka import KafkaAdmin
from dw_infrastructure.redis import RedisCache

logger = logging.getLogger(__name__)

ProbeFn = Callable[[], Awaitable[Mapping[str, Any]]]


@dataclass(frozen=True, slots=True)
class Probe:
    """一个下游依赖的探针定义。"""

    name: str
    probe_fn: ProbeFn
    # critical=True：该依赖不可用 = 服务整体不可用（PostgreSQL）
    # critical=False：该依赖不可用 = 服务降级但仍可服务（Redis / Kafka 缓存层）
    critical: bool = True


@dataclass(slots=True)
class InfrastructureBundle:
    """一组基础设施客户端，生命周期与 app 对齐（启动创建、关闭释放）。"""

    database: Database
    cache: RedisCache
    kafka_admin: KafkaAdmin

    @classmethod
    def from_settings(cls, settings: Settings) -> InfrastructureBundle:
        return cls(
            database=Database.from_settings(settings),
            cache=RedisCache.from_settings(settings),
            kafka_admin=KafkaAdmin.from_settings(settings),
        )

    async def aclose(self) -> None:
        await self.database.dispose()
        await self.cache.close()


def default_probes(bundle: InfrastructureBundle) -> list[Probe]:
    """按依赖重要性分级注册探针。"""
    return [
        Probe("postgres", bundle.database.ping, critical=True),
        Probe("redis", bundle.cache.ping, critical=False),
        Probe("kafka", bundle.kafka_admin.ping, critical=False),
    ]


class HealthService:
    """并发执行所有探针，并聚合出系统状态。"""

    def __init__(
        self,
        probes: Sequence[Probe],
        *,
        service_name: str,
        version: str,
        environment: str,
        timeout_s: float,
    ) -> None:
        self._probes = list(probes)
        self._service_name = service_name
        self._version = version
        self._environment = environment
        self._timeout_s = timeout_s

    async def check(self, *, only_critical: bool = False) -> HealthReport:
        """执行一次健康检查。

        only_critical=True 时只探测不可降级依赖，用于 readiness 探针快速判定。
        """
        targets = [p for p in self._probes if p.critical or not only_critical]
        results = await asyncio.gather(*(self._run(probe) for probe in targets))
        components = list(results)
        return HealthReport(
            status=aggregate_status(components),
            service=self._service_name,
            version=self._version,
            environment=self._environment,
            components=components,
        )

    async def _run(self, probe: Probe) -> ComponentHealth:
        started = perf_counter()
        status = ComponentStatus.HEALTHY
        detail: str | None = None
        meta: dict[str, Any] = {}
        try:
            metadata: Mapping[str, Any] = await asyncio.wait_for(
                probe.probe_fn(), timeout=self._timeout_s
            )
        except (asyncio.TimeoutError, TimeoutError):
            status = ComponentStatus.UNHEALTHY
            detail = f"探针超时（>{self._timeout_s:.2f}s）"
        except Exception as exc:  # 记录完整类型与信息后向上封装，不吞异常
            logger.warning(
                "health probe failed",
                extra={
                    "component": probe.name,
                    "critical": probe.critical,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            status = ComponentStatus.UNHEALTHY if probe.critical else ComponentStatus.DEGRADED
            detail = f"{type(exc).__name__}: {exc}"
        else:
            meta = dict(metadata)
        return ComponentHealth(
            name=probe.name,
            status=status,
            critical=probe.critical,
            latency_ms=round((perf_counter() - started) * 1000, 2),
            detail=detail,
            metadata=meta,
        )


def build_health_service(bundle: InfrastructureBundle, settings: Settings) -> HealthService:
    """按配置组装健康检查服务。"""
    return HealthService(
        default_probes(bundle),
        service_name=settings.service_name,
        version=settings.app_version,
        environment=settings.app_env.value,
        timeout_s=settings.health_probe_timeout_s,
    )
