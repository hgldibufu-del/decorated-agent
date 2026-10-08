"""Kafka 集成测试 —— 需求文档 §14 的连通性与幂等建 topic 验证。"""

from __future__ import annotations

import pytest
from dw_infrastructure.config import get_settings
from dw_infrastructure.kafka import KafkaAdmin, KafkaAdminError

SMOKE_TOPIC = "dw-phase0-smoke"


@pytest.fixture
def admin() -> KafkaAdmin:
    return KafkaAdmin.from_settings(get_settings())


def test_missing_bootstrap_servers_is_rejected():
    with pytest.raises(KafkaAdminError):
        KafkaAdmin("")


@pytest.mark.integration
async def test_ping_reports_topic_count(admin):
    metadata = await admin.ping()
    assert isinstance(metadata["topic_count"], int)
    assert metadata["topic_count"] >= 0


@pytest.mark.integration
async def test_create_topics_is_idempotent(admin):
    await admin.create_topics([SMOKE_TOPIC])
    second_call = await admin.create_topics([SMOKE_TOPIC])
    assert second_call == [], "重复创建同名 topic 必须幂等返回空列表，而不是报错"


@pytest.mark.integration
async def test_topic_appears_in_metadata_after_creation(admin):
    await admin.create_topics([SMOKE_TOPIC])
    ping_metadata = await admin.ping()
    assert ping_metadata["topic_count"] >= 1


@pytest.mark.integration
async def test_unreachable_broker_raises_admin_error():
    unreachable = KafkaAdmin("localhost:9095")
    with pytest.raises(KafkaAdminError):
        await unreachable.ping()
