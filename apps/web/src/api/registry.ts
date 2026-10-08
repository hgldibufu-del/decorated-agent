import type { AgentOut, SkillOut, ToolOut } from "@/types/agent";
import type { ApiClient } from "./client";

export function listAgents(client: ApiClient): Promise<AgentOut[]> {
  return client.getJson<AgentOut[]>("/v1/agents");
}

export function listSkills(client: ApiClient): Promise<SkillOut[]> {
  return client.getJson<SkillOut[]>("/v1/skills");
}

export function listTools(client: ApiClient): Promise<ToolOut[]> {
  return client.getJson<ToolOut[]>("/v1/tools");
}
