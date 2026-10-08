"""ORM 模型集合。Alembic 的 env.py 依赖本模块把所有表注册进 metadata。"""

from dw_domain.models.agent_runtime import (
    Agent,
    AgentRun,
    AgentTask,
    Approval,
    Artifact,
    AuditLog,
    Checkpoint,
    Skill,
    Tool,
    ToolCall,
)
from dw_domain.models.base import (
    Base,
    OptimisticLockMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    utc_now,
)
from dw_domain.models.iam import Permission, Role, User, role_permissions, user_roles
from dw_domain.models.project import Customer, House, Project, ProjectMember
from dw_domain.models.quote import QuoteItem, QuotePackage
from dw_domain.models.design import DesignStyle, LayoutModule
from dw_domain.models.construction import ConstructionMilestone, QualityChecklist

__all__ = [
    "Agent",
    "AgentRun",
    "AgentTask",
    "Approval",
    "Artifact",
    "AuditLog",
    "Base",
    "Checkpoint",
    "ConstructionMilestone",
    "Customer",
    "DesignStyle",
    "House",
    "LayoutModule",
    "QualityChecklist",
    "OptimisticLockMixin",
    "Permission",
    "Project",
    "QuoteItem",
    "QuotePackage",
    "ProjectMember",
    "Role",
    "Skill",
    "TimestampMixin",
    "Tool",
    "ToolCall",
    "UUIDPrimaryKeyMixin",
    "User",
    "role_permissions",
    "user_roles",
    "utc_now",
]
