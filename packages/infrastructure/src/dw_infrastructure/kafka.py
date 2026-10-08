"""Kafka Admin 适配 —— 需求文档 §14。

边界提醒：Kafka 表达「发生了什么」，不是 Agent 之间的 RPC 通道。
Phase 0 只做连通性探测；生产 / 消费与 topic 编排属于后续 Phase。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aiokafka.admin import AIOKafkaAdminClient
from aiokafka.errors import KafkaError

from dw_infrastructure.config import Settings
from dw_infrastructure.db import InfrastructureError


class KafkaAdminError(InfrastructureError):
    """Kafka 集群不可达或元数据请求失败。"""


class KafkaAdmin:
    """Kafka 集群元数据探测（每次探测独立建立 Admin 连接，避免长连接僵死）。"""

    def __init__(self, bootstrap_servers: str, *, client_id: str = "dw-infrastructure") -> None:
        if not bootstrap_servers:
            raise KafkaAdminError("缺少 Kafka bootstrap servers")
        self._bootstrap_servers = bootstrap_servers
        self._client_id = client_id

    @classmethod
    def from_settings(cls, settings: Settings) -> KafkaAdmin:
        return cls(settings.kafka_bootstrap_servers)

    @property
    def bootstrap_servers(self) -> str:
        return self._bootstrap_servers

    async def ping(self) -> Mapping[str, Any]:
        """拉取 topic 列表作为连通性证据。"""
        admin = AIOKafkaAdminClient(
            bootstrap_servers=self._bootstrap_servers,
            client_id=self._client_id,
        )
        try:
            await admin.start()
            topics = await admin.list_topics()
        except (KafkaError, OSError) as exc:
            raise KafkaAdminError(f"Kafka 探针失败: {exc}") from exc
        finally:
            await admin.close()
        return {"topic_count": len(topics)}

    async def create_topics(
        self, topic_names: list[str], *, num_partitions: int = 1, replication_factor: int = 1
    ) -> list[str]:
        """幂等建 topic：已存在则跳过，不做覆盖。

        Phase 0 compose 依赖 broker 自动建 topic，但测试/脚本仍可能需要显式创建。
        """
        admin = AIOKafkaAdminClient(
            bootstrap_servers=self._bootstrap_servers,
            client_id=self._client_id,
        )
        from aiokafka.admin import NewTopic

        try:
            await admin.start()
            existing = set(await admin.list_topics())
            to_create = [
                NewTopic(
                    name=topic,
                    num_partitions=num_partitions,
                    replication_factor=replication_factor,
                )
                for topic in topic_names
                if topic not in existing
            ]
            created: list[str] = []
            if to_create:
                await admin.create_topics(to_create, validate_only=False)
                created = [t.name for t in to_create]
            return created
        except (KafkaError, OSError) as exc:
            raise KafkaAdminError(f"创建 Kafka topic 失败: {exc}") from exc
        finally:
            await admin.close()
