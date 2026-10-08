import type {
  ProjectCreate,
  ProjectDetail,
  ProjectMember,
  ProjectRole,
  ProjectSummary,
  ProjectUpdate,
} from "@/types/project";
import type { ApiClient } from "./client";

export function listProjects(client: ApiClient): Promise<ProjectSummary[]> {
  return client.getJson<ProjectSummary[]>("/v1/projects");
}

export function getProject(client: ApiClient, projectId: string): Promise<ProjectDetail> {
  return client.getJson<ProjectDetail>(`/v1/projects/${projectId}`);
}

export function createProject(client: ApiClient, payload: ProjectCreate): Promise<ProjectDetail> {
  return client.postJson<ProjectDetail>("/v1/projects", payload);
}

export function addProjectMember(
  client: ApiClient,
  projectId: string,
  payload: { user_id: string; role: ProjectRole },
): Promise<ProjectMember[]> {
  return client.postJson<ProjectMember[]>(`/v1/projects/${projectId}/members`, payload);
}

export function updateProject(
  client: ApiClient,
  projectId: string,
  payload: ProjectUpdate,
): Promise<ProjectDetail> {
  return client.putJson<ProjectDetail>(`/v1/projects/${projectId}`, payload);
}

export function deleteProject(client: ApiClient, projectId: string): Promise<void> {
  return client.delete(`/v1/projects/${projectId}`);
}
