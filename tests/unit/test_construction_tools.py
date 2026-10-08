"""Construction 工具纯逻辑单测（不依赖 DB）：进度分析 / 验收打分 / 技能编排。"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from dw_agent_runtime.construction_tools import _analyze_progress, _grade_checklist
from dw_agent_runtime.skills import run_construction_review


def test_analyze_progress_computes_deviation_and_risk():
    milestones = [
        {"stage": "水电改造", "seq": 1, "planned_days": 7, "actual_days": 7, "status": "completed"},
        {"stage": "泥瓦工程", "seq": 2, "planned_days": 10, "actual_days": 13, "status": "completed"},
        {"stage": "木工工程", "seq": 3, "planned_days": 8, "actual_days": None, "status": "in_progress"},
        {"stage": "油漆工程", "seq": 4, "planned_days": 6, "actual_days": None, "status": "pending"},
    ]
    result = _analyze_progress(milestones)

    assert result["total_planned_days"] == 31
    assert result["total_actual_days"] == 20
    assert result["progress_ratio"] == 0.5
    assert result["at_risk"] is True
    assert result["delayed_stages"] == [
        {"stage": "泥瓦工程", "deviation_days": 3, "status": "completed"}
    ]
    # 未开始阶段的偏差为 None（不以 0 误报）
    assert result["stages"][2]["deviation_days"] is None


def test_analyze_progress_no_delay_is_not_at_risk():
    milestones = [
        {"stage": "水电改造", "seq": 1, "planned_days": 7, "actual_days": 6, "status": "completed"},
    ]
    result = _analyze_progress(milestones)
    assert result["at_risk"] is False
    assert result["delayed_stages"] == []
    assert result["progress_ratio"] == 1.0


def test_analyze_progress_empty_is_safe():
    result = _analyze_progress([])
    assert result["stages"] == []
    assert result["at_risk"] is False
    assert result["progress_ratio"] == 0.0


def test_grade_checklist_weighted_score():
    items = [
        {"category": "水电", "item": "强弱电分离", "weight": 3, "severity": "高"},
        {"category": "防水", "item": "闭水试验", "weight": 1, "severity": "高"},
    ]
    graded = _grade_checklist(items, ["闭水试验"])
    assert graded["total_weight"] == 4
    assert graded["passed_weight"] == 3
    assert graded["score"] == 0.75
    assert graded["passed"] is False
    assert graded["defects"][0]["item"] == "闭水试验"


def test_grade_checklist_all_pass():
    items = [{"category": "泥瓦", "item": "墙地砖空鼓", "weight": 2, "severity": "中"}]
    graded = _grade_checklist(items, [])
    assert graded["score"] == 1.0
    assert graded["passed"] is True
    assert graded["defects"] == []


class _FakeExecutor:
    def __init__(self, outputs: dict) -> None:
        self._outputs = outputs
        self.calls: list[tuple] = []

    async def call(self, tool_id: str, params: dict, idempotency_key: str | None = None):
        self.calls.append((tool_id, params, idempotency_key))
        return SimpleNamespace(tool_id=tool_id, output=self._outputs[tool_id], replayed=False, attempt=1)


def _ctx(executor: _FakeExecutor) -> SimpleNamespace:
    return SimpleNamespace(
        run_id=uuid4(),
        task_id=uuid4(),
        actor=SimpleNamespace(user_id=uuid4(), is_admin=False, permissions=[], roles=[]),
        executor=executor,
        session=None,
    )


async def test_run_construction_review_aggregates() -> None:
    outputs = {
        "progress_analysis": {
            "project_id": "p1",
            "stages": [
                {
                    "stage": "泥瓦工程",
                    "planned_days": 10,
                    "actual_days": 13,
                    "status": "completed",
                    "deviation_days": 3,
                }
            ],
            "total_planned_days": 31,
            "total_actual_days": 20,
            "progress_ratio": 0.5,
            "delayed_stages": [{"stage": "泥瓦工程", "deviation_days": 3, "status": "completed"}],
            "at_risk": True,
        },
        "quality_check": {
            "project_id": "p1",
            "category": None,
            "items": [{"category": "防水", "item": "闭水试验", "weight": 3, "severity": "高"}],
            "total_weight": 3,
            "passed_weight": 3,
            "score": 1.0,
            "defects": [],
            "passed": True,
        },
    }
    executor = _FakeExecutor(outputs)
    artifact_type, payload = await run_construction_review(
        _ctx(executor), {"project_id": str(uuid4())}
    )

    assert artifact_type == "construction_review"
    assert payload["progress"]["progress_ratio"] == 0.5
    assert payload["progress"]["at_risk"] is True
    assert payload["quality"]["score"] == 1.0
    assert payload["suggestions"], "至少给出一条建议"
    assert payload["confidence"] == 0.82
    assert [call[0] for call in executor.calls] == ["progress_analysis", "quality_check"]


async def test_run_construction_review_requires_project_id() -> None:
    from dw_domain.errors import ToolValidationError

    executor = _FakeExecutor({})
    with pytest.raises(ToolValidationError, match="project_id"):
        await run_construction_review(_ctx(executor), {"objective": "施工"})
