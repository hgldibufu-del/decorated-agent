"""PostgreSQL 异步适配 —— 需求文档 §9 / §22。

PostgreSQL 是本项目唯一业务事实源。此处只提供连接与会话能力，
**不承载任何业务表读写**（那是 Phase 1 `packages/domain` + repository 的职责）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from dw_infrastructure.config import Settings


class InfrastructureError(RuntimeError):
    """基础设施层异常基类。"""


class DatabaseError(InfrastructureError):
    """数据库不可达或查询失败。保留原始异常，禁止吞异常。"""


class DatabaseNotConfiguredError(DatabaseError):
    """缺少 DSN 配置。"""


class Database:
    """PostgreSQL 异步引擎封装（惰性创建连接池）。"""

    def __init__(
        self,
        dsn: str,
        *,
        echo: bool = False,
        pool_size: int = 10,
        max_overflow: int = 5,
        pool_pre_ping: bool = True,
    ) -> None:
        if not dsn:
            raise DatabaseNotConfiguredError("缺少数据库连接串")
        self._dsn = dsn
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None
        self._echo = echo
        self._pool_size = pool_size
        self._max_overflow = max_overflow
        self._pool_pre_ping = pool_pre_ping

    @classmethod
    def from_settings(cls, settings: Settings) -> Database:
        return cls(
            settings.async_database_dsn,
            echo=settings.app_debug,
            pool_pre_ping=True,
        )

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            self._engine = create_async_engine(
                self._dsn,
                echo=self._echo,
                pool_size=self._pool_size,
                max_overflow=self._max_overflow,
                pool_pre_ping=self._pool_pre_ping,
            )
            self._session_factory = async_sessionmaker(
                self._engine, expire_on_commit=False, autoflush=False
            )
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """访问前确保引擎已惰性创建。"""
        self.engine  # noqa: B018 —— 触发惰性初始化
        factory = self._session_factory
        if factory is None:
            raise DatabaseError("会话工厂未随引擎初始化")
        return factory

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """事务边界：正常提交，异常回滚并向上抛出。"""
        async with self.session_factory() as current:
            try:
                yield current
            except Exception:
                await current.rollback()
                raise
            else:
                await current.commit()

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[Any]:
        async with self.engine.connect() as connection:
            yield connection

    async def ping(self) -> Mapping[str, Any]:
        """连通性探针，返回结构化元数据供健康报告使用。"""
        try:
            async with self._connect() as connection:
                version = (
                    await connection.execute(text("SELECT current_setting('server_version')"))
                ).scalar_one()
                pgvector_version = (
                    await connection.execute(
                        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                    )
                ).scalar()
        except (SQLAlchemyError, OSError) as exc:
            # 连不上端口时 asyncpg 会抛原始 OSError，必须归一化成 DatabaseError，
            # 否则调用方无法用单一类型处理基础设施故障。
            raise DatabaseError(f"PostgreSQL 探针失败: {exc}") from exc
        return {
            "server_version": version,
            "pgvector": pgvector_version or "not-installed",
        }

    async def dispose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
