"""项目域仓储。

`list_for_user` / `find_access` 是 Project ACL 的取数点：
把「项目 + 当前用户在该项目的成员角色」一次性取出来，
避免业务层先查项目再查成员导致的两次往返与竞态。
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from dw_schemas.iam import ProjectRole
from dw_schemas.project import ProjectStatus
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from dw_domain.errors import StaleObjectError
from dw_domain.models.project import Customer, House, Project, ProjectMember
from dw_domain.repositories.base import SqlAlchemyRepository

ProjectWithRole = tuple[Project, ProjectRole | None]


def _role_or_none(role_value: str | None) -> ProjectRole | None:
    return ProjectRole(role_value) if role_value else None


class CustomerRepository(SqlAlchemyRepository):
    async def get(self, customer_id: UUID) -> Customer | None:
        result = await self._session.execute(select(Customer).where(Customer.id == customer_id))
        return result.unique().scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> Customer | None:
        result = await self._session.execute(select(Customer).where(Customer.phone == phone))
        return result.unique().scalar_one_or_none()

    async def create(
        self,
        *,
        name: str,
        phone: str,
        email: str | None = None,
        note: str | None = None,
    ) -> Customer:
        customer = Customer(name=name, phone=phone, email=email, note=note)
        self._session.add(customer)
        await self.flush_or_raise_duplicate(field="phone", value=phone)
        return customer

    async def list_all(self, limit: int = 200) -> list[Customer]:
        result = await self._session.execute(
            select(Customer).order_by(Customer.created_at.desc()).limit(limit)
        )
        return list(result.unique().scalars().all())

    async def save(self, customer: Customer) -> Customer:
        """保存客户改动；手机号唯一冲突转成 `DuplicateEntityError`（→ 409）。"""
        await self.flush_or_raise_duplicate(field="phone", value=customer.phone)
        return customer


class HouseRepository(SqlAlchemyRepository):
    async def get(self, house_id: UUID) -> House | None:
        result = await self._session.execute(select(House).where(House.id == house_id))
        return result.unique().scalar_one_or_none()

    async def get_by_address(self, address: str) -> House | None:
        result = await self._session.execute(select(House).where(House.address == address))
        return result.unique().scalar_one_or_none()

    async def create(
        self,
        *,
        customer_id: UUID,
        address: str,
        city: str | None = None,
        area_sqm: Decimal | None = None,
        layout: str | None = None,
        note: str | None = None,
    ) -> House:
        house = House(
            customer_id=customer_id,
            address=address,
            city=city,
            area_sqm=area_sqm,
            layout=layout,
            note=note,
        )
        self._session.add(house)
        await self._session.flush()
        return house

    async def list_all(
        self, *, customer_id: UUID | None = None, limit: int = 200
    ) -> list[House]:
        stmt = select(House).order_by(House.created_at.desc()).limit(limit)
        if customer_id is not None:
            stmt = stmt.where(House.customer_id == customer_id)
        return list((await self._session.execute(stmt)).unique().scalars().all())

    async def save(self, house: House) -> House:
        await self._session.flush()
        return house


class ProjectRepository(SqlAlchemyRepository):
    def __init__(self, session: AsyncSession, default_limit: int = 50) -> None:
        super().__init__(session)
        self._default_limit = default_limit

    # ------------------------------------------------------------------ 读
    async def get(self, project_id: UUID) -> Project | None:
        result = await self._session.execute(select(Project).where(Project.id == project_id))
        return result.unique().scalar_one_or_none()

    async def get_by_code(self, code: str) -> Project | None:
        result = await self._session.execute(select(Project).where(Project.code == code))
        return result.unique().scalar_one_or_none()

    async def find_access(self, project_id: UUID, user_id: UUID) -> ProjectWithRole:
        """返回 (项目, 当前用户成员角色)。非成员时角色为 None。"""
        stmt = (
            select(Project, ProjectMember.role)
            .outerjoin(
                ProjectMember,
                and_(
                    ProjectMember.project_id == Project.id,
                    ProjectMember.user_id == user_id,
                ),
            )
            .where(Project.id == project_id)
        )
        row = (await self._session.execute(stmt)).unique().first()
        if row is None:
            return (None, None)  # type: ignore[return-value]
        project, role_value = row
        return project, _role_or_none(role_value)

    async def list_for_user(
        self, user_id: UUID, *, is_admin: bool, limit: int | None = None
    ) -> list[ProjectWithRole]:
        stmt = (
            select(Project, ProjectMember.role)
            .outerjoin(
                ProjectMember,
                and_(
                    ProjectMember.project_id == Project.id,
                    ProjectMember.user_id == user_id,
                ),
            )
            .order_by(Project.created_at.desc())
            .limit(limit or self._default_limit)
        )
        if not is_admin:
            # 只保留存在成员关系的行（outerjoin + 非空过滤 = 成员可见集）
            stmt = stmt.where(ProjectMember.user_id == user_id)

        rows = (await self._session.execute(stmt)).unique().all()
        return [(row[0], _role_or_none(row[1])) for row in rows]

    async def get_member(self, project_id: UUID, user_id: UUID) -> ProjectMember | None:
        result = await self._session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        return result.unique().scalar_one_or_none()

    async def list_members(self, project_id: UUID) -> list[ProjectMember]:
        result = await self._session.execute(
            select(ProjectMember)
            .where(ProjectMember.project_id == project_id)
            .order_by(ProjectMember.joined_at)
        )
        return list(result.unique().scalars().all())

    # ------------------------------------------------------------------ 写
    async def create(
        self,
        *,
        code: str,
        name: str,
        customer_id: UUID,
        house_id: UUID,
        status: ProjectStatus = ProjectStatus.DRAFT,
        budget_amount: Decimal | None = None,
        planned_start_date=None,
        planned_complete_date=None,
        note: str | None = None,
    ) -> Project:
        project = Project(
            code=code,
            name=name,
            status=status.value,
            customer_id=customer_id,
            house_id=house_id,
            budget_amount=budget_amount,
            planned_start_date=planned_start_date,
            planned_complete_date=planned_complete_date,
            note=note,
        )
        self._session.add(project)
        await self.flush_or_raise_duplicate(field="code", value=code)
        return project

    async def add_member(
        self, *, project_id: UUID, user_id: UUID, role: ProjectRole
    ) -> ProjectMember:
        member = ProjectMember(project_id=project_id, user_id=user_id, role=role.value)
        self._session.add(member)
        await self.flush_or_raise_duplicate(field="membership", value=f"{project_id}:{user_id}")
        return member

    async def save(self, project: Project, *, expected_version: int) -> Project:
        """乐观锁保存：客户端持有的 version 与库中不一致 → `StaleObjectError`（→ 409）。"""
        if project.version != expected_version:
            raise StaleObjectError("Project", expected_version, project.version)
        project.version += 1
        await self._session.flush()
        return project
