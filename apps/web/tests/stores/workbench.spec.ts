import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import { clearRecentRuns, rememberRun } from "@/api/history";
import { isRunTerminal, useWorkbenchStore } from "@/stores/workbench";
import type { ArtifactOut, RunOut } from "@/types/agent";
import type { Plan } from "@/types/supervisor";
import { makeFakeClient } from "../helpers/fake-client";

const PLAN: Plan = {
  intent: "quote_estimate",
  mode: "direct",
  rationale: "报价估算意图",
  steps: [
    {
      task_key: "T-001",
      agent_id: "quote_agent",
      skill_id: "quote_estimate",
      objective: "报价",
      depends_on: [],
      input: {},
    },
  ],
};

const RUN: RunOut = {
  id: "run-1",
  project_id: "p-1",
  status: "completed",
  mode: "direct",
  objective: "报价",
  error: null,
  created_at: "2026-10-05T10:00:00Z",
  finished_at: "2026-10-05T10:00:01Z",
  tasks: [],
  artifact_ids: ["art-1"],
  approval_id: null,
  review_decision: "PASS",
  review_issues: [],
};

const ARTIFACT: ArtifactOut = {
  id: "art-1",
  run_id: "run-1",
  artifact_type: "quote_estimate",
  producer: "quote_estimate",
  payload: { estimate: { total: "156000.00" } },
  version: 1,
  created_at: "2026-10-05T10:00:01Z",
};

function routes(run: RunOut) {
  return {
    "POST /v1/runs/plan": () => PLAN,
    "POST /v1/runs": () => run,
    [`GET /v1/runs/${run.id}`]: () => run,
    [`GET /v1/runs/${run.id}/events`]: () => [],
    [`GET /v1/runs/${run.id}/tool-calls`]: () => [],
    "GET /v1/artifacts/art-1": () => ARTIFACT,
  };
}

describe("useWorkbenchStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    clearRecentRuns();
  });

  it("preview 拉取计划", async () => {
    const store = useWorkbenchStore();
    store.objective = "报价";

    await store.preview(makeFakeClient(routes(RUN)));

    expect(store.plan?.intent).toBe("quote_estimate");
    expect(store.planState).toBe("ready");
  });

  it("execute 自动补规划、跑 Run、聚合 Artifact 并记入本地历史", async () => {
    const store = useWorkbenchStore();
    store.objective = "报价";
    store.projectId = "p-1";

    await store.execute(makeFakeClient(routes(RUN)));

    expect(store.plan?.intent).toBe("quote_estimate");
    expect(store.run?.id).toBe("run-1");
    expect(store.artifacts).toHaveLength(1);
    expect(store.recent[0]?.id).toBe("run-1");
    expect(store.actionState).toBe("ready");
  });

  it("openRun 按 id 拉齐详情并刷新历史", async () => {
    const store = useWorkbenchStore();

    await store.openRun("run-1", makeFakeClient(routes(RUN)));

    expect(store.run?.id).toBe("run-1");
    expect(store.state).toBe("ready");
    expect(store.artifacts[0]?.artifact_type).toBe("quote_estimate");
  });

  it("awaiting_approval 时 approve → resume 后刷新为终态", async () => {
    const store = useWorkbenchStore();
    const pending: RunOut = { ...RUN, status: "awaiting_approval", approval_id: "ap-1" };
    store.$patch({ run: pending });

    const client = makeFakeClient({
      ...routes(RUN),
      "POST /v1/approvals/ap-1/approve": () => ({ id: "ap-1", status: "approved" }),
      "POST /v1/runs/run-1/resume": () => RUN,
    });

    await store.approve(client);

    expect(store.run?.status).toBe("completed");
  });

  it("reject 后重新拉取 Run 变为 failed", async () => {
    const store = useWorkbenchStore();
    const failed: RunOut = { ...RUN, status: "failed", error: "审批被拒绝", approval_id: null };
    store.$patch({ run: { ...RUN, status: "awaiting_approval", approval_id: "ap-1" } });

    const client = makeFakeClient({
      ...routes(failed),
      "POST /v1/approvals/ap-1/reject": () => ({ id: "ap-1", status: "rejected" }),
    });

    await store.reject(client);

    expect(store.run?.status).toBe("failed");
  });

  it("loadRecent 用后端列表作为权威历史", async () => {
    const store = useWorkbenchStore();
    const client = makeFakeClient({ "GET /v1/runs?limit=20": () => [RUN] });

    await store.loadRecent(client);

    expect(store.recent[0]?.id).toBe("run-1");
    expect(store.recent[0]?.status).toBe("completed");
  });

  it("loadRecent 后端不可用时回退本地记录", async () => {
    rememberRun({
      id: "local-1",
      objective: "本地记录",
      intent: null,
      status: "completed",
      project_id: null,
      at: "2026-10-05T10:00:00Z",
    });
    const store = useWorkbenchStore();
    const client = makeFakeClient({
      "GET /v1/runs?limit=20": () => Promise.reject({ code: "NETWORK_ERROR" }),
    });

    await store.loadRecent(client);

    expect(store.recent.some((entry) => entry.id === "local-1")).toBe(true);
  });

  it("isRunTerminal 判定终态", () => {
    expect(isRunTerminal("completed")).toBe(true);
    expect(isRunTerminal("failed")).toBe(true);
    expect(isRunTerminal("awaiting_approval")).toBe(false);
    expect(isRunTerminal("running")).toBe(false);
  });

  it("终态 Run 不启动轮询", () => {
    const store = useWorkbenchStore();
    store.$patch({ run: RUN });
    store.startPolling(makeFakeClient({}));

    expect(store.polling).toBe(false);
  });

  it("非终态 Run 启动轮询，stopPolling 可停止", () => {
    const store = useWorkbenchStore();
    store.$patch({ run: { ...RUN, status: "awaiting_approval" } });

    store.startPolling(makeFakeClient({}));
    expect(store.polling).toBe(true);

    store.stopPolling();
    expect(store.polling).toBe(false);
  });

  it("pollOnce 拉到终态后自动停止轮询", async () => {
    const store = useWorkbenchStore();
    store.$patch({ run: { ...RUN, status: "awaiting_approval" }, polling: true });
    const client = makeFakeClient({
      "GET /v1/runs/run-1": () => RUN,
      "GET /v1/runs/run-1/events": () => [],
      "GET /v1/runs/run-1/tool-calls": () => [],
    });

    await store.pollOnce(client);

    expect(store.run?.status).toBe("completed");
    expect(store.polling).toBe(false);
  });
});
