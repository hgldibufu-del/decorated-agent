import { defineStore } from "pinia";

import { ApiClient } from "@/api/client";
import { listRecentRuns, rememberRun, type RecentRun } from "@/api/history";
import {
  approveRun,
  createRun,
  getArtifact,
  getRun,
  getRunEvents,
  getRunToolCalls,
  listRuns,
  previewPlan,
  rejectRun,
  resumeRun,
} from "@/api/runs";
import type { ArtifactOut, RunEvent, RunOut, ToolCallOut } from "@/types/agent";
import type { Plan } from "@/types/supervisor";
import type { LoadState } from "@/types/ui";

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);
const POLL_INTERVAL_MS = 1000;

/** Run 是否已到终态（终态后无需继续轮询）。 */
export function isRunTerminal(status: string): boolean {
  return TERMINAL_STATUSES.has(status);
}

interface WorkbenchState {
  objective: string;
  projectId: string | null;
  plan: Plan | null;
  run: RunOut | null;
  events: RunEvent[];
  toolCalls: ToolCallOut[];
  artifacts: ArtifactOut[];
  recent: RecentRun[];
  state: LoadState;
  planState: LoadState;
  actionState: LoadState;
  errorMessage: string | null;
  errorCode: string | null;
  retryable: boolean;
  permissionDenied: boolean;
  polling: boolean;
  pollTimer: ReturnType<typeof setInterval> | null;
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export const useWorkbenchStore = defineStore("workbench", {
  state: (): WorkbenchState => ({
    objective: "",
    projectId: null,
    plan: null,
    run: null,
    events: [],
    toolCalls: [],
    artifacts: [],
    recent: listRecentRuns(),
    state: "idle",
    planState: "idle",
    actionState: "idle",
    errorMessage: null,
    errorCode: null,
    retryable: false,
    permissionDenied: false,
    polling: false,
    pollTimer: null as ReturnType<typeof setInterval> | null,
  }),

  getters: {
    isBusy: (state): boolean => state.actionState === "loading" || state.planState === "loading",
    hasRun: (state): boolean => state.run !== null,
    canExecute: (state): boolean => state.objective.trim().length > 0,
    isAwaitingApproval: (state): boolean => state.run?.status === "awaiting_approval",
  },

  actions: {
    reset(): void {
      this.objective = "";
      this.projectId = null;
      this.plan = null;
      this.run = null;
      this.events = [];
      this.toolCalls = [];
      this.artifacts = [];
      this.state = "idle";
      this.planState = "idle";
      this.actionState = "idle";
      this.errorMessage = null;
      this.errorCode = null;
      this.retryable = false;
      this.permissionDenied = false;
    },

    refreshRecent(): void {
      this.recent = listRecentRuns();
    },

    async preview(client: ApiClient = new ApiClient()): Promise<void> {
      this.planState = "loading";
      this.errorMessage = null;
      this.errorCode = null;
      this.permissionDenied = false;
      try {
        this.plan = await previewPlan(client, this.objective, this.projectId);
        this.planState = "ready";
      } catch (error) {
        this.plan = null;
        this.planState = "error";
        this.applyError(error);
      }
    },

    async execute(client: ApiClient = new ApiClient()): Promise<void> {
      this.actionState = "loading";
      this.errorMessage = null;
      this.errorCode = null;
      this.permissionDenied = false;
      try {
        // 未先预览时自动补一次规划，保证 Run 一定带合法 intent
        if (!this.plan) {
          this.plan = await previewPlan(client, this.objective, this.projectId);
        }
        const run = await createRun(client, {
          intent: this.plan.intent,
          objective: this.objective,
          project_id: this.projectId ?? undefined,
        });
        await this.hydrate(run, client);
        this.recent = rememberRun({
          id: run.id,
          objective: run.objective,
          intent: this.plan?.intent ?? null,
          status: run.status,
          project_id: run.project_id,
          at: run.created_at,
        });
        // 尽力而为：后端可用时以后端权威列表为准（含本 Run），失败则保留本地记录
        await this.loadRecent(client);
        this.startPolling(client);
        this.actionState = "ready";
      } catch (error) {
        this.actionState = "error";
        this.applyError(error);
      }
    },

    async openRun(runId: string, client: ApiClient = new ApiClient()): Promise<void> {
      this.state = "loading";
      this.errorMessage = null;
      this.errorCode = null;
      this.permissionDenied = false;
      try {
        const run = await getRun(client, runId);
        await this.hydrate(run, client);
        this.startPolling(client);
        this.state = "ready";
      } catch (error) {
        this.state = "error";
        this.run = null;
        this.applyError(error);
      }
    },

    async approve(client: ApiClient = new ApiClient()): Promise<void> {
      if (!this.run?.approval_id) return;
      this.actionState = "loading";
      try {
        await approveRun(client, this.run.approval_id, null);
        const run = await resumeRun(client, this.run.id);
        await this.hydrate(run, client);
        this.actionState = "ready";
      } catch (error) {
        this.actionState = "error";
        this.applyError(error);
      }
    },

    async reject(client: ApiClient = new ApiClient()): Promise<void> {
      if (!this.run?.approval_id) return;
      this.actionState = "loading";
      try {
        await rejectRun(client, this.run.approval_id, null);
        const run = await getRun(client, this.run.id);
        await this.hydrate(run, client);
        this.actionState = "ready";
      } catch (error) {
        this.actionState = "error";
        this.applyError(error);
      }
    },

    /** 拉齐一个 Run 的全部展示数据（详情 + 时间线 + 工具调用 + Artifact）。 */
    async hydrate(run: RunOut, client: ApiClient): Promise<void> {
      const [events, toolCalls, artifacts] = await Promise.all([
        getRunEvents(client, run.id),
        getRunToolCalls(client, run.id),
        Promise.all(run.artifact_ids.map((id) => getArtifact(client, id))),
      ]);
      this.run = run;
      this.events = events;
      this.toolCalls = toolCalls;
      this.artifacts = artifacts;
      if (isRunTerminal(run.status)) {
        this.stopPolling();
      }
    },

    /** 从后端拉取最近 Run（后端不可用时回退本地记录）。 */
    async loadRecent(client: ApiClient = new ApiClient()): Promise<void> {
      try {
        const runs = await listRuns(client, 20);
        this.recent = runs.map((run) => ({
          id: run.id,
          objective: run.objective,
          intent: null,
          status: run.status,
          project_id: run.project_id,
          at: run.created_at,
        }));
      } catch {
        this.recent = listRecentRuns();
      }
    },

    /** 非终态 Run 每秒轮询一次事件，终态自动停止（同步执行下主要覆盖审批往返窗口）。 */
    startPolling(client: ApiClient = new ApiClient()): void {
      if (this.polling || !this.run || isRunTerminal(this.run.status)) return;
      this.polling = true;
      this.pollTimer = setInterval(() => {
        void this.pollOnce(client);
      }, POLL_INTERVAL_MS);
    },

    stopPolling(): void {
      if (this.pollTimer !== null) {
        clearInterval(this.pollTimer);
        this.pollTimer = null;
      }
      this.polling = false;
    },

    async pollOnce(client: ApiClient = new ApiClient()): Promise<void> {
      if (!this.run) {
        this.stopPolling();
        return;
      }
      try {
        const run = await getRun(client, this.run.id);
        this.run = run;
        this.events = await getRunEvents(client, run.id);
        this.toolCalls = await getRunToolCalls(client, run.id);
        if (isRunTerminal(run.status)) {
          this.stopPolling();
        }
      } catch {
        this.stopPolling();
      }
    },

    applyError(error: unknown): void {
      this.errorCode = (error as { code?: string }).code ?? "UNKNOWN";
      this.errorMessage = messageOf(error);
      this.retryable = Boolean((error as { retryable?: boolean }).retryable);
      this.permissionDenied = Boolean((error as { isPermissionDenied?: boolean }).isPermissionDenied);
    },
  },
});
