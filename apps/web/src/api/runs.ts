import type {
  ApprovalOut,
  ArtifactOut,
  RunCreateRequest,
  RunEvent,
  RunOut,
  ToolCallOut,
} from "@/types/agent";
import type { Plan } from "@/types/supervisor";
import type { ApiClient } from "./client";

export function previewPlan(
  client: ApiClient,
  message: string,
  projectId: string | null,
): Promise<Plan> {
  return client.postJson<Plan>("/v1/runs/plan", {
    message,
    project_id: projectId,
  });
}

export function listRuns(client: ApiClient, limit = 20): Promise<RunOut[]> {
  return client.getJson<RunOut[]>(`/v1/runs?limit=${limit}`);
}

export function createRun(client: ApiClient, payload: RunCreateRequest): Promise<RunOut> {
  return client.postJson<RunOut>("/v1/runs", payload);
}

export function getRun(client: ApiClient, runId: string): Promise<RunOut> {
  return client.getJson<RunOut>(`/v1/runs/${runId}`);
}

export function getRunEvents(client: ApiClient, runId: string): Promise<RunEvent[]> {
  return client.getJson<RunEvent[]>(`/v1/runs/${runId}/events`);
}

export function getRunToolCalls(client: ApiClient, runId: string): Promise<ToolCallOut[]> {
  return client.getJson<ToolCallOut[]>(`/v1/runs/${runId}/tool-calls`);
}

export function getArtifact(client: ApiClient, artifactId: string): Promise<ArtifactOut> {
  return client.getJson<ArtifactOut>(`/v1/artifacts/${artifactId}`);
}

export function approveRun(
  client: ApiClient,
  approvalId: string,
  comment: string | null,
): Promise<ApprovalOut> {
  return client.postJson<ApprovalOut>(`/v1/approvals/${approvalId}/approve`, {
    decision: "approve",
    comment,
  });
}

export function rejectRun(
  client: ApiClient,
  approvalId: string,
  comment: string | null,
): Promise<ApprovalOut> {
  return client.postJson<ApprovalOut>(`/v1/approvals/${approvalId}/reject`, {
    decision: "reject",
    comment,
  });
}

export function resumeRun(client: ApiClient, runId: string): Promise<RunOut> {
  return client.postJson<RunOut>(`/v1/runs/${runId}/resume`, {});
}
