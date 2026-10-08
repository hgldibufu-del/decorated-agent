import type { LoginRequest, TokenResponse, UserSummary } from "@/types/iam";
import type { ApiClient } from "./client";

export function login(client: ApiClient, credentials: LoginRequest): Promise<TokenResponse> {
  return client.postJson<TokenResponse>("/v1/auth/login", credentials);
}

export function fetchMe(client: ApiClient): Promise<UserSummary> {
  return client.getJson<UserSummary>("/v1/auth/me");
}
