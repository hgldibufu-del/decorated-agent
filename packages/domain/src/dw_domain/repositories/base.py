"""仓储基类 —— 需求文档 §23（Application → Domain → Repository → Infrastructure）。

仓储层只负责「怎么把对象取出来 / 存进去」，**不做业务决策**。
所有写操作显式 `flush()`：让唯一约束冲突在调用栈内抛出，
而不是等到外层 commit 时才炸（那样就无法映射成 409 了）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dw_domain.errors import DuplicateEntityError, EntityInUseError


class SqlAlchemyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def flush_or_raise_duplicate(self, *, field: str, value: str) -> None:
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # 唯一冲突是「预期内的业务错误」，必须转成领域异常并保留原异常链
            raise DuplicateEntityError(field, value) from exc
        except Exception:
            # 其余错误原样上抛，绝不吞掉
            raise

    async def delete_guarded(
        self, instance: Any, *, entity: str, referenced_by: str
    ) -> None:
        """删除实体；被外键 RESTRICT 引用时转成 `EntityInUseError`（→ 409）。

        业务事实不允许被连坐删除，因此这里**不**做级联，而是明确失败。
        """
        try:
            await self._session.delete(instance)
            await self._session.flush()
        except IntegrityError as exc:
            raise EntityInUseError(entity, referenced_by) from exc
