import { defineStore } from "pinia";

import { ApiClient } from "@/api/client";
import { fetchHealth } from "@/api/health";
import type { HealthReport } from "@/types/health";

/**
 * 页面状态机必须覆盖需求文档 §19 列出的全部状态，不能只做 happy path：
 * idle → loading → ready | error，其中 error 还要区分「无权限」与「后端故障」。
 */
export type LoadState = "idle" | "loading" | "ready" | "error";

export interface SystemState {
  report: HealthReport | null;
  state: LoadState;
  lastUpdatedAt: string | null;
  errorMessage: string | null;
  errorCode: string | null;
  retryable: boolean;
  permissionDenied: boolean;
}

export const useSystemStore = defineStore("system", {
  state: (): SystemState => ({
    report: null,
    state: "idle",
    lastUpdatedAt: null,
    errorMessage: null,
    errorCode: null,
    retryable: false,
    permissionDenied: false,
  }),

  getters: {
    components: (state): HealthReport["components"] => state.report?.components ?? [],
    isLoading: (state): boolean => state.state === "loading",
    isEmpty: (state): boolean =>
      state.state === "ready" && (state.report?.components.length ?? 0) === 0,
    hasError: (state): boolean => state.state === "error",
  },

  actions: {
    async load(client: ApiClient = new ApiClient()): Promise<void> {
      this.state = "loading";
      this.errorMessage = null;
      this.errorCode = null;
      this.retryable = false;
      this.permissionDenied = false;
      try {
        this.report = await fetchHealth(client);
        this.state = "ready";
        this.lastUpdatedAt = new Date().toISOString();
      } catch (error) {
        this.report = null;
        this.state = "error";
        this.permissionDenied = Boolean(
          error && (error as { isPermissionDenied?: boolean }).isPermissionDenied,
        );
        this.errorCode = (error as { code?: string }).code ?? "UNKNOWN";
        this.errorMessage = error instanceof Error ? error.message : String(error);
        this.retryable = Boolean((error as { retryable?: boolean }).retryable);
      }
    },
  },
});
