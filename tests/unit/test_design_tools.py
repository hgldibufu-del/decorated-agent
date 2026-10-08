"""Design 工具纯逻辑单测（不依赖 DB）：房间推导 / 模块筛选 / 风格排序 / 技能编排。"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from dw_agent_runtime.design_tools import (
    _derive_room_types,
    _rank_styles,
    _select_modules,
)
from dw_agent_runtime.skills import run_design_proposal


def _style(name: str, tags: list[str], family: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4().hex,
        name=name,
        style_family=family or name,
        description="",
        suitable_layouts=[],
        palette=[],
        characteristics={},
        tags=tags,
    )


def test_derive_room_types_parses_layout():
    types = _derive_room_types("三室两厅")
    assert "卧室" in types
    assert "客厅" in types and "餐厅" in types
    # 厨卫阳是住宅标配，始终纳入
    assert {"厨房", "卫生间", "阳台"}.issubset(set(types))


def test_derive_room_types_none_returns_baseline():
    assert set(_derive_room_types(None)) == {"厨房", "卫生间", "阳台"}


def test_select_modules_filters_by_derived_type():
    modules = [
        SimpleNamespace(room_type="卧室"),
        SimpleNamespace(room_type="客厅"),
        SimpleNamespace(room_type="厨房"),
        SimpleNamespace(room_type="阳台"),
    ]
    selected = _select_modules(modules, "两室一厅")
    room_types = {m.room_type for m in selected}
    assert {"卧室", "客厅", "厨房", "阳台"}.issubset(room_types)


def test_select_modules_falls_back_to_all_when_empty():
    modules = [SimpleNamespace(room_type="卧室"), SimpleNamespace(room_type="厨房")]
    assert len(_select_modules(modules, "???")) == 2


def test_rank_styles_scores_by_preference():
    styles = [_style("现代简约", ["现代", "简约"]), _style("新中式", ["传统"])]
    ranked = _rank_styles("现代", styles)
    assert ranked[0]["name"] == "现代简约"
    assert ranked[0]["score"] > ranked[1]["score"]


def test_rank_styles_no_preference_keeps_order_and_zero_score():
    styles = [_style("A", []), _style("B", [])]
    ranked = _rank_styles("", styles)
    assert [s["name"] for s in ranked] == ["A", "B"]
    assert all(s["score"] == 0 for s in ranked)


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


async def test_run_design_proposal_aggregates() -> None:
    outputs = {
        "layout_analysis": {
            "project_id": "p1",
            "layout": "三室两厅",
            "area_sqm": "100.00",
            "space_suggestions": [
                {
                    "room_type": "卧室",
                    "suggested_function": "休息",
                    "design_principle": "静谧",
                    "recommended_material_category": "主材",
                    "notes": "",
                },
                {
                    "room_type": "厨房",
                    "suggested_function": "烹饪",
                    "design_principle": "易清洁",
                    "recommended_material_category": "硬装",
                    "notes": "",
                },
            ],
        },
        "style_match": {
            "preference": "现代",
            "constraints": "",
            "styles": [
                {
                    "id": "1",
                    "name": "现代简约",
                    "style_family": "现代简约",
                    "description": "",
                    "suitable_layouts": ["三室两厅"],
                    "palette": ["#FFFFFF", "#222222"],
                    "characteristics": {},
                    "tags": ["现代"],
                    "score": 2,
                }
            ],
        },
    }
    executor = _FakeExecutor(outputs)
    artifact_type, payload = await run_design_proposal(
        _ctx(executor), {"project_id": str(uuid4()), "preference": "现代"}
    )

    assert artifact_type == "design_proposal"
    assert payload["layout"] == "三室两厅"
    assert payload["area_sqm"] == "100.00"
    assert len(payload["space_planning"]) == 2
    assert payload["recommended_styles"][0]["name"] == "现代简约"
    assert payload["recommended_palette"] == ["#FFFFFF", "#222222"]
    assert payload["suggested_material_categories"] == ["主材", "硬装"]
    assert payload["confidence"] == 0.8
    assert [call[0] for call in executor.calls] == ["layout_analysis", "style_match"]


async def test_run_design_proposal_requires_project_id() -> None:
    from dw_domain.errors import ToolValidationError

    executor = _FakeExecutor({})
    with pytest.raises(ToolValidationError, match="project_id"):
        await run_design_proposal(_ctx(executor), {"objective": "设计"})
