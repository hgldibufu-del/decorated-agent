"""AfterSales 技能执行体单测 —— Phase 4（不依赖数据库）。

用 FakeExecutor 拦截三个 RAG 工具调用，验证 `run_aftersales_diagnosis` 的编排逻辑：
是否按 issue 调对了工具、是否把证据/根因/相似案例收敛成带引用的 Artifact。
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest
from dw_agent_runtime.executor import ToolResult
from dw_agent_runtime.skills import run_aftersales_diagnosis
from dw_schemas.iam import RoleName, UserIdentity


@dataclass
class FakeExecutor:
    outputs: dict
    calls: list[tuple[str, dict]]

    async def call(self, tool_id: str, payload: dict, **_: object) -> ToolResult:
        self.calls.append((tool_id, payload))
        return ToolResult(
            tool_id=tool_id, output=self.outputs[tool_id], attempt=1, duration_ms=1
        )


def _admin_identity() -> UserIdentity:
    return UserIdentity(
        user_id=uuid4(),
        email="admin@dw.local",
        full_name="admin",
        roles=[RoleName.ADMIN],
        permissions=[],
    )


def _ctx(executor: FakeExecutor):
    return type("_Ctx", (), {  # 轻量 SkillContext 替身
        "run_id": uuid4(),
        "task_id": uuid4(),
        "actor": _admin_identity(),
        "executor": executor,
        "session": None,
    })()


EXPECTED_OUTPUTS = {
    "case_search": {
        "query": "卫生间渗水",
        "strategy": "hybrid(vector+bm25+rrf)",
        "chunks": [{"id": str(uuid4()), "content": "防水施工规范", "source": "kb", "score": 0.9}],
    },
    "root_cause": {
        "issue": "卫生间渗水",
        "hypothesis": "防水/管道渗漏",
        "suggested_actions": ["排查防水层"],
        "confidence": 0.7,
        "evidence": [],
    },
    "case_match": {
        "issue": "卫生间渗水",
        "cases": [{"chunk_id": str(uuid4()), "source": "case-1", "similarity": 0.88}],
    },
}


async def test_aftersales_diagnosis_orchestrates_tools() -> None:
    executor = FakeExecutor(outputs=EXPECTED_OUTPUTS, calls=[])
    ctx = _ctx(executor)

    artifact_type, payload = await run_aftersales_diagnosis(ctx, {"issue": "卫生间渗水"})

    assert artifact_type == "aftersales_diagnosis"
    # 应依次调用三个工具，且都带上了 issue/query
    called = {tool_id for tool_id, _ in executor.calls}
    assert called == {"case_search", "root_cause", "case_match"}
    # 根因来自 RAG 证据 + 规则
    assert payload["hypothesis"] == "防水/管道渗漏"
    # 证据与相似案例原样收敛进 Artifact
    assert payload["evidence"] == EXPECTED_OUTPUTS["case_search"]["chunks"]
    assert payload["similar_cases"] == EXPECTED_OUTPUTS["case_match"]["cases"]


async def test_aftersales_diagnosis_rejects_missing_issue() -> None:
    from dw_domain.errors import ToolValidationError

    executor = FakeExecutor(outputs={}, calls=[])
    ctx = _ctx(executor)

    with pytest.raises(ToolValidationError):
        await run_aftersales_diagnosis(ctx, {})
