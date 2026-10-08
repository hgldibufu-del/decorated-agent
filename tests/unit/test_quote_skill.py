"""Quote 技能编排单测：用 FakeExecutor 验证 run_quote_estimate 的聚合与调用顺序。"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from dw_agent_runtime.skills import run_quote_estimate


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


async def test_run_quote_estimate_aggregates() -> None:
    outputs = {
        "budget_estimate": {
            "project_id": "p1",
            "area_sqm": "100.00",
            "layout": "三室两厅",
            "package": {
                "id": "pkg1",
                "name": "标准",
                "tier": "标准",
                "base_price": "28000.00",
                "price_per_sqm": "1280.00",
                "included_scope": None,
            },
            "line_items": [
                {"label": "面积计价", "amount": "128000.00", "detail": "100.00 m² × 1280.00 元/m²"}
            ],
            "total": "156000.00",
            "currency": "CNY",
            "assumptions": ["x"],
            "confidence": 0.85,
        },
        "package_compare": {
            "area_sqm": "100.00",
            "packages": [{"name": "标准", "total": "156000.00"}],
            "currency": "CNY",
        },
        "material_lookup": {"query": {}, "items": [{"name": "水电隐蔽工程", "unit_price": "28000.00"}]},
    }
    executor = _FakeExecutor(outputs)
    artifact_type, payload = await run_quote_estimate(
        _ctx(executor), {"project_id": str(uuid4()), "objective": "报价"}
    )

    assert artifact_type == "quote_estimate"
    assert payload["estimate"]["total"] == "156000.00"
    assert payload["recommended_package"]["name"] == "标准"
    assert payload["comparison"]
    assert payload["materials"]
    assert payload["assumptions"] == ["x"]
    assert [call[0] for call in executor.calls] == [
        "budget_estimate",
        "package_compare",
        "material_lookup",
    ]


async def test_run_quote_estimate_requires_project_id() -> None:
    from dw_domain.errors import ToolValidationError

    executor = _FakeExecutor({})
    with pytest.raises(ToolValidationError, match="project_id"):
        await run_quote_estimate(_ctx(executor), {"objective": "报价"})
