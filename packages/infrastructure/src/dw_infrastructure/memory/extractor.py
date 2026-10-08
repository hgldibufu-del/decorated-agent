"""记忆抽取 —— Phase 10。

`MemoryExtractor` 是**协议**，`RuleBasedExtractor` 是确定性的默认实现：

* **纯函数、零外部依赖**：同一句话永远抽出同一批候选，可单测、可离线复现；
* **否定先挡掉**：「不要新中式」不应被记成「偏好新中式」——
  匹配命中后先看**紧邻其前**的否定词，命中即丢弃该候选；
* **一值一键**：`focus.storage` / `focus.bright` 各占一个 key，
  否则两个偏好会互相覆盖（唯一约束是 `(user, kind, key)`）。

mem0ai 接缝：将来用 LLM 做抽取 / 冲突消解，只需实现同一 `extract(text)` 协议，
存储、编排与测试都不必改动。

局限（明确声明）：只覆盖**显式关键词**，不做条件句（「如果预算够就…」）与
否定从句的语义分析 —— 这类判断需要 LLM，属接缝范围。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from dw_schemas.memory import MemoryCandidate, MemoryKind, MemoryValue

# 否定词：出现在匹配片段**紧邻之前**时，该候选作废
_NEGATIONS = ("不", "别", "勿", "非", "免", "厌", "拒绝", "避免", "无需", "不要")
# 向前回看的窗口：中文否定一般紧贴关键词（「不要新中式」「预算不敏感」）
_LOOKBACK = 4

# 风格同义词 → 设计目录里的规范名（与 `design_styles.name` 对齐）
STYLE_ALIASES: dict[str, str] = {
    "现代简约": "现代简约",
    "现代": "现代简约",
    "简约": "现代简约",
    "新中式": "新中式",
    "中式": "新中式",
    "北欧": "北欧",
    "工业风": "工业风",
    "工业": "工业风",
}


@dataclass(frozen=True, slots=True)
class ExtractionRule:
    """一条抽取规则：命中任一关键词即产出一个候选。"""

    kind: MemoryKind
    key: str
    value: MemoryValue
    keywords: tuple[str, ...]
    confidence: float = 0.8


RULES: tuple[ExtractionRule, ...] = (
    # 风格偏好：value 由命中的同义词决定，故 keywords 交给专门的风格规则处理
    ExtractionRule(MemoryKind.PREFERENCE, "budget.sensitivity", "high", ("预算有限", "控制预算", "预算紧张", "性价比", "省钱"), 0.7),
    ExtractionRule(MemoryKind.PREFERENCE, "material.priority", "eco", ("环保", "无甲醛", "绿色材料", "零甲醛"), 0.7),
    ExtractionRule(MemoryKind.PREFERENCE, "material.priority", "premium", ("进口", "高端", "品质优先"), 0.6),
    ExtractionRule(MemoryKind.CONSTRAINT, "schedule.strict", True, ("按期", "不能延期", "赶工", "工期紧", "严格工期"), 0.75),
    ExtractionRule(MemoryKind.PREFERENCE, "focus.storage", True, ("收纳", "储物"), 0.7),
    ExtractionRule(MemoryKind.PREFERENCE, "focus.bright", True, ("采光", "明亮", "通透"), 0.6),
    ExtractionRule(MemoryKind.PREFERENCE, "focus.low_maintenance", True, ("好打理", "易清洁", "免维护"), 0.6),
)

_STYLE_RULE_CONFIDENCE = 0.85
_STYLE_PATTERN = "|".join(sorted(STYLE_ALIASES, key=len, reverse=True))


def _is_negated(text: str, start: int) -> bool:
    """匹配片段之前紧邻处是否有否定词。"""
    prefix = text[max(0, start - _LOOKBACK) : start]
    if not prefix:
        return False
    # 「不要新中式」：`不要` 与 `新中式` 之间可能有空格
    return any(negation in prefix for negation in _NEGATIONS)


def _dedupe(candidates: list[MemoryCandidate]) -> list[MemoryCandidate]:
    """同 key 只保留置信度最高的一条（一值一键，避免写入时互相覆盖）。"""
    best: dict[str, MemoryCandidate] = {}
    for candidate in candidates:
        current = best.get(candidate.key)
        if current is None or candidate.confidence > current.confidence:
            best[candidate.key] = candidate
    return list(best.values())


@runtime_checkable
class MemoryExtractor(Protocol):
    """记忆抽取协议（mem0ai / LLM 实现替换此处）。"""

    def extract(self, text: str) -> list[MemoryCandidate]: ...


class RuleBasedExtractor:
    """确定性规则抽取：词典 + 否定守卫，零外部依赖。"""

    def __init__(self, rules: tuple[ExtractionRule, ...] = RULES) -> None:
        self._rules = rules
        self._style_re = re.compile(f"({_STYLE_PATTERN})")

    def extract(self, text: str) -> list[MemoryCandidate]:
        raw = (text or "").strip()
        if not raw:
            return []

        found: list[MemoryCandidate] = []

        for match in self._style_re.finditer(raw):
            if _is_negated(raw, match.start()):
                continue
            style = STYLE_ALIASES[match.group(1)]
            found.append(
                MemoryCandidate(
                    kind=MemoryKind.PREFERENCE,
                    key="style",
                    value=style,
                    confidence=_STYLE_RULE_CONFIDENCE,
                )
            )

        for rule in self._rules:
            for keyword in rule.keywords:
                position = raw.find(keyword)
                if position < 0:
                    continue
                if _is_negated(raw, position):
                    continue
                found.append(
                    MemoryCandidate(
                        kind=rule.kind,
                        key=rule.key,
                        value=rule.value,
                        confidence=rule.confidence,
                    )
                )
                break  # 同一规则命中一次即可

        return _dedupe(found)
