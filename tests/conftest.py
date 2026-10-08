"""pytest 全局 fixture。

集成测试（marked `integration`）默认**必须执行**：中间件不可达时应该失败而不是悄悄跳过。
只有在 CI 等确实没有基础设施的场景下，显式设置 `SKIP_INTEGRATION=1` 才会跳过。
这样做的理由：静默跳过会让「永远绿」的假象掩盖真实回归。
"""

from __future__ import annotations

import asyncio
import os

import pytest
from dw_infrastructure.config import Settings, get_settings


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.getenv("SKIP_INTEGRATION", "").lower() not in {"1", "true", "yes"}:
        return
    skip = pytest.mark.skip(reason="SKIP_INTEGRATION 已设置，跳过需要真实中间件的用例")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
async def slow_probe_fn():
    """永不返回的探针，用于验证超时分支。"""

    async def _probe():
        await asyncio.sleep(30)
        return {}

    return _probe
