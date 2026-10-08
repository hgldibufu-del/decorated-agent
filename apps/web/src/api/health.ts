import type { HealthReport } from "@/types/health";
import type { ApiClient } from "./client";

export const HEALTH_PATH = "/v1/health";
export const READINESS_PATH = "/v1/ready";
export const LIVENESS_PATH = "/v1/live";

export function fetchHealth(client: ApiClient): Promise<HealthReport> {
  return client.getJson<HealthReport>(HEALTH_PATH);
}

export function fetchReadiness(client: ApiClient): Promise<HealthReport> {
  return client.getJson<HealthReport>(READINESS_PATH);
}

export function fetchLiveness(client: ApiClient): Promise<{ status: string }> {
  return client.getJson<{ status: string }>(LIVENESS_PATH);
}
