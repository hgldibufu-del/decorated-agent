"""FastAPI 应用工厂 —— 需求文档 §21 / §23。

这里是唯一的 ASGI 组装点：中间件、异常处理器、路由、生命周期资源。
业务逻辑不得出现在此文件。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dw_infrastructure.config import Settings, get_settings
from dw_infrastructure.health import InfrastructureBundle, build_health_service
from dw_infrastructure.logging_setup import configure_logging, get_logger
from dw_infrastructure.observability import configure_tracing
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from dw_api.errors import install_exception_handlers
from dw_api.middleware import (
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    TracingMiddleware,
)
from dw_api.routes.auth import router as auth_router
from dw_api.routes.health import router as health_router
from dw_api.routes.memories import router as memories_router
from dw_api.routes.projects import router as projects_router
from dw_api.routes.reference import router as reference_router
from dw_api.routes.registry import router as registry_router
from dw_api.routes.runs import router as runs_router

logger = get_logger(__name__)

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """进程级资源：基础设施客户端与健康探针随应用生命周期创建 / 释放。"""
    settings: Settings = app.state.settings

    bundle = InfrastructureBundle.from_settings(settings)
    app.state.infrastructure = bundle
    # 业务路由依赖 app.state.database 获取会话，单独暴露避免每次再从 bundle 里取
    app.state.database = bundle.database
    app.state.health_service = build_health_service(bundle, settings)

    logger.info(
        "service started",
        extra={
            "service": settings.service_name,
            "app_env": settings.app_env.value,
            "app_version": settings.app_version,
        },
    )
    try:
        yield
    finally:
        await bundle.aclose()
        logger.info("service stopped", extra={"service": settings.service_name})


def create_app(settings: Settings | None = None) -> FastAPI:
    """构造 FastAPI 应用。传入 settings 便于测试隔离。"""
    resolved = settings or get_settings()
    configure_logging(
        level=resolved.log_level,
        json_format=resolved.log_json,
        service_name=resolved.service_name,
    )
    # Phase 9：默认关闭。未启用时 span 全部为 no-op，启动与既有测试零差异。
    configure_tracing(resolved)

    app = FastAPI(
        title="装修企业 AI Agent Workbench API",
        description=(
            "Supervisor + Specialist Agents 的装修领域 AI Agent 工作台后端。"
            "Phase 0 仅提供工程骨架与健康探针。"
        ),
        version=resolved.app_version,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = resolved

    # Starlette 语义：后注册的中间件更靠外层（先收到请求）。
    # 因此 CORS 最后注册——预检请求在打日志 / 绑定 request_id 之前就被短路返回。
    app.add_middleware(RequestContextMiddleware)  # 最内层
    # Phase 9：追踪层在 request_id 之外，span 覆盖整个请求（含访问日志），
    # 日志与 trace 因 trace_id 绑定而可互查
    app.add_middleware(TracingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    install_exception_handlers(app)
    app.include_router(health_router, prefix=API_PREFIX)
    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(memories_router, prefix=API_PREFIX)
    app.include_router(projects_router, prefix=API_PREFIX)
    app.include_router(reference_router, prefix=API_PREFIX)
    app.include_router(registry_router, prefix=API_PREFIX)
    app.include_router(runs_router, prefix=API_PREFIX)
    return app
