"""ORM 基础设施 —— 需求文档 §22 的通用要求。

统一在这里定死三件事，避免各表各写一套：

1. **命名约定**：索引/约束名由约定生成（`ix_`/`uq_`/`fk_`/`pk_`），迁移可读且可预期；
2. **UUID 主键**：全部业务实体使用 UUID，避免自增 ID 泄露规模与跨环境合并冲突；
3. **时间戳**：`created_at` / `updated_at` 由应用层写入时区感知的时间戳。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, MetaData
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

POSTGRES_NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """所有表的 Declarative 基类。"""

    metadata = MetaData(naming_convention=POSTGRES_NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """统一使用 timestamptz：asyncpg 不接受把时区感知的值写入 naive 列。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class OptimisticLockMixin:
    """并发写保护。

    只对会被并发修改的聚合根加（Project / User），不是每张表都需要。
    版本号由仓储层在 UPDATE 时显式比对，冲突抛 `StaleObjectError`。
    """

    version: Mapped[int] = mapped_column(default=1, nullable=False)
