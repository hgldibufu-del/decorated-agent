"""报价业务表 —— Phase 5（Quote Specialist）。

金额统一使用 `Decimal` / `NUMERIC(12,2)`，序列化用字符串（与 `project.py` 的金额约束一致）。
报价为**业务表驱动的确定性计算**，不依赖 LLM，可解释、可测、零外部依赖。
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dw_domain.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class QuotePackage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """整装套餐：用「基础费 + 面积×单价」表达一份标准报价方案。"""

    __tablename__ = "quote_packages"

    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(2000))
    tier: Mapped[str | None] = mapped_column(String(32), comment="经济 / 标准 / 高端")
    base_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    price_per_sqm: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    included_scope: Mapped[dict | None] = mapped_column(JSONB)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)


class QuoteItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """工艺 / 材料项：用于预算明细拆解与材料检索。"""

    __tablename__ = "quote_items"

    category: Mapped[str] = mapped_column(String(64), nullable=False, comment="硬装 / 主材 / 软装")
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False, comment="m² / 项 / 米 / 延米")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)
