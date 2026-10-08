/** Agent 基础设施契约镜像 —— 对应 `dw_schemas.agent`。 */

export type AgentType = "supervisor" | "design" | "quote" | "construction" | "aftersales" | "reviewer";
export type RunMode = "direct" | "sequential" | "parallel_dag";
export type RunStatus = "pending" | "running" | "awaiting_approval" | "completed" | "failed" | "cancelled";
export type TaskStatus = "pending" | "running" | "awaiting_approval" | "completed" | "failed";
export type ToolCallStatus = "success" | "failed" | "timeout" | "denied";
export type ApprovalStatus = "pending" | "approved" | "rejected";
export type RiskLevel = "L0" | "L1" | "L2" | "L3";

export interface AgentOut {
  agent_id: string;
  agent_type: AgentType;
  description: string;
  version: string;
  supported_skills: string[];
  required_scopes: string[];
  enabled: boolean;
}

export interface SkillOut {
  skill_id: string;
  agent_type: AgentType;
  version: string;
  required_scopes: string[];
  risk_level: RiskLevel;
  allowed_tools: string[];
  enabled: boolean;
}

export interface ToolOut {
  tool_id: string;
  description: string;
  required_scopes: string[];
  risk_level: RiskLevel;
  timeout_ms: number;
  retry_max_attempts: number;
  fallback_tool_id: string | null;
  idempotency_required: boolean;
  audit_required: boolean;
  enabled: boolean;
}

export interface TaskOut {
  id: string;
  task_key: string;
  agent_id: string;
  skill_id: string;
  status: TaskStatus;
  attempt: number;
  risk_level: RiskLevel;
  allowed_tools: string[];
  depends_on: string[];
  artifact_id: string | null;
  error: string | null;
}

export interface RunOut {
  id: string;
  project_id: string | null;
  status: RunStatus;
  mode: RunMode;
  objective: string;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  tasks: TaskOut[];
  artifact_ids: string[];
  approval_id: string | null;
  review_decision: string | null;
  review_issues: string[];
}

export interface ArtifactOut {
  id: string;
  run_id: string;
  artifact_type: string;
  producer: string;
  payload: Record<string, unknown>;
  version: number;
  created_at: string;
}

export interface ToolCallOut {
  id: string;
  tool_id: string;
  status: ToolCallStatus;
  attempt: number;
  duration_ms: number;
  error: string | null;
  created_at: string;
}

export interface RunEvent {
  kind: "run" | "task" | "tool_call" | string;
  at: string;
  summary: string;
  status: string;
  detail: Record<string, unknown>;
}

export interface ApprovalOut {
  id: string;
  run_id: string;
  task_id: string | null;
  status: ApprovalStatus;
  reason: string;
  created_at: string;
  decided_at: string | null;
}

export interface RunCreateRequest {
  intent?: string;
  objective: string;
  project_id?: string;
  input?: Record<string, unknown>;
}

/** Artifact 类型 → 中文标签，供前端卡片标题与渲染分发。 */
export const ARTIFACT_LABELS: Record<string, string> = {
  project_snapshot: "项目概览",
  aftersales_diagnosis: "售后诊断",
  quote_estimate: "报价估算",
  design_proposal: "设计提案",
  construction_review: "施工审查",
};
