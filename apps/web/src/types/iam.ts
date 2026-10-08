/** 身份契约镜像 —— 对应 `dw_schemas.iam`。 */

export type RoleName =
  | "admin"
  | "project_manager"
  | "designer"
  | "estimator"
  | "construction_manager"
  | "aftersales"
  | "viewer";

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface UserSummary {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  roles: RoleName[];
  permissions: string[];
}

export interface LoginRequest {
  email: string;
  password: string;
}

/** 成员候选最小信息（对应后端 `UserBrief`）。 */
export interface UserBrief {
  id: string;
  email: string;
  full_name: string;
}
