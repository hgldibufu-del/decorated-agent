import { defineStore } from "pinia";

import { ApiClient } from "@/api/client";
import { listAgents, listSkills, listTools } from "@/api/registry";
import type { AgentOut, SkillOut, ToolOut } from "@/types/agent";
import type { LoadState } from "@/types/ui";

interface RegistryState {
  agents: AgentOut[];
  skills: SkillOut[];
  tools: ToolOut[];
  state: LoadState;
  errorMessage: string | null;
  errorCode: string | null;
  retryable: boolean;
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export const useRegistryStore = defineStore("registry", {
  state: (): RegistryState => ({
    agents: [],
    skills: [],
    tools: [],
    state: "idle",
    errorMessage: null,
    errorCode: null,
    retryable: false,
  }),

  getters: {
    isLoading: (state): boolean => state.state === "loading",
  },

  actions: {
    async load(client: ApiClient = new ApiClient()): Promise<void> {
      this.state = "loading";
      this.errorMessage = null;
      this.errorCode = null;
      this.retryable = false;
      try {
        const [agents, skills, tools] = await Promise.all([
          listAgents(client),
          listSkills(client),
          listTools(client),
        ]);
        this.agents = agents;
        this.skills = skills;
        this.tools = tools;
        this.state = "ready";
      } catch (error) {
        this.agents = [];
        this.skills = [];
        this.tools = [];
        this.state = "error";
        this.errorCode = (error as { code?: string }).code ?? "UNKNOWN";
        this.errorMessage = messageOf(error);
        this.retryable = Boolean((error as { retryable?: boolean }).retryable);
      }
    },
  },
});
