"""记忆层单测 —— Phase 10（抽取与画像，纯逻辑，无需数据库）。"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from dw_agent_runtime.memory_tools import MemoryRecallIn, MemoryRememberIn
from dw_infrastructure.memory import RuleBasedExtractor
from dw_schemas.memory import MemoryItem, MemoryKind, MemoryProfile
from pydantic import ValidationError

EXTRACTOR = RuleBasedExtractor()


def _extracted(text: str) -> dict[str, object]:
    return {candidate.key: candidate.value for candidate in EXTRACTOR.extract(text)}


def test_extract_is_deterministic():
    text = "预算有限，喜欢新中式，最好有收纳"
    assert EXTRACTOR.extract(text) == EXTRACTOR.extract(text)


def test_extract_normalizes_style_aliases():
    assert _extracted("想要新中式的感觉")["style"] == "新中式"
    assert _extracted("喜欢简约风")["style"] == "现代简约"
    assert _extracted("考虑北欧")["style"] == "北欧"
    assert _extracted("偏工业")["style"] == "工业风"


def test_extract_picks_up_multiple_preferences():
    keys = _extracted("预算有限，喜欢现代简约，重视采光和收纳")
    assert keys["style"] == "现代简约"
    assert keys["budget.sensitivity"] == "high"
    assert keys["focus.storage"] is True
    assert keys["focus.bright"] is True


def test_extract_records_schedule_constraint_as_constraint_kind():
    candidates = EXTRACTOR.extract("工期紧，必须按期交付")
    schedule = next(item for item in candidates if item.key == "schedule.strict")
    assert schedule.value is True
    assert schedule.kind is MemoryKind.CONSTRAINT


def test_extract_ignores_negated_preference():
    """核心正确性：否定句不能被记成肯定偏好。"""
    assert "style" not in _extracted("不要新中式")
    assert "style" not in _extracted("不喜欢工业风")
    assert "budget.sensitivity" not in _extracted("预算不紧张")


def test_extract_keeps_positive_constraints_phrased_with_negation():
    """「不能延期」本身是正向约束，不能被否定守卫误杀。"""
    assert _extracted("不能延期")["schedule.strict"] is True


def test_extract_returns_nothing_for_unrelated_text():
    assert EXTRACTOR.extract("") == []
    assert EXTRACTOR.extract("   ") == []
    assert EXTRACTOR.extract("你好") == []


def test_extract_dedupes_same_key():
    """两个风格词命中同一 key，只留一条（否则写入时会互相覆盖）。"""
    styles = [c for c in EXTRACTOR.extract("现代简约，也考虑过北欧") if c.key == "style"]
    assert len(styles) == 1


def _item(key: str, value: object, confidence: float = 1.0) -> MemoryItem:
    return MemoryItem(
        id=uuid4(),
        kind=MemoryKind.PREFERENCE,
        key=key,
        value=value,  # type: ignore[arg-type]
        confidence=confidence,
        updated_at=datetime.now(timezone.utc),
    )


def test_profile_value_for_prefers_higher_confidence():
    profile = MemoryProfile(
        user_id=uuid4(),
        items=[_item("style", "北欧", 0.5), _item("style", "新中式", 0.9)],
    )
    assert profile.value_for("style") == "新中式"
    assert profile.value_for("unknown") is None


def test_profile_as_notes_is_human_readable():
    profile = MemoryProfile(user_id=uuid4(), items=[_item("style", "北欧")])
    assert profile.as_notes() == ["style=北欧"]


def test_recall_input_bounds_limit():
    assert MemoryRecallIn().limit == 20
    with pytest.raises(ValidationError):
        MemoryRecallIn(limit=0)


def test_remember_input_requires_key():
    with pytest.raises(ValidationError):
        MemoryRememberIn(value="新中式")  # type: ignore[call-arg]
