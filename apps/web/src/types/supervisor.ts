/** Supervisor 契约镜像 —— 对应 `dw_schemas.supervisor`。 */

import type { RunMode } from "./agent";

export type IntentType =
  | "project_overview"
  | "project_compare"
  | "aftersales_diagnosis"
  | "quote_estimate"
  | "design_proposal"
  | "construction_review"
  | "direct_request"
  | "unknown";

export interface PlanStep {
  task_key: string;
  agent_id: string;
  skill_id: string;
  objective: string;
  depends_on: string[];
  input: Record<string, unknown>;
}

export interface Plan {
  intent: IntentType;
  mode: RunMode;
  steps: PlanStep[];
  rationale: string;
}

/** 意图 → 中文标签，供工作台展示（与后端 planner 的映射一致）。 */
export const INTENT_LABELS: Record<IntentType, string> = {
  project_overview: "项目概览",
  project_compare: "项目对比",
  aftersales_diagnosis: "售后诊断",
  quote_estimate: "报价估算",
  design_proposal: "设计提案",
  construction_review: "施工审查",
  direct_request: "直接请求",
  unknown: "未识别",
};
