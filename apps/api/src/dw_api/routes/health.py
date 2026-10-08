"""健康检查路由 —— 需求文档 §31。

三个探针故意区分语义：
    /live   只证明「进程还活着」，不碰任何下游；
    /ready  只探测不可降级依赖（PostgreSQL），用于负载均衡摘除；
    /health 全量报告，可降级依赖（Redis / Kafka）异常只降级不摘除。
"""

from __future__ import annotations

from dw_infrastructure.health import HealthService
from dw_schemas.health import HealthReport, SystemStatus
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from dw_api.deps import get_health_service

router = APIRouter(tags=["observability"])

_UNHEALTHY_STATUS = 503


def _report_response(report: HealthReport) -> Response:
    """健康 → 200；降级 → 200；不可用 → 503，body 始终是完整 HealthReport。"""
    status_code = 200 if report.status is not SystemStatus.UNHEALTHY else _UNHEALTHY_STATUS
    return JSONResponse(status_code=status_code, content=report.model_dump(mode="json"))


@router.get(
    "/live",
    summary="存活探针",
    response_model=dict[str, str],
)
async def liveness() -> dict[str, str]:
    return {"status": "alive"}


@router.get(
    "/ready",
    summary="就绪探针（仅不可降级依赖）",
    responses={200: {"model": HealthReport}, 503: {"model": HealthReport}},
)
async def readiness(
    service: HealthService = Depends(get_health_service),
) -> Response:
    report = await service.check(only_critical=True)
    return _report_response(report)


@router.get(
    "/health",
    summary="完整健康检查",
    responses={200: {"model": HealthReport}, 503: {"model": HealthReport}},
)
async def health(
    request: Request, service: HealthService = Depends(get_health_service)
) -> Response:
    report = await service.check()
    return _report_response(report)
