"""项目应用服务 —— 需求文档 §9 / §13 / §22。

这里是「项目」聚合的事务边界与业务规则所在：
* 建档自动把创建者置为 owner（否则会创建出无人可管的孤儿项目）；
* 列表按 Project ACL 收敛到可见集；
* 访达判定统一委托 `access_control`（纯函数），不在 SQL 里散落权限逻辑。

关于 403 vs 404 的口径：**明确返回 403**。
项目 ID 是不可猜测的 UUID，返回 403 不会泄露额外信息，却能让前端明确提示
「无权限」而不是「不存在」——后者在装修场景会让设计师反复以为数据丢了。
"""

from __future__ import annotations

from uuid import UUID

from dw_schemas.iam import PermissionCode, ProjectRole, UserBrief, UserIdentity
from dw_schemas.project import (
    CustomerCreate,
    CustomerOut,
    CustomerUpdate,
    HouseCreate,
    HouseOut,
    HouseUpdate,
    ProjectCreate,
    ProjectDetail,
    ProjectMemberAdd,
    ProjectMemberOut,
    ProjectSummary,
    ProjectUpdate,
)
from sqlalchemy.ext.asyncio import AsyncSession

from dw_domain.access_control import (
    AccessSubject,
    can_manage_members,
    can_read_project,
    can_write_project,
)
from dw_domain.errors import (
    EntityNotFoundError,
    InvalidOperationError,
    PermissionDeniedError,
)
from dw_domain.models.project import Project
from dw_domain.repositories.iam import UserRepository
from dw_domain.repositories.projects import (
    CustomerRepository,
    HouseRepository,
    ProjectRepository,
)


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectRepository(session)
        self._customers = CustomerRepository(session)
        self._houses = HouseRepository(session)
        self._users = UserRepository(session)

    # ------------------------------------------------------------------ 查询
    async def list_projects(self, actor: UserIdentity) -> list[ProjectSummary]:
        rows = await self._projects.list_for_user(actor.user_id, is_admin=actor.is_admin)
        return [_to_summary(project, role) for project, role in rows]

    async def get_project(self, project_id: UUID, actor: UserIdentity) -> ProjectDetail:
        project, membership_role = await self._require_readable(project_id, actor)
        return await self._to_detail(project, membership_role)

    async def list_members(self, project_id: UUID, actor: UserIdentity) -> list[ProjectMemberOut]:
        project, _ = await self._require_readable(project_id, actor)
        return await self._member_outs(project.id)

    # ------------------------------------------------------------------ 写入
    async def create_project(self, payload: ProjectCreate, actor: UserIdentity) -> ProjectDetail:
        subject = self._subject(actor, membership_role=None)
        if not (subject.is_admin or subject.has(PermissionCode.PROJECT_WRITE)):
            raise PermissionDeniedError("缺少 project:write 权限")

        customer = await self._customers.get(payload.customer_id)
        if customer is None:
            raise EntityNotFoundError(f"客户不存在: {payload.customer_id}")

        house = await self._houses.get(payload.house_id)
        if house is None:
            raise EntityNotFoundError(f"房屋不存在: {payload.house_id}")
        if str(house.customer_id) != str(payload.customer_id):
            raise InvalidOperationError("房屋不属于该客户，无法作为项目标的")

        project = await self._projects.create(
            code=payload.code,
            name=payload.name,
            customer_id=payload.customer_id,
            house_id=payload.house_id,
            status=payload.status,
            budget_amount=payload.budget_amount,
            planned_start_date=payload.planned_start_date,
            planned_complete_date=payload.planned_complete_date,
            note=payload.note,
        )
        # 创建者默认 owner：保证每个项目至少有一个可管理的责任人
        await self._projects.add_member(
            project_id=project.id, user_id=actor.user_id, role=ProjectRole.OWNER
        )
        # 重新按 eager-load 取一次：新建对象的关系属性尚未加载，
        # 在 async 会话里直接访问会触发 lazy load 并抛 MissingGreenlet。
        reloaded = await self._projects.get(project.id)
        if reloaded is None:  # pragma: no cover - 刚写入必然存在，防御性分支
            raise EntityNotFoundError(f"项目不存在: {project.id}")
        return await self._to_detail(reloaded, ProjectRole.OWNER)

    async def add_member(
        self, project_id: UUID, payload: ProjectMemberAdd, actor: UserIdentity
    ) -> list[ProjectMemberOut]:
        project, membership_role = await self._projects.find_access(project_id, actor.user_id)
        if project is None:
            raise EntityNotFoundError(f"项目不存在: {project_id}")

        subject = self._subject(actor, membership_role)
        if not can_manage_members(subject):
            raise PermissionDeniedError("无权管理该项目成员")

        target = await self._users.get_by_id(payload.user_id)
        if target is None:
            raise EntityNotFoundError(f"用户不存在: {payload.user_id}")

        existing = await self._projects.get_member(project.id, payload.user_id)
        if existing is not None:
            existing.role = payload.role.value
            await self._session.flush()
        else:
            await self._projects.add_member(
                project_id=project.id, user_id=payload.user_id, role=payload.role
            )
        return await self._member_outs(project.id)

    async def update_project(
        self, project_id: UUID, payload: ProjectUpdate, actor: UserIdentity
    ) -> ProjectDetail:
        """部分更新项目；`version` 不匹配即乐观锁冲突（→ 409）。"""
        project, membership_role = await self._projects.find_access(project_id, actor.user_id)
        if project is None:
            raise EntityNotFoundError(f"项目不存在: {project_id}")
        if not can_write_project(self._subject(actor, membership_role)):
            raise PermissionDeniedError("无权修改该项目")

        changes = payload.model_dump(exclude_unset=True)
        changes.pop("version", None)
        if "status" in changes:
            if changes["status"] is None:
                # status 非空，显式传 null 视作「未修改」，避免写入非法值
                changes.pop("status")
            else:
                changes["status"] = changes["status"].value
        for field, value in changes.items():
            setattr(project, field, value)

        await self._projects.save(project, expected_version=payload.version)
        return await self._to_detail(project, membership_role)

    async def delete_project(self, project_id: UUID, actor: UserIdentity) -> None:
        project, membership_role = await self._projects.find_access(project_id, actor.user_id)
        if project is None:
            raise EntityNotFoundError(f"项目不存在: {project_id}")
        if not can_write_project(self._subject(actor, membership_role)):
            raise PermissionDeniedError("无权删除该项目")
        await self._projects.delete_guarded(
            project, entity="项目", referenced_by="已有 Agent Run / 施工记录"
        )

    # ------------------------------------------------------------------ 参考数据
    async def list_customers(self, actor: UserIdentity) -> list[CustomerOut]:
        self._require_write(actor)
        rows = await self._customers.list_all()
        return [CustomerOut.model_validate(row) for row in rows]

    async def create_customer(self, payload: CustomerCreate, actor: UserIdentity) -> CustomerOut:
        self._require_write(actor)
        customer = await self._customers.create(
            name=payload.name, phone=payload.phone, email=payload.email, note=payload.note
        )
        return CustomerOut.model_validate(customer)

    async def list_houses(
        self, actor: UserIdentity, *, customer_id: UUID | None = None
    ) -> list[HouseOut]:
        self._require_write(actor)
        rows = await self._houses.list_all(customer_id=customer_id)
        return [HouseOut.model_validate(row) for row in rows]

    async def create_house(self, payload: HouseCreate, actor: UserIdentity) -> HouseOut:
        self._require_write(actor)
        customer = await self._customers.get(payload.customer_id)
        if customer is None:
            raise EntityNotFoundError(f"客户不存在: {payload.customer_id}")
        house = await self._houses.create(
            customer_id=payload.customer_id,
            address=payload.address,
            city=payload.city,
            area_sqm=payload.area_sqm,
            layout=payload.layout,
            note=payload.note,
        )
        return HouseOut.model_validate(house)

    async def list_users(self, actor: UserIdentity) -> list[UserBrief]:
        """成员候选：只回 id / email / full_name（不含角色，避免越权线索）。"""
        self._require_write(actor)
        rows = await self._users.list_all()
        return [UserBrief.model_validate(row) for row in rows]

    async def update_customer(
        self, customer_id: UUID, payload: CustomerUpdate, actor: UserIdentity
    ) -> CustomerOut:
        self._require_write(actor)
        customer = await self._customers.get(customer_id)
        if customer is None:
            raise EntityNotFoundError(f"客户不存在: {customer_id}")
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(customer, field, value)
        await self._customers.save(customer)
        return CustomerOut.model_validate(customer)

    async def delete_customer(self, customer_id: UUID, actor: UserIdentity) -> None:
        self._require_write(actor)
        customer = await self._customers.get(customer_id)
        if customer is None:
            raise EntityNotFoundError(f"客户不存在: {customer_id}")
        await self._customers.delete_guarded(customer, entity="客户", referenced_by="名下房屋")

    async def update_house(
        self, house_id: UUID, payload: HouseUpdate, actor: UserIdentity
    ) -> HouseOut:
        self._require_write(actor)
        house = await self._houses.get(house_id)
        if house is None:
            raise EntityNotFoundError(f"房屋不存在: {house_id}")
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(house, field, value)
        await self._houses.save(house)
        return HouseOut.model_validate(house)

    async def delete_house(self, house_id: UUID, actor: UserIdentity) -> None:
        self._require_write(actor)
        house = await self._houses.get(house_id)
        if house is None:
            raise EntityNotFoundError(f"房屋不存在: {house_id}")
        await self._houses.delete_guarded(house, entity="房屋", referenced_by="关联项目")

    def _require_write(self, actor: UserIdentity) -> None:
        subject = self._subject(actor, membership_role=None)
        if not (subject.is_admin or subject.has(PermissionCode.PROJECT_WRITE)):
            raise PermissionDeniedError("缺少 project:write 权限")

    # ------------------------------------------------------------------ 内部
    async def _require_readable(
        self, project_id: UUID, actor: UserIdentity
    ) -> tuple[Project, ProjectRole | None]:
        project, membership_role = await self._projects.find_access(project_id, actor.user_id)
        if project is None:
            raise EntityNotFoundError(f"项目不存在: {project_id}")
        if not can_read_project(self._subject(actor, membership_role)):
            raise PermissionDeniedError("无权访问该项目")
        return project, membership_role

    def _subject(self, actor: UserIdentity, membership_role: ProjectRole | None) -> AccessSubject:
        return AccessSubject.from_iterable(
            is_admin=actor.is_admin,
            membership_role=membership_role,
            permissions=[permission.value for permission in actor.permissions],
        )

    async def _member_outs(self, project_id: UUID) -> list[ProjectMemberOut]:
        members = await self._projects.list_members(project_id)
        return [
            ProjectMemberOut(
                project_id=member.project_id,
                user_id=member.user_id,
                role=member.role_enum,
                email=member.user.email,
                full_name=member.user.full_name,
                joined_at=member.joined_at,
            )
            for member in members
        ]

    async def _to_detail(
        self, project: Project, membership_role: ProjectRole | None
    ) -> ProjectDetail:
        members = await self._member_outs(project.id)
        return ProjectDetail(
            id=project.id,
            code=project.code,
            name=project.name,
            status=project.status_enum,
            customer_id=project.customer_id,
            house_id=project.house_id,
            budget_amount=project.budget_amount,
            planned_start_date=project.planned_start_date,
            planned_complete_date=project.planned_complete_date,
            note=project.note,
            created_at=project.created_at,
            updated_at=project.updated_at,
            version=project.version,
            customer=CustomerOut.model_validate(project.customer),
            house=HouseOut.model_validate(project.house),
            members=members,
        )


def _to_summary(project: Project, membership_role: ProjectRole | None) -> ProjectSummary:
    return ProjectSummary(
        id=project.id,
        code=project.code,
        name=project.name,
        status=project.status_enum,
        customer_name=project.customer.name,
        house_address=project.house.address,
        member_role=membership_role,
        created_at=project.created_at,
    )
