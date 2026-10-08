"""设计业务表 —— Phase 6（Design Specialist）。

与 Phase 5 的报价表同构：业务表驱动的确定性设计提案，不依赖 LLM，
可解释、可测、零外部依赖。动态结构（色板 / 适用户型 / 特征 / 标签）用 JSONB。
"""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dw_domain.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DesignStyle(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """设计风格目录：风格族 + 适用户型 + 色板 + 特征 + 标签。"""

    __tablename__ = "design_styles"

    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    style_family: Mapped[str | None] = mapped_column(
        String(64), comment="现代简约 / 新中式 / 北欧 …"
    )
    description: Mapped[str | None] = mapped_column(String(2000))
    suitable_layouts: Mapped[list[str] | None] = mapped_column(JSONB, comment="适用户型列表")
    palette: Mapped[list[str] | None] = mapped_column(JSONB, comment="推荐色板（hex 列表）")
    characteristics: Mapped[dict | None] = mapped_column(JSONB, comment="风格特征（如 明亮通透）")
    tags: Mapped[list[str] | None] = mapped_column(JSONB, comment="检索标签")
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)


class LayoutModule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """户型模块指南：按房间类型给出功能建议、设计原则、建议材料类目。"""

    __tablename__ = "layout_modules"

    room_type: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, comment="卧室 / 客厅 / 厨房 …"
    )
    suggested_function: Mapped[str | None] = mapped_column(String(500))
    design_principle: Mapped[str | None] = mapped_column(String(2000))
    recommended_material_category: Mapped[str | None] = mapped_column(
        String(64), comment="主材 / 硬装 / 软装"
    )
    notes: Mapped[str | None] = mapped_column(String(2000))
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)
