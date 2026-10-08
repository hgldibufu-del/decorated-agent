"""Redis 适配 —— 需求文档 §9。

Redis 只负责短期运行状态：会话快照、流式状态、缓存、分布式锁、限流计数。
**禁止把 Redis 当作业务事实源**（那是 PostgreSQL 的职责）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from dw_infrastructure.config import Settings
from dw_infrastructure.db import InfrastructureError


class RedisConnectionError(InfrastructureError):
    """Redis 不可达。"""


class RedisCache:
    """Redis 异步客户端封装（惰性连接）。"""

    def __init__(self, url: str, *, socket_timeout_s: float = 3.0) -> None:
        if not url:
            raise RedisConnectionError("缺少 Redis 连接串")
        self._url = url
        self._socket_timeout_s = socket_timeout_s
        self._client: Redis | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> RedisCache:
        return cls(settings.redis_url, socket_timeout_s=settings.health_probe_timeout_s)

    @property
    def client(self) -> Redis:
        if self._client is None:
            self._client = Redis.from_url(
                self._url,
                decode_responses=True,
                socket_timeout=self._socket_timeout_s,
                socket_connect_timeout=self._socket_timeout_s,
            )
        return self._client

    async def ping(self) -> Mapping[str, Any]:
        """连通性探针。"""
        try:
            if not await self.client.ping():
                raise RedisConnectionError("Redis 返回了非预期响应")
            server_info: dict[str, Any] = await self.client.info("server")
        except RedisError as exc:
            raise RedisConnectionError(f"Redis 探针失败: {exc}") from exc
        return {
            "redis_version": server_info.get("redis_version", "unknown"),
            "connected_clients": server_info.get("connected_clients", 0),
        }

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
