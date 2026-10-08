"""dw-domain —— 领域层：业务规则、持久化模型、应用服务。"""

from dw_domain.access_control import (
    PROJECT_WRITE_ROLES,
    AccessSubject,
    can_manage_members,
    can_read_project,
    can_use_tool_scope,
    can_write_project,
    is_project_member,
)
from dw_domain.errors import (
    AuthenticationError,
    AuthorizationError,
    DomainError,
    DuplicateEntityError,
    EntityNotFoundError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidOperationError,
    PermissionDeniedError,
    StaleObjectError,
    TokenError,
    TokenExpiredError,
    TokenInvalidError,
)
from dw_domain.security import (
    ALGORITHM,
    PBKDF2_ITERATIONS,
    create_access_token,
    decode_access_token,
    hash_password,
    password_needs_upgrade,
    verify_password,
)
from dw_domain.services import AuthService, ProjectService

__version__ = "0.1.0"

__all__ = [
    "ALGORITHM",
    "PBKDF2_ITERATIONS",
    "PROJECT_WRITE_ROLES",
    "AccessSubject",
    "AuthService",
    "AuthenticationError",
    "AuthorizationError",
    "DomainError",
    "DuplicateEntityError",
    "EntityNotFoundError",
    "InactiveUserError",
    "InvalidCredentialsError",
    "InvalidOperationError",
    "PermissionDeniedError",
    "ProjectService",
    "StaleObjectError",
    "TokenError",
    "TokenExpiredError",
    "TokenInvalidError",
    "__version__",
    "can_manage_members",
    "can_read_project",
    "can_use_tool_scope",
    "can_write_project",
    "create_access_token",
    "decode_access_token",
    "hash_password",
    "is_project_member",
    "password_needs_upgrade",
    "verify_password",
]
