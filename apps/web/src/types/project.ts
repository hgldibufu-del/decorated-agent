/** 项目域契约镜像 —— 对应 `dw_schemas.project`。 */

export type ProjectStatus = "draft" | "active" | "on_hold" | "completed" | "cancelled";
export type ProjectRole = "owner" | "manager" | "member" | "viewer";

export interface Customer {
  id: string;
  name: string;
  phone: string;
  email: string | null;
  note: string | null;
  created_at: string;
}

export interface House {
  id: string;
  customer_id: string;
  address: string;
  city: string | null;
  area_sqm: string | null;
  layout: string | null;
  note: string | null;
}

export interface ProjectMember {
  project_id: string;
  user_id: string;
  role: ProjectRole;
  email: string;
  full_name: string;
  joined_at: string;
}

export interface ProjectSummary {
  id: string;
  code: string;
  name: string;
  status: ProjectStatus;
  customer_name: string;
  house_address: string;
  member_role: ProjectRole | null;
  created_at: string;
}

export interface CustomerCreate {
  name: string;
  phone: string;
  email?: string | null;
  note?: string | null;
}

export interface CustomerUpdate {
  name?: string;
  phone?: string;
  email?: string | null;
  note?: string | null;
}

export interface HouseUpdate {
  address?: string;
  city?: string | null;
  area_sqm?: string | null;
  layout?: string | null;
  note?: string | null;
}

export interface ProjectUpdate {
  version: number;
  name?: string;
  status?: ProjectStatus;
  budget_amount?: string | null;
  planned_start_date?: string | null;
  planned_complete_date?: string | null;
  note?: string | null;
}

export interface HouseCreate {
  customer_id: string;
  address: string;
  city?: string | null;
  area_sqm?: string | null;
  layout?: string | null;
  note?: string | null;
}

export interface ProjectCreate {
  code: string;
  name: string;
  customer_id: string;
  house_id: string;
  status?: ProjectStatus;
  budget_amount?: string | null;
  note?: string | null;
}

export interface ProjectDetail {
  id: string;
  code: string;
  name: string;
  status: ProjectStatus;
  customer_id: string;
  house_id: string;
  budget_amount: string | null;
  planned_start_date: string | null;
  planned_complete_date: string | null;
  note: string | null;
  created_at: string;
  updated_at: string;
  /** 乐观锁令牌：编辑时须原样回传。 */
  version: number;
  customer: Customer;
  house: House;
  members: ProjectMember[];
}
