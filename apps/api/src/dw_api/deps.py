"""FastAPI 依赖项：把 app.state 上的运行时对象取出并做类型收窄。"""

from __future__ import annotations

from dw_infrastructure.config import Settings
from dw_infrastructure.health import HealthService
from fastapi import Request


def current_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_health_service(request: Request) -> HealthService:
    service: HealthService = request.app.state.health_service
    return service
