"""Supervisor 契约 —— 需求文档 §4 / §7 / §32 / §5(Reviewer)。

只描述「意图、计划、复核结论、检查点」的形状，**不含编排逻辑**。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from dw_schemas.agent import RunMode


class IntentType(str, Enum):
    """§4 Intent Recognition 的输出。"""

    PROJECT_OVERVIEW = "project_overview"
    PROJECT_COMPARE = "project_compare"
    AFTERSALES_DIAGNOSIS = "aftersales_diagnosis"
    QUOTE_ESTIMATE = "quote_estimate"
    DESIGN_PROPOSAL = "design_proposal"
    CONSTRUCTION_REVIEW = "construction_review"
    # 调用方直接指定 agent/skill（不经意图路由）时的计划标记
    DIRECT_REQUEST = "direct_request"
    UNKNOWN = "unknown"


class IntentResult(BaseModel):
    intent: IntentType
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    matched_keywords: list[str] = Field(default_factory=list)
    mentioned_project_code: str | None = None


class PlanStep(BaseModel):
    """§8 任务契约的最小形态。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    task_key: str = Field(..., min_length=1, max_length=32)
    agent_id: str
    skill_id: str
    objective: str = Field(..., min_length=1, max_length=500)
    depends_on: list[str] = Field(default_factory=list)
    input: dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
    intent: IntentType
    mode: RunMode
    steps: list[PlanStep]
    # 计划来源说明（用户可见，便于解释「为什么这样做」）
    rationale: str = ""


class PlanRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    message: str = Field(..., min_length=1, max_length=500)
    project_id: UUID | None = None


class ReviewDecision(str, Enum):
    """§5 Reviewer 允许的决策。"""

    PASS = "PASS"
    RETRY = "RETRY"
    FALLBACK = "FALLBACK"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class ReviewResult(BaseModel):
    decision: ReviewDecision
    issues: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    consistency_issues: list[str] = Field(default_factory=list)
    recommended_action: str = ""


class CheckpointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    node: str
    version: int
    state: dict[str, Any]
    created_at: str | None = None


@dataclass(frozen=True, slots=True)
class PlannerLimits:
    """§32 明确要求的规划上限：不允许无限创建 Agent / 无限展开 DAG。"""

    max_steps: int = 8
    max_depth: int = 3
    max_parallel: int = 3
    deadline_ms: int = 30_000
    retry_limit: int = 1

    def describe(self) -> dict[str, int]:
        return {
            "max_steps": self.max_steps,
            "max_depth": self.max_depth,
            "max_parallel": self.max_parallel,
            "deadline_ms": self.deadline_ms,
            "retry_limit": self.retry_limit,
        }
