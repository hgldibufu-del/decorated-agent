"""身份仓储：用户、角色、权限。

`ensure_*` 系列是幂等的（存在则返回、不存在则创建），
这样 seed 脚本和测试夹具可以放心重复执行。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import insert, select

from dw_domain.models.iam import (
    Permission,
    Role,
    User,
    role_permissions,
    user_roles,
)
from dw_domain.repositories.base import SqlAlchemyRepository


class UserRepository(SqlAlchemyRepository):
    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.unique().scalar_one_or_none()

    async def get_by_id(self, user_id: UUID) -> User | None:
        result = await self._session.execute(select(User).where(User.id == user_id))
        return result.unique().scalar_one_or_none()

    async def list_all(self, limit: int = 100) -> list[User]:
        """列出用户（供「添加成员」选择候选）。按创建时间倒序，避免只看到最早的用户。"""
        result = await self._session.execute(
            select(User).order_by(User.created_at.desc()).limit(limit)
        )
        return list(result.unique().scalars().all())

    async def create(
        self,
        *,
        email: str,
        full_name: str,
        hashed_password: str,
        is_active: bool = True,
    ) -> User:
        user = User(
            email=email,
            full_name=full_name,
            hashed_password=hashed_password,
            is_active=is_active,
        )
        self._session.add(user)
        await self.flush_or_raise_duplicate(field="email", value=email)
        # 新建对象的集合属性仍未加载；若调用方紧接着访问 user.roles，
        # 在 async 会话里会触发 lazy load 并抛 MissingGreenlet。这里主动加载一次。
        await self._session.refresh(user, attribute_names=["roles"])
        return user


class RoleRepository(SqlAlchemyRepository):
    async def ensure_role(self, name: str, description: str | None = None) -> Role:
        result = await self._session.execute(select(Role).where(Role.name == name))
        role = result.unique().scalar_one_or_none()
        if role is not None:
            return role
        role = Role(name=name, description=description)
        self._session.add(role)
        await self.flush_or_raise_duplicate(field="role", value=name)
        return role

    async def ensure_permissions(self, codes: list[str]) -> list[Permission]:
        created: list[Permission] = []
        existing = {
            permission.code: permission
            for permission in (
                await self._session.execute(select(Permission).where(Permission.code.in_(codes)))
            )
            .unique()
            .scalars()
            .all()
        }
        for code in codes:
            permission = existing.get(code)
            if permission is None:
                permission = Permission(code=code)
                self._session.add(permission)
                created.append(permission)
        if created:
            await self.flush_or_raise_duplicate(field="permission", value=",".join(codes))
        return [
            existing.get(code) or next(item for item in created if item.code == code)
            for code in codes
        ]

    async def bind_permissions(self, role: Role, codes: list[str]) -> None:
        """把 codes 关联到 role 上（幂等，缺少的补齐，已有的不重复插入）。

        这里刻意**不写** `role.permissions = [...]`：给集合赋值会触发 lazy load，
        在 async 会话下会抛 MissingGreenlet。直接写关联表更可控。
        """
        permissions = await self.ensure_permissions(codes)
        existing = set(
            (
                await self._session.execute(
                    select(role_permissions.c.permission_id).where(
                        role_permissions.c.role_id == role.id
                    )
                )
            )
            .scalars()
            .all()
        )
        missing = [
            {"role_id": role.id, "permission_id": permission.id}
            for permission in permissions
            if permission.id not in existing
        ]
        if missing:
            await self._session.execute(insert(role_permissions), missing)
            await self._session.flush()
            # 让内存中的 role.permissions 与数据库保持一致
            self._session.expire(role, attribute_names=["permissions"])

    async def assign_role(self, user: User, role: Role) -> None:
        """幂等授予角色。同样不走 ORM 集合赋值，避免隐式 lazy load。"""
        existing = (
            await self._session.execute(
                select(user_roles.c.role_id).where(
                    user_roles.c.user_id == user.id, user_roles.c.role_id == role.id
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return
        await self._session.execute(insert(user_roles), [{"user_id": user.id, "role_id": role.id}])
        await self._session.flush()
        self._session.expire(user, attribute_names=["roles"])
