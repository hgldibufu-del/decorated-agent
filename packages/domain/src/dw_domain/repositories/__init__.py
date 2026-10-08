"""仓储集合。"""

from dw_domain.repositories.base import SqlAlchemyRepository
from dw_domain.repositories.iam import RoleRepository, UserRepository
from dw_domain.repositories.projects import (
    CustomerRepository,
    HouseRepository,
    ProjectRepository,
)

__all__ = [
    "CustomerRepository",
    "HouseRepository",
    "ProjectRepository",
    "RoleRepository",
    "SqlAlchemyRepository",
    "UserRepository",
]
