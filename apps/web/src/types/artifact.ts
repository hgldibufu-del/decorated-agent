/** 各 Specialist 产出 Artifact 的 payload 形状（镜像各 SkillRunner 的返回）。 */

export interface ProjectSnapshotPayload {
  project: {
    id: string;
    code: string;
    name: string;
    status: string;
    customer_name: string;
    house_address: string;
    budget_amount: string | null;
    member_role: string | null;
  };
  upstream_artifacts: Array<Record<string, unknown>>;
  produced_by?: string;
}

export interface EvidenceChunk {
  content?: string;
  title?: string;
  source?: string;
  score?: number;
  [key: string]: unknown;
}

export interface AftersalesPayload {
  issue: string;
  hypothesis: string;
  suggested_actions: string[];
  confidence: number;
  evidence: EvidenceChunk[];
  similar_cases: Array<Record<string, unknown>>;
  produced_by?: string;
}

export interface QuoteLineItem {
  label: string;
  amount: string;
  detail: string;
}

export interface QuotePackageSummary {
  name: string;
  tier?: string | null;
  total?: string;
  per_sqm_effective?: string;
  base_price?: string;
  price_per_sqm?: string;
  [key: string]: unknown;
}

export interface QuoteMaterial {
  category: string;
  name: string;
  unit: string;
  unit_price: string;
}

export interface QuotePayload {
  project_id: string;
  layout: string | null;
  recommended_package: {
    name: string;
    tier: string | null;
    base_price: string;
    price_per_sqm: string;
    included_scope?: unknown;
  };
  estimate: { line_items: QuoteLineItem[]; total: string; currency: string };
  comparison: QuotePackageSummary[];
  materials: QuoteMaterial[];
  assumptions: string[];
  confidence: number;
}

export interface DesignSpace {
  room_type: string;
  suggested_function: string | null;
  design_principle: string | null;
  recommended_material_category: string | null;
  notes?: string | null;
}

export interface DesignStyle {
  name: string;
  style_family: string | null;
  description: string | null;
  suitable_layouts: string[];
  palette: string[];
  characteristics: Record<string, boolean>;
  tags: string[];
  score: number;
}

export interface DesignPayload {
  project_id: string;
  layout: string | null;
  area_sqm: string | null;
  space_planning: DesignSpace[];
  recommended_styles: DesignStyle[];
  recommended_palette: string[];
  suggested_material_categories: string[];
  assumptions: string[];
  confidence: number;
}

export interface ConstructionStage {
  stage: string;
  planned_days: number;
  actual_days: number | null;
  status: string | null;
  deviation_days: number | null;
}

export interface QualityDefect {
  category: string | null;
  item: string;
  severity: string | null;
  weight: number;
}

export interface ConstructionPayload {
  project_id: string;
  progress: {
    stages: ConstructionStage[];
    total_planned_days: number;
    total_actual_days: number;
    progress_ratio: number;
    delayed_stages: Array<{ stage: string; deviation_days: number; status?: string | null }>;
    at_risk: boolean;
  };
  quality: {
    items: Array<Record<string, unknown>>;
    score: number;
    defects: QualityDefect[];
    passed: boolean;
  };
  suggestions: string[];
  assumptions: string[];
  confidence: number;
}
