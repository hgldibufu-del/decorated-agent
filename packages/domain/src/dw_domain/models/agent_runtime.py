"""Agent 基础设施表 —— 需求文档 §6 / §8 / §14 / §22 / §34。

表：
    agents / skills / tools            注册中心（§6 metadata）
    agent_runs / agent_tasks           Run 与 Task（§8 任务契约）
    artifacts                          跨 Agent 传递的结构化结果（§34）
    tool_calls / approvals / audit_logs 工具治理与审批留痕（§12 / §15）

外键策略：
* `agent_tasks` → `agent_runs` 用 CASCADE（Task 依附 Run）；
* `agent_runs.project_id` / requester 用 RESTRICT（业务事实不被 Agent 日志连坐删除）；
* `approvals.decided_by` 用 SET NULL（审批人账号被删不应删掉审批记录）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from dw_schemas.agent import (
    AgentType,
    ApprovalStatus,
    RiskLevel,
    RunMode,
    RunStatus,
    TaskStatus,
    ToolCallStatus,
)
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dw_domain.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utc_now
from dw_domain.models.iam import User
from dw_domain.models.project import Project


class Agent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    agent_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="0.1.0")
    supported_skills: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    input_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    required_scopes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    @property
    def agent_type_enum(self) -> AgentType:
        return AgentType(self.agent_type)


class Skill(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "skills"

    skill_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    agent_type: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="0.1.0")
    input_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    required_scopes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    risk_level: Mapped[str] = mapped_column(String(8), nullable=False, default=RiskLevel.L0.value)
    allowed_tools: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    @property
    def agent_type_enum(self) -> AgentType:
        return AgentType(self.agent_type)

    @property
    def risk_enum(self) -> RiskLevel:
        return RiskLevel(self.risk_level)


class Tool(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tools"

    tool_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    input_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    required_scopes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    risk_level: Mapped[str] = mapped_column(String(8), nullable=False, default=RiskLevel.L1.value)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    retry_max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    retry_backoff_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    fallback_tool_id: Mapped[str | None] = mapped_column(String(64))
    idempotency_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    audit_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    @property
    def risk_enum(self) -> RiskLevel:
        return RiskLevel(self.risk_level)


class AgentRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agent_runs"

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    requester_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=RunStatus.PENDING.value)
    mode: Mapped[str] = mapped_column(String(24), nullable=False, default=RunMode.DIRECT.value)
    objective: Mapped[str] = mapped_column(String(500), nullable=False)
    error: Mapped[str | None] = mapped_column(String(2000))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # §7 执行计划（Phase 3）：落库后才能从检查点恢复，不能只存在内存里
    plan: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    review_decision: Mapped[str | None] = mapped_column(String(16))
    review_issues: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    tasks: Mapped[list[AgentTask]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def status_enum(self) -> RunStatus:
        return RunStatus(self.status)


class AgentTask(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agent_tasks"
    __table_args__ = (
        UniqueConstraint("run_id", "task_key", name="uq_agent_tasks_run_id_task_key"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    task_key: Mapped[str] = mapped_column(String(32), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    skill_id: Mapped[str] = mapped_column(String(64), nullable=False)
    objective: Mapped[str] = mapped_column(String(500), nullable=False)
    input_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    allowed_tools: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    risk_level: Mapped[str] = mapped_column(String(8), nullable=False, default=RiskLevel.L1.value)
    success_conditions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    deadline_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=30000)
    depends_on: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=TaskStatus.PENDING.value
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retry: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL")
    )
    error: Mapped[str | None] = mapped_column(String(2000))

    run: Mapped[AgentRun] = relationship(back_populates="tasks")

    @property
    def status_enum(self) -> TaskStatus:
        return TaskStatus(self.status)


class Artifact(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "artifacts"
    __table_args__ = (
        # 版本按「任务」独立递增：并行 DAG 中同一技能（相同 artifact_type）的多个任务
        # 各自产出自己的 Artifact，不能因为共享 run_id + artifact_type 而撞唯一键。
        UniqueConstraint(
            "run_id", "task_id", "version", name="uq_artifacts_run_id_task_id_version"
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_tasks.id", ondelete="SET NULL")
    )
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    producer: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ToolCall(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tool_calls"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_tasks.id", ondelete="SET NULL")
    )
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # 幂等键：相同 key + 已完成 → 直接回放上次结果（§12 idempotency check）
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    input_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ToolCallStatus.SUCCESS.value
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(2000))

    @property
    def status_enum(self) -> ToolCallStatus:
        return ToolCallStatus(self.status)


class Approval(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "approvals"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_tasks.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ApprovalStatus.PENDING.value
    )
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(String(1000))

    @property
    def status_enum(self) -> ApprovalStatus:
        return ApprovalStatus(self.status)


class Checkpoint(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """§9 节点级恢复：每个任务完成后写一条，恢复时从最后一个完成的节点继续。

    (run_id, node, version) 唯一：同一节点重试会留下新版本，便于追溯
    「这次结果是从哪一次尝试来的」。
    """

    __tablename__ = "checkpoints"
    __table_args__ = (
        UniqueConstraint("run_id", "node", "version", name="uq_checkpoints_run_id_node_version"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    node: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class AuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """§12 审计留痕：谁在什么时候对什么资源做了什么。"""

    __tablename__ = "audit_logs"

    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


# 便于显式引用（关系定义用到了字符串形式，这里保证模块被导入时类已定义）
__all__ = [
    "Agent",
    "AgentRun",
    "AgentTask",
    "Approval",
    "Artifact",
    "AuditLog",
    "Checkpoint",
    "Project",
    "Skill",
    "Tool",
    "ToolCall",
    "User",
]
