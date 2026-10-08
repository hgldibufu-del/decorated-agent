"""应用服务集合。"""

from dw_domain.services.auth_service import AuthService
from dw_domain.services.project_service import ProjectService

__all__ = ["AuthService", "ProjectService"]
