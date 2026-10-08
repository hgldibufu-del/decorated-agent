<script setup lang="ts">
import { computed, onMounted, onUnmounted } from "vue";

import ArtifactView from "@/components/artifact/ArtifactView.vue";
import PlanPreview from "@/components/PlanPreview.vue";
import RunTimeline from "@/components/RunTimeline.vue";
import StatePanel from "@/components/StatePanel.vue";
import { useProjectsStore } from "@/stores/projects";
import { useWorkbenchStore } from "@/stores/workbench";
import type { PanelState } from "@/types/ui";
import { formatDateTime } from "@/utils/format";

const projects = useProjectsStore();
const wb = useWorkbenchStore();

const RUN_STATUS_TONE: Record<string, string> = {
  completed: "border-emerald-500/30 text-emerald-300",
  failed: "border-rose-500/30 text-rose-300",
  awaiting_approval: "border-amber-500/30 text-amber-300",
  running: "border-sky-500/30 text-sky-300",
  pending: "border-surface-line text-slate-400",
  cancelled: "border-surface-line text-slate-400",
};

const errorState = computed<PanelState>(() => {
  const failed = wb.actionState === "error" || wb.state === "error" || wb.planState === "error";
  if (!failed) return "ready";
  return wb.permissionDenied ? "permission" : "error";
});

const hasError = computed(
  () => wb.actionState === "error" || wb.state === "error" || wb.planState === "error",
);

onMounted(async () => {
  await wb.loadRecent();
  if (projects.state === "idle") {
    await projects.load();
  }
});

onUnmounted(() => {
  wb.stopPolling();
});

function retry(): void {
  if (wb.planState === "error") {
    void wb.preview();
  } else {
    void wb.execute();
  }
}
</script>

<template>
  <section class="space-y-6">
    <header>
      <h2 class="text-lg font-semibold text-slate-100">AI 工作台</h2>
      <p class="mt-1 text-xs text-slate-500">
        用自然语言描述诉求，Supervisor 先出计划、再调度 Specialist 执行，产出可追溯的 Artifact。
      </p>
    </header>

    <div class="panel p-4">
      <div class="grid gap-3 md:grid-cols-[1fr_240px]">
        <label class="block text-xs text-slate-400">
          诉求
          <textarea
            v-model="wb.objective"
            rows="2"
            class="input mt-1"
            placeholder="例如：这套房做现代简约风格的整装报价"
            data-testid="objective-input"
          />
        </label>
        <label class="block text-xs text-slate-400">
          项目
          <select v-model="wb.projectId" class="input mt-1" data-testid="project-select">
            <option :value="null">（不指定项目）</option>
            <option v-for="item in projects.items" :key="item.id" :value="item.id">
              {{ item.code }} · {{ item.name }}
            </option>
          </select>
        </label>
      </div>

      <div class="mt-3 flex items-center gap-2">
        <button
          type="button"
          class="btn"
          :disabled="!wb.canExecute || wb.isBusy"
          data-testid="preview-button"
          @click="wb.preview()"
        >
          预览计划
        </button>
        <button
          type="button"
          class="btn btn-primary"
          :disabled="!wb.canExecute || wb.isBusy"
          data-testid="execute-button"
          @click="wb.execute()"
        >
          {{ wb.actionState === "loading" ? "执行中…" : "执行" }}
        </button>
        <span v-if="wb.isBusy" class="text-xs text-slate-500">处理中…</span>
        <span
          v-if="wb.polling"
          class="text-xs text-sky-300"
          data-testid="polling-indicator"
        >
          实时刷新中…
        </span>
      </div>
    </div>

    <StatePanel
      v-if="hasError"
      :state="errorState"
      :message="wb.errorMessage"
      :code="wb.errorCode"
      :retryable="wb.retryable"
      @retry="retry"
    />

    <PlanPreview v-if="wb.plan" :plan="wb.plan" />

    <template v-if="wb.run">
      <article class="panel" data-testid="run-summary">
        <header class="panel-title flex items-center justify-between">
          <span>执行结果</span>
          <span
            class="rounded border px-2 py-0.5 text-xs"
            :class="RUN_STATUS_TONE[wb.run.status] ?? 'border-surface-line text-slate-400'"
            data-testid="run-status"
          >
            {{ wb.run.status }}
          </span>
        </header>
        <div class="space-y-3 p-4">
          <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span class="tag">模式 {{ wb.run.mode }}</span>
            <span class="tag">发起 {{ formatDateTime(wb.run.created_at) }}</span>
            <span v-if="wb.run.review_decision" class="tag">
              Reviewer {{ wb.run.review_decision }}
            </span>
          </div>

          <ul v-if="wb.run.review_issues.length" class="list-disc space-y-1 pl-5 text-xs text-amber-300">
            <li v-for="(issue, index) in wb.run.review_issues" :key="index">{{ issue }}</li>
          </ul>

          <table class="w-full">
            <thead>
              <tr class="border-b border-surface-line">
                <th class="th text-left">任务</th>
                <th class="th text-left">Agent · Skill</th>
                <th class="th text-left">状态</th>
                <th class="th text-right">尝试</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="task in wb.run.tasks"
                :key="task.id"
                class="border-b border-surface-line/60"
              >
                <td class="td font-mono">{{ task.task_key }}</td>
                <td class="td">{{ task.agent_id }} · {{ task.skill_id }}</td>
                <td class="td text-slate-500">{{ task.status }}</td>
                <td class="td text-right font-mono">{{ task.attempt }}</td>
              </tr>
            </tbody>
          </table>

          <div v-if="wb.isAwaitingApproval" class="flex items-center gap-2" data-testid="approval-actions">
            <span class="text-xs text-amber-300">该 Run 等待人工审批：</span>
            <button type="button" class="btn btn-primary" :disabled="wb.isBusy" @click="wb.approve()">
              通过并恢复
            </button>
            <button type="button" class="btn" :disabled="wb.isBusy" @click="wb.reject()">拒绝</button>
          </div>
        </div>
      </article>

      <div v-if="wb.artifacts.length" class="space-y-4">
        <ArtifactView v-for="artifact in wb.artifacts" :key="artifact.id" :artifact="artifact" />
      </div>

      <RunTimeline :events="wb.events" />

      <article v-if="wb.toolCalls.length" class="panel" data-testid="tool-calls">
        <header class="panel-title">工具调用明细</header>
        <table class="w-full">
          <thead>
            <tr class="border-b border-surface-line">
              <th class="th text-left">工具</th>
              <th class="th text-left">状态</th>
              <th class="th text-right">尝试</th>
              <th class="th text-right">耗时</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="call in wb.toolCalls"
              :key="call.id"
              class="border-b border-surface-line/60"
            >
              <td class="td font-mono">{{ call.tool_id }}</td>
              <td class="td text-slate-500">{{ call.status }}</td>
              <td class="td text-right font-mono">{{ call.attempt }}</td>
              <td class="td text-right font-mono">{{ call.duration_ms }} ms</td>
            </tr>
          </tbody>
        </table>
      </article>
    </template>

    <article v-if="wb.recent.length" class="panel">
      <header class="panel-title">运行历史（本地）</header>
      <ul class="divide-y divide-surface-line">
        <li
          v-for="entry in wb.recent"
          :key="entry.id"
          class="flex cursor-pointer items-center justify-between gap-3 px-4 py-2 hover:bg-surface-line/40"
          data-testid="recent-run"
          @click="wb.openRun(entry.id)"
        >
          <span class="truncate text-xs text-slate-300">{{ entry.objective }}</span>
          <span class="flex shrink-0 items-center gap-3 text-xs text-slate-500">
            <span>{{ entry.intent ?? "-" }}</span>
            <span>{{ entry.status }}</span>
            <span>{{ formatDateTime(entry.at) }}</span>
          </span>
        </li>
      </ul>
    </article>
  </section>
</template>
