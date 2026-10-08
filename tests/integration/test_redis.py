"""Redis 集成测试 —— 验证短期状态存储可用，且不作为业务事实源。"""

from __future__ import annotations

import pytest
from dw_infrastructure.config import get_settings
from dw_infrastructure.redis import RedisCache, RedisConnectionError

KEY = "dw:phase0:probe"


@pytest.fixture
async def cache() -> RedisCache:
    store = RedisCache.from_settings(get_settings())
    yield store
    await store.client.delete(KEY)
    await store.close()


@pytest.mark.integration
async def test_ping_reports_version(cache):
    metadata = await cache.ping()
    assert metadata["redis_version"]
    assert isinstance(metadata["connected_clients"], int)


@pytest.mark.integration
async def test_key_value_roundtrip(cache):
    await cache.client.set(KEY, "v1", ex=30)
    assert await cache.client.get(KEY) == "v1"
    await cache.client.delete(KEY)
    assert await cache.client.get(KEY) is None


@pytest.mark.integration
async def test_ttl_expires_as_short_term_state():
    store = RedisCache.from_settings(get_settings())
    try:
        await store.client.set(KEY, "v", ex=1)
        ttl = await store.client.ttl(KEY)
        assert 0 < ttl <= 1
    finally:
        await store.client.delete(KEY)
        await store.close()


@pytest.mark.integration
async def test_unreachable_redis_raises_connection_error():
    store = RedisCache("redis://127.0.0.1:6399/0", socket_timeout_s=1.0)
    try:
        with pytest.raises(RedisConnectionError):
            await store.ping()
    finally:
        await store.close()
