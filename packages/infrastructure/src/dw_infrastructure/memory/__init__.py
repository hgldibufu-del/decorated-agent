"""记忆层适配器 —— Phase 10。

对外只暴露两件事：存储协议与抽取协议（外加确定性的默认实现）。
编排侧（`dw_agent_runtime`）只依赖协议，因此换 mem0ai / 向量检索时不必改业务代码。
"""

from dw_infrastructure.memory.extractor import (
    RULES,
    STYLE_ALIASES,
    ExtractionRule,
    MemoryExtractor,
    RuleBasedExtractor,
)
from dw_infrastructure.memory.models import UserMemory
from dw_infrastructure.memory.store import (
    DEFAULT_RECALL_LIMIT,
    MAX_RECALL_LIMIT,
    MemoryStore,
    PostgresMemoryStore,
)

__all__ = [
    "DEFAULT_RECALL_LIMIT",
    "MAX_RECALL_LIMIT",
    "RULES",
    "STYLE_ALIASES",
    "ExtractionRule",
    "MemoryExtractor",
    "MemoryStore",
    "PostgresMemoryStore",
    "RuleBasedExtractor",
    "UserMemory",
]
