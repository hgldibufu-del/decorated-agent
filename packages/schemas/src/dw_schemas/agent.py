"""Agent 基础设施契约 —— 需求文档 §5 / §6 / §8 / §12 / §34。

说明：这里定义「注册中心里存什么、Run/Task/Artifact 长什么样」，
**不定义执行逻辑**（在 `dw_agent_runtime`）。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AgentType(str, Enum):
    SUPERVISOR = "supervisor"
    DESIGN = "design"
    QUOTE = "quote"
    CONSTRUCTION = "construction"
    AFTERSALES = "aftersales"
    REVIEWER = "reviewer"


class RunMode(str, Enum):
    DIRECT = "direct"
    SEQUENTIAL = "sequential"
    PARALLEL_DAG = "parallel_dag"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


class ToolCallStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    DENIED = "denied"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RiskLevel(str, Enum):
    """工具/技能风险等级。L2 及以上触发人工审批（§15）。"""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


_RISK_ORDER = [RiskLevel.L0, RiskLevel.L1, RiskLevel.L2, RiskLevel.L3]


def risk_rank(level: RiskLevel) -> int:
    return _RISK_ORDER.index(level)


def risk_at_least(level: RiskLevel, threshold: RiskLevel) -> bool:
    """L2 及以上需要人工审批，用等级序比较而不是字符串比较。"""
    return risk_rank(level) >= risk_rank(threshold)


APPROVAL_THRESHOLD = RiskLevel.L2


# -----------------------------------------------------------------------------
# 注册中心对外视图
# -----------------------------------------------------------------------------
class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agent_id: str
    agent_type: AgentType
    description: str
    version: str
    supported_skills: list[str] = Field(default_factory=list)
    required_scopes: list[str] = Field(default_factory=list)
    enabled: bool


class SkillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    skill_id: str
    agent_type: AgentType
    version: str
    required_scopes: list[str] = Field(default_factory=list)
    risk_level: RiskLevel
    allowed_tools: list[str] = Field(default_factory=list)
    enabled: bool


class ToolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tool_id: str
    description: str
    required_scopes: list[str] = Field(default_factory=list)
    risk_level: RiskLevel
    timeout_ms: int
    retry_max_attempts: int
    fallback_tool_id: str | None
    idempotency_required: bool
    audit_required: bool
    enabled: bool


# -----------------------------------------------------------------------------
# Run / Task / Artifact / Approval
# -----------------------------------------------------------------------------
class RunCreateRequest(BaseModel):
    """发起 Run。两种用法二选一：

    1. 直接指定 `agent_id` + `skill_id`（Phase 2 起，单任务 Direct）；
    2. 只给 `intent`（Phase 3 起），由 Supervisor 规划出 DAG 再执行。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    # 用法 1
    agent_id: str | None = None
    skill_id: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    # 用法 2（用 str 而非 IntentType：避免与 dw_schemas.supervisor 形成循环导入，
    # 取值合法性由接入层 IntentType(...) 校验）
    intent: str | None = None
    objective: str = Field(..., min_length=1, max_length=500)
    project_id: UUID | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_key: str
    agent_id: str
    skill_id: str
    status: TaskStatus
    attempt: int
    risk_level: RiskLevel
    allowed_tools: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    artifact_id: UUID | None
    error: str | None


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None
    status: RunStatus
    mode: RunMode
    objective: str
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    tasks: list[TaskOut] = Field(default_factory=list)
    artifact_ids: list[UUID] = Field(default_factory=list)
    # 高风险技能触发人工审批时给出审批单 ID，前端据此跳转 / 轮询
    approval_id: UUID | None = None
    # Reviewer 结论（§5）：PASS / RETRY / FALLBACK / HUMAN_REVIEW
    review_decision: str | None = None
    review_issues: list[str] = Field(default_factory=list)


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    artifact_type: str
    producer: str
    payload: dict[str, Any]
    version: int
    created_at: datetime


class ToolCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tool_id: str
    status: ToolCallStatus
    attempt: int
    duration_ms: int
    error: str | None
    created_at: datetime


class RunEvent(BaseModel):
    """一次 Run 的执行时间线（供 Workbench 展示，见 §19）。"""

    kind: str
    at: datetime
    summary: str
    status: str
    detail: dict[str, Any] = Field(default_factory=dict)


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    task_id: UUID | None
    status: ApprovalStatus
    reason: str
    created_at: datetime
    decided_at: datetime | None


class ApprovalDecision(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject)$")
    comment: str | None = Field(default=None, max_length=1000)
