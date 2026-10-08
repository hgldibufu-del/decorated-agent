"""Planner —— 需求文档 §4 / §7 / §32。

职责：把「意图 + 可见项目」翻译成**受限额约束**的执行计划。

两条硬规则（§32）：
* Planner 必须在限额内（max_steps / max_depth / max_parallel / deadline / retry_limit）；
* Planner 只能选注册中心里**真实存在且启用**的 Agent/Skill，遇到缺失即明确报错，
  绝不生成「看起来能跑」的假步骤。
"""

from __future__ import annotations

from uuid import UUID

from dw_domain.errors import UnsupportedIntentError
from dw_schemas.agent import RunMode
from dw_schemas.supervisor import (
    IntentResult,
    IntentType,
    Plan,
    PlannerLimits,
    PlanStep,
)

from dw_agent_runtime.registry import RuntimeRegistries
from dw_agent_runtime.supervisor.dag import validate_plan

# 意图 → 所需能力（Agent, Skill）。未列出的意图表示所需 Agent 尚未注册。
INTENT_CAPABILITY: dict[IntentType, tuple[str, str]] = {
    IntentType.PROJECT_OVERVIEW: ("supervisor_agent", "project_snapshot"),
    IntentType.PROJECT_COMPARE: ("supervisor_agent", "project_snapshot"),
    # Phase 4：AfterSales 已落地（Agent + 技能 + 三个 RAG 工具）
    IntentType.AFTERSALES_DIAGNOSIS: ("aftersales_agent", "aftersales_diagnosis"),
    # Phase 5：Quote 已落地（Agent + 技能 + 三个业务表驱动工具）
    IntentType.QUOTE_ESTIMATE: ("quote_agent", "quote_estimate"),
    # Phase 6：Design 已落地（Agent + 技能 + 两个业务表驱动工具）
    IntentType.DESIGN_PROPOSAL: ("design_agent", "design_proposal"),
    # Phase 7：Construction 已落地（Agent + 技能 + 两个业务表驱动工具）
    IntentType.CONSTRUCTION_REVIEW: ("construction_agent", "construction_review"),
}

# 尚未注册的能力（当前为空：§5 的四个领域 Specialist 均已落地）。
# 保留该结构：未来新增能力前，先在这里声明它属于哪个 Phase，
# 使「能力缺失」在规划阶段就能给出明确的 Phase 提示而非静默失败。
MISSING_CAPABILITY_HINT: dict[IntentType, str] = {}


class Planner:
    def __init__(
        self,
        registries: RuntimeRegistries,
        limits: PlannerLimits | None = None,
    ) -> None:
        self._registries = registries
        self._limits = limits or PlannerLimits()

    @property
    def limits(self) -> PlannerLimits:
        return self._limits

    def plan(
        self,
        *,
        intent_result: IntentResult,
        objective: str,
        project_ids: list[UUID],
    ) -> Plan:
        intent = intent_result.intent

        if intent is IntentType.UNKNOWN:
            raise UnsupportedIntentError(
                "unknown",
                "无法识别的意图；请补充更明确的业务诉求（如「看项目概览」「对比两个项目」）",
            )

        capability = INTENT_CAPABILITY.get(intent)
        if capability is None:
            raise UnsupportedIntentError(
                intent.value, MISSING_CAPABILITY_HINT.get(intent, "对应能力尚未注册")
            )

        agent_id, skill_id = capability
        self._require_capability(agent_id, skill_id, intent.value)

        if intent is IntentType.PROJECT_COMPARE:
            plan = self._compare_plan(agent_id, skill_id, objective, project_ids)
        elif intent is IntentType.AFTERSALES_DIAGNOSIS:
            plan = self._aftersales_plan(agent_id, skill_id, objective, project_ids)
        elif intent is IntentType.QUOTE_ESTIMATE:
            plan = self._quote_plan(agent_id, skill_id, objective, project_ids)
        elif intent is IntentType.DESIGN_PROPOSAL:
            plan = self._design_plan(agent_id, skill_id, objective, project_ids)
        elif intent is IntentType.CONSTRUCTION_REVIEW:
            plan = self._construction_plan(agent_id, skill_id, objective, project_ids)
        else:
            plan = self._overview_plan(agent_id, skill_id, objective, project_ids)

        # 计划生成后必须立刻过一遍 DAG 校验：不允许把非法计划带进执行阶段
        validate_plan(plan.steps, self._limits)
        return plan

    # ------------------------------------------------------------------ AfterSales
    def _aftersales_plan(
        self, agent_id: str, skill_id: str, objective: str, project_ids: list[UUID]
    ) -> Plan:
        """售后诊断：单步调用 AfterSales Agent 做根因分析与案例匹配。

        与 project_overview 不同，售后诊断不强制要求可见项目（问题本身即可诊断），
        但若有可见项目，把项目上下文一并带进技能输入，便于后续按项目收敛建议。
        """
        project_id = str(project_ids[0]) if project_ids else None
        step = PlanStep(
            task_key="T-001",
            agent_id=agent_id,
            skill_id=skill_id,
            objective=objective,
            input={"issue": objective, "project_id": project_id},
        )
        return Plan(
            intent=IntentType.AFTERSALES_DIAGNOSIS,
            mode=RunMode.DIRECT,
            steps=[step],
            rationale="售后诊断意图：单步调用 AfterSales Agent 进行根因分析与案例匹配",
        )

    # ------------------------------------------------------------------ Quote
    def _quote_plan(
        self, agent_id: str, skill_id: str, objective: str, project_ids: list[UUID]
    ) -> Plan:
        """报价估算：单步调用 Quote Agent，基于项目面积与套餐目录生成估算。

        与 overview 类似，报价估算**必须绑定一个可见项目**（面积取自项目关联房屋），
        没有项目上下文无法估算，因此无可见项目时明确报错。
        """
        if not project_ids:
            raise UnsupportedIntentError(
                "quote_estimate", "当前用户没有可见项目，无法生成报价估算计划"
            )

        project_id = project_ids[0]
        step = PlanStep(
            task_key="T-001",
            agent_id=agent_id,
            skill_id=skill_id,
            objective=objective,
            input={"project_id": str(project_id), "objective": objective},
        )
        return Plan(
            intent=IntentType.QUOTE_ESTIMATE,
            mode=RunMode.DIRECT,
            steps=[step],
            rationale="报价估算意图：单步调用 Quote Agent 基于项目面积与套餐目录生成估算",
        )

    # ------------------------------------------------------------------ Design
    def _design_plan(
        self, agent_id: str, skill_id: str, objective: str, project_ids: list[UUID]
    ) -> Plan:
        """设计提案：单步调用 Design Agent，基于户型/面积与风格目录生成提案。

        与 quote 类似，设计提案**必须绑定一个可见项目**（户型/面积取自项目关联房屋），
        没有项目上下文无法生成，因此无可见项目时明确报错。
        """
        if not project_ids:
            raise UnsupportedIntentError(
                "design_proposal", "当前用户没有可见项目，无法生成设计提案计划"
            )

        project_id = project_ids[0]
        step = PlanStep(
            task_key="T-001",
            agent_id=agent_id,
            skill_id=skill_id,
            objective=objective,
            input={"project_id": str(project_id), "objective": objective},
        )
        return Plan(
            intent=IntentType.DESIGN_PROPOSAL,
            mode=RunMode.DIRECT,
            steps=[step],
            rationale="设计提案意图：单步调用 Design Agent 基于户型/面积与风格目录生成设计提案",
        )

    # ------------------------------------------------------------------ Construction
    def _construction_plan(
        self, agent_id: str, skill_id: str, objective: str, project_ids: list[UUID]
    ) -> Plan:
        """施工审查：单步调用 Construction Agent，基于施工阶段与验收清单生成审查。

        与 quote / design 类似，施工审查**必须绑定一个可见项目**（进度/验收数据取自该项目），
        没有项目上下文无法审查，因此无可见项目时明确报错。
        """
        if not project_ids:
            raise UnsupportedIntentError(
                "construction_review", "当前用户没有可见项目，无法生成施工审查计划"
            )

        project_id = project_ids[0]
        step = PlanStep(
            task_key="T-001",
            agent_id=agent_id,
            skill_id=skill_id,
            objective=objective,
            input={"project_id": str(project_id), "objective": objective},
        )
        return Plan(
            intent=IntentType.CONSTRUCTION_REVIEW,
            mode=RunMode.DIRECT,
            steps=[step],
            rationale="施工审查意图：单步调用 Construction Agent 基于施工阶段与验收清单生成审查",
        )

    # ------------------------------------------------------------------ 内部
    def _require_capability(self, agent_id: str, skill_id: str, intent: str) -> None:
        try:
            self._registries.validate_task(agent_id, skill_id)
        except Exception as exc:
            raise UnsupportedIntentError(intent, f"{agent_id}.{skill_id}（{exc}）") from exc

    def _overview_plan(
        self, agent_id: str, skill_id: str, objective: str, project_ids: list[UUID]
    ) -> Plan:
        if not project_ids:
            raise UnsupportedIntentError(
                "project_overview", "当前用户没有可见项目，无法生成概览计划"
            )

        selected = project_ids[: self._limits.max_parallel]
        steps = [
            PlanStep(
                task_key=f"T-{index:03d}",
                agent_id=agent_id,
                skill_id=skill_id,
                objective=f"{objective}（{project_id}）" if len(selected) > 1 else objective,
                input={"project_id": str(project_id)},
            )
            for index, project_id in enumerate(selected, start=1)
        ]
        mode = RunMode.DIRECT if len(steps) == 1 else RunMode.PARALLEL_DAG
        rationale = (
            "单个项目，直接执行"
            if len(steps) == 1
            else (
                f"共 {len(project_ids)} 个可见项目，取前 {len(steps)} 个并行加载上下文"
                f"（max_parallel={self._limits.max_parallel}）"
            )
        )
        return Plan(intent=IntentType.PROJECT_OVERVIEW, mode=mode, steps=steps, rationale=rationale)

    def _compare_plan(
        self, agent_id: str, skill_id: str, objective: str, project_ids: list[UUID]
    ) -> Plan:
        if len(project_ids) < 2:
            raise UnsupportedIntentError("project_compare", "至少需要 2 个可见项目才能生成对比计划")

        first, second = project_ids[0], project_ids[1]
        steps = [
            PlanStep(
                task_key="T-001",
                agent_id=agent_id,
                skill_id=skill_id,
                objective=f"{objective}：先加载 {first} 的上下文",
                input={"project_id": str(first)},
            ),
            PlanStep(
                task_key="T-002",
                agent_id=agent_id,
                skill_id=skill_id,
                objective=f"{objective}：在 {first} 的上下文基础上加载 {second}",
                depends_on=["T-001"],
                input={"project_id": str(second)},
            ),
        ]
        return Plan(
            intent=IntentType.PROJECT_COMPARE,
            mode=RunMode.SEQUENTIAL,
            steps=steps,
            rationale="对比需要先后加载两侧上下文，第二个任务复用第一个任务的 Artifact",
        )
