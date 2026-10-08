"""Alembic 运行环境（async + asyncpg）。

要点：
* 连接串来自 `dw_infrastructure.Settings`，与业务代码同一份配置；
* 使用 `NullPool`：迁移是短命的一次性连接，不需要池化；
* 导入 `dw_domain.models` 以把全部表注册进 metadata，autogenerate 才不会漏表。
"""

from __future__ import annotations

import asyncio

from alembic import context
from dw_domain.models import Base
from dw_infrastructure.config import get_settings
# 让 Alembic 的 target_metadata 纳入 RAG 模型（rag_documents / rag_document_chunks）
import dw_infrastructure.rag.models  # noqa: F401
# 同上：纳入记忆层模型（user_memories）
import dw_infrastructure.memory.models  # noqa: F401
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

settings = get_settings()
# ConfigParser 使用 % 做插值，而 DSN 经过 URL 编码后可能含 %，需转义
config.set_main_option("sqlalchemy.url", settings.async_database_dsn.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL 脚本，不连数据库。"""
    context.configure(
        url=settings.async_database_dsn,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
