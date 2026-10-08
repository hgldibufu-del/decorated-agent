"""PostgreSQL 集成测试 —— 需要 docker compose 提供的真实数据库。"""

from __future__ import annotations

import pytest
from dw_infrastructure.config import get_settings
from dw_infrastructure.db import Database, DatabaseError, DatabaseNotConfiguredError
from sqlalchemy import text

PROBE_TABLE = "workbench.tmp_phase0_probe"


@pytest.fixture
def database() -> Database:
    return Database.from_settings(get_settings())


async def _table_exists(database: Database) -> bool:
    async with database.session() as session:
        result = await session.execute(text(f"SELECT to_regclass('{PROBE_TABLE}')"))
        return result.scalar() is not None


def test_empty_dsn_is_rejected():
    with pytest.raises(DatabaseNotConfiguredError):
        Database("")


@pytest.mark.integration
async def test_ping_reports_server_and_pgvector(database):
    metadata = await database.ping()
    assert metadata["server_version"]
    assert metadata["pgvector"] != "not-installed", (
        "pgvector 扩展缺失，请确认 infra/postgres/init.sql 已执行"
    )


@pytest.mark.integration
async def test_session_can_execute_and_commit(database):
    async with database.session() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar_one() == 1


@pytest.mark.integration
async def test_session_rolls_back_on_exception(database):
    async with database.session() as session:
        await session.execute(text(f"DROP TABLE IF EXISTS {PROBE_TABLE}"))

    assert await _table_exists(database) is False

    with pytest.raises(RuntimeError, match="boom"):
        async with database.session() as session:
            await session.execute(text(f"CREATE TABLE {PROBE_TABLE} (id int)"))
            raise RuntimeError("boom")

    # 事务必须被回滚：表不能残留
    assert await _table_exists(database) is False


@pytest.mark.integration
async def test_unreachable_database_is_normalized_to_database_error():
    """端口不可达时 asyncpg 抛的是原始 OSError，必须被归一化成 DatabaseError。"""
    unreachable = Database(
        "postgresql+asyncpg://decoration:decoration@localhost:5599/workbench",
        pool_size=1,
        max_overflow=0,
    )
    try:
        with pytest.raises(DatabaseError) as excinfo:
            await unreachable.ping()
        assert "探针失败" in str(excinfo.value)
    finally:
        await unreachable.dispose()
