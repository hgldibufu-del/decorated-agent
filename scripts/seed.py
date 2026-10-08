"""演示数据 —— 需求文档 §27。

设计原则：
* **幂等**：可以反复执行。用户按邮箱、客户按手机号、房屋按地址、项目按编号去重；
* **可复生产性**：口令统一为 `DEFAULT_SEED_PASSWORD`（默认 `Passw0rd!`）。
  若使用默认值会在结尾打印警告，提示在生产环境必须替换；
* 只依赖 `dw-domain`，不绕过领域层直接写 SQL。

用法：
    python scripts/seed.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from decimal import Decimal
from sqlalchemy import select

from dw_domain.rbac_defaults import ROLE_PERMISSIONS
from dw_domain.repositories.agent_runtime import RegistryRepository
from dw_domain.repositories.iam import RoleRepository, UserRepository
from dw_domain.repositories.projects import (
    CustomerRepository,
    HouseRepository,
    ProjectRepository,
)
from dw_domain.models import (
    ConstructionMilestone,
    DesignStyle,
    LayoutModule,
    QualityChecklist,
    QuoteItem,
    QuotePackage,
)
from dw_domain.security import hash_password
from dw_infrastructure.config import get_settings
from dw_infrastructure.db import Database
from dw_schemas.agent import AgentType, RiskLevel
from dw_schemas.iam import PermissionCode, ProjectRole, RoleName
from dw_schemas.project import ProjectStatus

DEFAULT_PASSWORD = "Passw0rd!"

# -----------------------------------------------------------------------------
# 用户（10 个）
# -----------------------------------------------------------------------------
USERS: list[tuple[str, str, list[str]]] = [
    ("admin@dw.local", "系统管理员", [RoleName.ADMIN.value]),
    ("pm.wang@dw.local", "王志远", [RoleName.PROJECT_MANAGER.value]),
    ("pm.li@dw.local", "李婷", [RoleName.PROJECT_MANAGER.value]),
    ("designer.zhao@dw.local", "赵敏", [RoleName.DESIGNER.value]),
    ("designer.chen@dw.local", "陈亦然", [RoleName.DESIGNER.value]),
    ("estimator.sun@dw.local", "孙博", [RoleName.ESTIMATOR.value]),
    ("cm.zhou@dw.local", "周凯", [RoleName.CONSTRUCTION_MANAGER.value]),
    ("aftersales.wu@dw.local", "吴倩", [RoleName.AFTERSALES.value]),
    ("aftersales.zheng@dw.local", "郑昊", [RoleName.AFTERSALES.value]),
    ("viewer.hu@dw.local", "胡静", [RoleName.VIEWER.value]),
]

# -----------------------------------------------------------------------------
# 客户 / 房屋 / 项目（各 5 条）
# -----------------------------------------------------------------------------
CUSTOMERS: list[tuple[str, str, str | None]] = [
    ("刘女士", "13800000001", "liu@example.com"),
    ("王先生", "13800000002", "wang@example.com"),
    ("张女士", "13800000003", None),
    ("李先生", "13800000004", "li@example.com"),
    ("陈女士", "13800000005", None),
]

HOUSES: list[tuple[int, str, str, Decimal, str]] = [
    (0, "星河湾 3 期 3-1201", "上海", Decimal("118.50"), "三室两厅"),
    (1, "保利叶语 8-0903", "上海", Decimal("89.00"), "两室两厅"),
    (2, "翠湖天地 5-2202", "杭州", Decimal("143.20"), "四室两厅"),
    (3, "万科城一路 12-0401", "南京", Decimal("96.40"), "三室一厅"),
    (4, "中海观园 2-1803", "苏州", Decimal("132.00"), "三室两厅"),
]

PROJECTS: list[tuple[str, str, int, int, ProjectStatus, Decimal, str]] = [
    (
        "GC-2026-001",
        "星河湾现代简约整装",
        0,
        0,
        ProjectStatus.ACTIVE,
        Decimal("380000.00"),
        "客户偏好无主灯与隐形收纳",
    ),
    (
        "GC-2026-002",
        "保利叶语北欧风改造",
        1,
        1,
        ProjectStatus.ACTIVE,
        Decimal("210000.00"),
        "预算偏紧，优先控制硬装成本",
    ),
    (
        "GC-2026-003",
        "翠湖天地新中式整装",
        2,
        2,
        ProjectStatus.DRAFT,
        Decimal("560000.00"),
        "需要全屋智能预留",
    ),
    (
        "GC-2026-004",
        "万科城旧房翻新",
        3,
        3,
        ProjectStatus.ON_HOLD,
        Decimal("175000.00"),
        "等待客户确认拆改范围",
    ),
    (
        "GC-2026-005",
        "中海观园婚房整装",
        4,
        4,
        ProjectStatus.COMPLETED,
        Decimal("295000.00"),
        "已交付，处于质保期",
    ),
]

# 项目成员：项目编号 → (用户邮箱, 项目内角色)
# -----------------------------------------------------------------------------
# Agent 注册中心（§6）
#
# 只注册「已有真实执行体」的 Agent / Skill / Tool。
# §5 里 Design / Quote / Construction / AfterSales 的技能随各自 Phase 落地，
# 不在本阶段注册空壳 —— 空壳会让前端以为能力已具备。
# -----------------------------------------------------------------------------
# 报价目录（Phase 5）：套餐 + 工艺/材料项（确定性演示数据）
QUOTE_PACKAGES: list[tuple[str, str, str, Decimal, Decimal, dict]] = [
    ("经济整装包", "满足基础居住需求的整装套餐", "经济", Decimal("18000.00"), Decimal("880.00"), {"含": ["设计", "硬装", "基础主材"], "不含": ["家具家电", "个性化软装"]}),
    ("标准整装包", "主流品质整装，含主材与基础软装", "标准", Decimal("28000.00"), Decimal("1280.00"), {"含": ["设计", "硬装", "主材"], "不含": ["家具家电", "智能系统"]}),
    ("高端定制包", "全屋定制与高端主材", "高端", Decimal("48000.00"), Decimal("1880.00"), {"含": ["设计", "硬装", "主材", "基础软装"], "不含": ["家具家电"]}),
]


QUOTE_ITEMS: list[tuple[str, str, str, Decimal, dict]] = [
    ("硬装", "水电隐蔽工程", "项", Decimal("28000.00"), {"keywords": ["水电", "隐蔽", "防水"]}),
    ("硬装", "墙面基层与乳胶漆", "m²", Decimal("68.00"), {"keywords": ["墙面", "乳胶漆", "基层"]}),
    ("主材", "实木复合地板", "m²", Decimal("220.00"), {"keywords": ["地板", "木地板"]}),
    ("主材", "整体橱柜", "延米", Decimal("1850.00"), {"keywords": ["橱柜", "厨房"]}),
    ("软装", "全屋窗帘", "项", Decimal("6500.00"), {"keywords": ["窗帘", "软装"]}),
]


# 设计目录（Phase 6）：风格 + 户型模块（确定性演示数据）
DESIGN_STYLES: list[tuple[str, str, str, list[str], list[str], dict, list[str]]] = [
    (
        "现代简约",
        "现代简约",
        "强调留白与功能性，去繁就简，适合中小户型",
        ["两室两厅", "三室两厅", "四室两厅"],
        ["#F5F5F5", "#E0E0E0", "#FFFFFF", "#222222"],
        {"明亮通透": True, "强调收纳": True, "去繁就简": True},
        ["现代", "简约", "无主灯"],
    ),
    (
        "新中式",
        "新中式",
        "以东方美学重构空间，木作与留白并重",
        ["三室两厅", "四室两厅"],
        ["#8C6A4F", "#D9C7B0", "#3E3A36", "#FFFFFF"],
        {"文化底蕴": True, "对称稳重": True, "木作质感": True},
        ["新中式", "传统", "沉稳"],
    ),
    (
        "北欧",
        "北欧",
        "自然材质与柔和色彩，强调采光与舒适",
        ["两室两厅", "三室两厅"],
        ["#FAFAFA", "#A9C5C2", "#E8B4A0", "#D7CCC8"],
        {"自然温馨": True, "采光优先": True, "轻量化": True},
        ["北欧", "自然", "温馨"],
    ),
    (
        "工业风",
        "工业风",
        "裸露结构与冷调材质，强调个性与粗犷",
        ["三室两厅", "四室两厅", "复式"],
        ["#3A3A3A", "#B0A08F", "#7A7A7A", "#C0392B"],
        {"个性粗犷": True, "材质裸露": True, "冷调": True},
        ["工业", "个性", "loft"],
    ),
]

LAYOUT_MODULES: list[tuple[str, str, str, str, str | None]] = [
    ("卧室", "休息与收纳", "静谧色调，注重隔音与储物", "主材", "主卧宜朝南、次卧兼顾多功能"),
    ("客厅", "会客与家庭活动", "开阔通透，动线流畅，采光优先", "主材", "与餐厅一体化可放大空间感"),
    ("餐厅", "用餐", "靠近厨房，灯光温馨", "软装", "岛台或卡座提升社交属性"),
    ("厨房", "烹饪", "动线三角布局，易清洁", "硬装", "烟道与水位提前规划"),
    ("卫生间", "洗漱沐浴", "干湿分离，防水优先", "硬装", "同层排水减少噪音"),
    ("阳台", "休闲 / 晾晒", "功能分区，兼顾采光", "主材", "封窗与晾晒区分离"),
]


# 施工目录（Phase 7）：标准施工阶段模板 + 全局验收清单
CONSTRUCTION_STAGES: list[tuple[str, int, int, str]] = [
    # (stage, seq, planned_days, standard)
    ("水电改造", 1, 7, "线管横平竖直、强弱电分离、打压试验合格"),
    ("泥瓦工程", 2, 10, "墙地砖空鼓率达标、防水闭水试验合格"),
    ("木工工程", 3, 8, "龙骨牢固、收口平整、柜体方正"),
    ("油漆工程", 4, 6, "基层平整、无流挂色差、环保检测达标"),
    ("安装收尾", 5, 5, "五金安装到位、成品保护完好"),
]

# 按项目状态决定已完成阶段数（演示用确定性规则，真实系统由施工报量驱动）
COMPLETED_STAGES_BY_STATUS: dict[str, int] = {
    ProjectStatus.DRAFT.value: 0,
    ProjectStatus.ON_HOLD.value: 2,
    ProjectStatus.ACTIVE.value: 3,
    ProjectStatus.COMPLETED.value: 5,
}

QUALITY_ITEMS: list[tuple[str, str, str, int, str]] = [
    # (category, item, standard, weight, severity)
    ("水电", "强弱电分离", "强弱电间距≥300mm，交叉处屏蔽", 3, "高"),
    ("水电", "水管打压试验", "打压 0.8MPa 保持 30min 无渗漏", 3, "高"),
    ("防水", "闭水试验", "蓄水 24h 无渗漏", 3, "高"),
    ("泥瓦", "墙地砖空鼓", "单块空鼓面积≤5%", 2, "中"),
    ("木工", "柜体方正度", "对角线偏差≤2mm", 2, "中"),
    ("油漆", "墙面平整度", "2m 靠尺偏差≤3mm", 1, "低"),
]


TOOLS: list[tuple[str, str, list[str], RiskLevel, int, int, str | None]] = [
    # (tool_id, description, scopes, risk, timeout_ms, retry_attempts, fallback)
    (
        "project_query",
        "按 ID 查询项目（受 Project ACL 约束）",
        ["project:read"],
        RiskLevel.L0,
        5000,
        2,
        None,
    ),
    ("project_list", "列出当前用户可见的项目", ["project:read"], RiskLevel.L0, 5000, 2, None),
    ("artifact_query", "读取 Artifact 内容", ["project:read"], RiskLevel.L0, 5000, 1, None),
    # Phase 4：AfterSales 的 RAG 工具（L0，证据检索类，不写业务）
    ("case_search", "混合检索相关售后知识/案例", ["project:read"], RiskLevel.L0, 5000, 2, None),
    ("root_cause", "基于 RAG 证据与规则产出根因假设", ["project:read"], RiskLevel.L0, 5000, 2, None),
    ("case_match", "向量匹配相似历史售后案例", ["project:read"], RiskLevel.L0, 5000, 2, None),
    # Phase 5：Quote 的业务表驱动工具（L0，只读估算）
    ("budget_estimate", "基于项目面积与套餐计算报价明细与总价", ["project:read", "quote:read"], RiskLevel.L0, 5000, 2, None),
    ("package_compare", "同一面积下对比多个套餐总价与每平米单价", ["project:read", "quote:read"], RiskLevel.L0, 5000, 2, None),
    ("material_lookup", "按类目/关键词检索工艺与材料项", ["project:read", "quote:read"], RiskLevel.L0, 5000, 2, None),
    # Phase 6：Design 的业务表驱动工具（L0，只读分析）
    ("layout_analysis", "基于项目户型与面积产出空间规划建议", ["project:read", "design:read"], RiskLevel.L0, 5000, 2, None),
    ("style_match", "按偏好 / 约束匹配并排序设计风格", ["project:read", "design:read"], RiskLevel.L0, 5000, 2, None),
    # Phase 7：Construction 的业务表驱动工具（L0，只读分析）
    ("progress_analysis", "按项目施工阶段对比计划/实际工期", ["project:read", "construction:read"], RiskLevel.L0, 5000, 2, None),
    ("quality_check", "按类目评估验收项并给出加权得分", ["project:read", "construction:read"], RiskLevel.L0, 5000, 2, None),
    # Phase 10：记忆工具（受治理）。记忆按用户维度，与项目无关，故只需 memory scope。
    ("memory_recall", "召回当前用户的长期记忆（偏好 / 约束 / 事实）", ["memory:read"], RiskLevel.L0, 5000, 2, None),
    ("memory_remember", "写入或更新当前用户的一条长期记忆（按 kind + key 幂等）", ["memory:write"], RiskLevel.L0, 5000, 2, None),
]

SKILLS: list[tuple[str, str, list[str], RiskLevel, list[str]]] = [
    # (skill_id, agent_type, scopes, risk, allowed_tools)
    (
        "project_snapshot",
        AgentType.SUPERVISOR.value,
        ["project:read"],
        RiskLevel.L0,
        # `memory_recall` 允许但**不**进入 required_scopes：技能内部按
        # `ctx.memory is not None`（等价于持有 memory:read）决定是否真的调用
        ["project_query", "artifact_query", "memory_recall"],
    ),
    # Phase 4：AfterSales 售后诊断技能（L1，端到端可跑、不触发审批门控）
    (
        "aftersales_diagnosis",
        AgentType.AFTERSALES.value,
        ["project:read"],
        RiskLevel.L1,
        ["case_search", "root_cause", "case_match"],
    ),
    # Phase 5：Quote 报价估算技能（L0，只读估算，不产生业务写操作）
    (
        "quote_estimate",
        AgentType.QUOTE.value,
        ["project:read", "quote:read"],
        RiskLevel.L0,
        ["budget_estimate", "package_compare", "material_lookup"],
    ),
    # Phase 6：Design 设计提案技能（L0，只读分析/合成）
    (
        "design_proposal",
        AgentType.DESIGN.value,
        ["project:read", "design:read"],
        RiskLevel.L0,
        ["layout_analysis", "style_match"],
    ),
    # Phase 7：Construction 施工审查技能（L0，只读分析/合成）
    (
        "construction_review",
        AgentType.CONSTRUCTION.value,
        ["project:read", "construction:read"],
        RiskLevel.L0,
        ["progress_analysis", "quality_check"],
    ),
]

AGENTS: list[tuple[str, str, str, list[str], list[str]]] = [
    # (agent_id, agent_type, description, scopes, supported_skills)
    (
        "supervisor_agent",
        AgentType.SUPERVISOR.value,
        "总控 Agent：理解用户目标、加载项目上下文、规划任务",
        ["project:read"],
        ["project_snapshot"],
    ),
    # Phase 4：AfterSales Agent（专业领域判断）
    (
        "aftersales_agent",
        AgentType.AFTERSALES.value,
        "售后 Agent：根因分析、案例匹配、处置建议",
        ["project:read"],
        ["aftersales_diagnosis"],
    ),
    # Phase 5：Quote Agent（专业领域判断）
    (
        "quote_agent",
        AgentType.QUOTE.value,
        "报价 Agent：预算估算、套餐对比、材料检索",
        ["project:read", "quote:read"],
        ["quote_estimate"],
    ),
    # Phase 6：Design Agent（专业领域判断）
    (
        "design_agent",
        AgentType.DESIGN.value,
        "设计 Agent：空间规划分析、风格匹配、设计提案",
        ["project:read", "design:read"],
        ["design_proposal"],
    ),
    # Phase 7：Construction Agent（专业领域判断）
    (
        "construction_agent",
        AgentType.CONSTRUCTION.value,
        "施工 Agent：进度分析、验收评估、施工审查",
        ["project:read", "construction:read"],
        ["construction_review"],
    ),
]

PROJECT_MEMBERS: dict[str, list[tuple[str, ProjectRole]]] = {
    "GC-2026-001": [
        ("pm.wang@dw.local", ProjectRole.OWNER),
        ("designer.zhao@dw.local", ProjectRole.MEMBER),
        ("estimator.sun@dw.local", ProjectRole.MEMBER),
        ("cm.zhou@dw.local", ProjectRole.MANAGER),
    ],
    "GC-2026-002": [
        ("pm.li@dw.local", ProjectRole.OWNER),
        ("designer.chen@dw.local", ProjectRole.MEMBER),
    ],
    "GC-2026-003": [
        ("pm.wang@dw.local", ProjectRole.OWNER),
        ("designer.zhao@dw.local", ProjectRole.MANAGER),
        ("viewer.hu@dw.local", ProjectRole.VIEWER),
    ],
    "GC-2026-004": [
        ("pm.li@dw.local", ProjectRole.OWNER),
        ("estimator.sun@dw.local", ProjectRole.MANAGER),
    ],
    "GC-2026-005": [
        ("pm.wang@dw.local", ProjectRole.OWNER),
        ("aftersales.wu@dw.local", ProjectRole.MEMBER),
    ],
}


async def _seed_quote_catalog(session) -> dict[str, int]:
    """幂等插入报价目录（按名称去重），使 Quote 能力开箱可用。"""
    counters = {"quote_packages": 0, "quote_items": 0}
    for name, desc, tier, base, per, scope in QUOTE_PACKAGES:
        existing = (
            await session.execute(select(QuotePackage).where(QuotePackage.name == name))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                QuotePackage(
                    name=name,
                    description=desc,
                    tier=tier,
                    base_price=base,
                    price_per_sqm=per,
                    included_scope=scope,
                )
            )
            counters["quote_packages"] += 1
    for category, name, unit, price, meta in QUOTE_ITEMS:
        existing = (
            await session.execute(select(QuoteItem).where(QuoteItem.name == name))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                QuoteItem(
                    category=category,
                    name=name,
                    unit=unit,
                    unit_price=price,
                    metadata_json=meta,
                )
            )
            counters["quote_items"] += 1
    return counters


async def _seed_design_catalog(session) -> dict[str, int]:
    """幂等插入设计目录（按名称去重），使 Design 能力开箱可用。"""
    counters = {"design_styles": 0, "layout_modules": 0}
    for name, family, desc, layouts, palette, chars, tags in DESIGN_STYLES:
        existing = (
            await session.execute(select(DesignStyle).where(DesignStyle.name == name))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                DesignStyle(
                    name=name,
                    style_family=family,
                    description=desc,
                    suitable_layouts=layouts,
                    palette=palette,
                    characteristics=chars,
                    tags=tags,
                )
            )
            counters["design_styles"] += 1
    for room_type, function, principle, category, notes in LAYOUT_MODULES:
        existing = (
            await session.execute(
                select(LayoutModule).where(LayoutModule.room_type == room_type)
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                LayoutModule(
                    room_type=room_type,
                    suggested_function=function,
                    design_principle=principle,
                    recommended_material_category=category,
                    notes=notes,
                )
            )
            counters["layout_modules"] += 1
    return counters


async def _seed_construction_catalog(session, projects) -> dict[str, int]:
    """幂等写入施工目录：全局验收清单 + 各项目施工阶段（按项目状态生成进度）。"""
    counters = {"construction_milestones": 0, "quality_checklists": 0}
    for category, item, standard, weight, severity in QUALITY_ITEMS:
        existing = (
            await session.execute(select(QualityChecklist).where(QualityChecklist.item == item))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                QualityChecklist(
                    category=category,
                    item=item,
                    standard=standard,
                    weight=weight,
                    severity=severity,
                )
            )
            counters["quality_checklists"] += 1

    for project, status in projects:
        status_value = status.value if hasattr(status, "value") else str(status)
        completed = COMPLETED_STAGES_BY_STATUS.get(status_value, 0)
        for stage, seq, planned, standard in CONSTRUCTION_STAGES:
            existing = (
                await session.execute(
                    select(ConstructionMilestone).where(
                        ConstructionMilestone.project_id == project.id,
                        ConstructionMilestone.stage == stage,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue
            if seq <= completed:
                # 偶数阶段演示性延期 1 天，使进度分析能产出「落后阶段」
                m_status, actual = "completed", planned + (1 if seq % 2 == 0 else 0)
            elif seq == completed + 1:
                m_status, actual = "in_progress", None
            else:
                m_status, actual = "pending", None
            session.add(
                ConstructionMilestone(
                    project_id=project.id,
                    stage=stage,
                    seq=seq,
                    planned_days=planned,
                    actual_days=actual,
                    status=m_status,
                    standard=standard,
                )
            )
            counters["construction_milestones"] += 1
    return counters


async def seed(password: str) -> dict[str, int]:
    database = Database.from_settings(get_settings())
    counters = {
        "users": 0,
        "roles": 0,
        "permissions": 0,
        "customers": 0,
        "houses": 0,
        "projects": 0,
        "members": 0,
        "tools": 0,
        "skills": 0,
        "agents": 0,
        "quote_packages": 0,
        "quote_items": 0,
        "design_styles": 0,
        "layout_modules": 0,
        "construction_milestones": 0,
        "quality_checklists": 0,
    }

    try:
        async with database.session() as session:
            roles_repo = RoleRepository(session)
            users_repo = UserRepository(session)
            customers_repo = CustomerRepository(session)
            houses_repo = HouseRepository(session)
            projects_repo = ProjectRepository(session)

            # 1) 权限 + 角色 + 绑定
            all_codes = [permission.value for permission in PermissionCode]
            await roles_repo.ensure_permissions(all_codes)
            counters["permissions"] = len(all_codes)

            roles: dict[str, object] = {}
            for role_name, permissions in ROLE_PERMISSIONS.items():
                role = await roles_repo.ensure_role(role_name, description=f"{role_name} 内置角色")
                await roles_repo.bind_permissions(role, permissions)
                roles[role_name] = role
                counters["roles"] += 1

            # 2) 用户
            user_ids: dict[str, object] = {}
            for email, full_name, role_names in USERS:
                existing = await users_repo.get_by_email(email)
                if existing is None:
                    user = await users_repo.create(
                        email=email,
                        full_name=full_name,
                        hashed_password=hash_password(password),
                    )
                    counters["users"] += 1
                else:
                    user = existing
                for role_name in role_names:
                    await roles_repo.assign_role(user, roles[role_name])  # type: ignore[arg-type]
                user_ids[email] = user.id

            # 3) 客户（按手机号去重）
            customer_ids: list[object] = []
            for name, phone, email in CUSTOMERS:
                customer = await customers_repo.get_by_phone(phone)
                if customer is None:
                    customer = await customers_repo.create(name=name, phone=phone, email=email)
                    counters["customers"] += 1
                customer_ids.append(customer.id)

            # 4) 房屋（按地址去重）
            house_ids: dict[int, object] = {}
            for index, customer_index, address, city, area, layout in (
                (i, h[0], h[1], h[2], h[3], h[4]) for i, h in enumerate(HOUSES)
            ):
                existing = await houses_repo.get_by_address(address)
                if existing is not None:
                    house_ids[index] = existing.id
                    continue
                house = await houses_repo.create(
                    customer_id=customer_ids[customer_index],  # type: ignore[arg-type]
                    address=address,
                    city=city,
                    area_sqm=area,
                    layout=layout,
                )
                house_ids[index] = house.id
                counters["houses"] += 1

            # 5) 项目 + 成员
            seeded_projects: list[tuple[object, str]] = []
            for code, name, customer_index, house_index, status, budget, note in PROJECTS:
                project = await projects_repo.get_by_code(code)
                if project is None:
                    project = await projects_repo.create(
                        code=code,
                        name=name,
                        customer_id=customer_ids[customer_index],  # type: ignore[arg-type]
                        house_id=house_ids[house_index],  # type: ignore[arg-type]
                        status=status,
                        budget_amount=budget,
                        note=note,
                    )
                    counters["projects"] += 1
                seeded_projects.append((project, status))

            # 6) Agent 注册中心（工具 → 技能 → Agent，顺序即依赖顺序）
            registry = RegistryRepository(session)
            for tool_id, description, scopes, risk, timeout, attempts, fallback in TOOLS:
                existed = await registry.get_tool(tool_id) is not None
                await registry.ensure_tool(
                    tool_id=tool_id,
                    description=description,
                    required_scopes=scopes,
                    risk_level=risk,
                    timeout_ms=timeout,
                    retry_max_attempts=attempts,
                    fallback_tool_id=fallback,
                )
                if not existed:
                    counters["tools"] += 1

            for skill_id, agent_type, scopes, risk, allowed_tools in SKILLS:
                existed = await registry.get_skill(skill_id) is not None
                await registry.ensure_skill(
                    skill_id=skill_id,
                    agent_type=agent_type,
                    version="0.1.0",
                    required_scopes=scopes,
                    risk_level=risk,
                    allowed_tools=allowed_tools,
                )
                if not existed:
                    counters["skills"] += 1

            for agent_id, agent_type, description, scopes, supported_skills in AGENTS:
                existed = await registry.get_agent(agent_id) is not None
                await registry.ensure_agent(
                    agent_id=agent_id,
                    agent_type=agent_type,
                    description=description,
                    version="0.1.0",
                    supported_skills=supported_skills,
                    required_scopes=scopes,
                )
                if not existed:
                    counters["agents"] += 1

                for email, project_role in PROJECT_MEMBERS.get(code, []):
                    user_id = user_ids[email]
                    existing_member = await projects_repo.get_member(project.id, user_id)  # type: ignore[arg-type]
                    if existing_member is None:
                        await projects_repo.add_member(
                            project_id=project.id,  # type: ignore[arg-type]
                            user_id=user_id,  # type: ignore[arg-type]
                            role=project_role,
                        )
                        counters["members"] += 1

            # 7) 报价目录（Phase 5）
            quote_counts = await _seed_quote_catalog(session)
            counters["quote_packages"] += quote_counts["quote_packages"]
            counters["quote_items"] += quote_counts["quote_items"]

            # 8) 设计目录（Phase 6）
            design_counts = await _seed_design_catalog(session)
            counters["design_styles"] += design_counts["design_styles"]
            counters["layout_modules"] += design_counts["layout_modules"]

            # 9) 施工目录 + 分项目阶段（Phase 7）
            construction_counts = await _seed_construction_catalog(session, seeded_projects)
            counters["construction_milestones"] += construction_counts["construction_milestones"]
            counters["quality_checklists"] += construction_counts["quality_checklists"]
    finally:
        await database.dispose()

    return counters


def main() -> int:
    password = os.getenv("DEFAULT_SEED_PASSWORD", DEFAULT_PASSWORD)
    is_default = password == DEFAULT_PASSWORD

    counters = asyncio.run(seed(password))

    print("Seed 完成：")
    for key, value in counters.items():
        print(f"  - {key}: {value}")
    print(f"\n登录口令：{password}（账号列表见 scripts/seed.py 的 USERS）")
    if is_default:
        print("警告：正在使用默认口令，仅可用于本地演示。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
