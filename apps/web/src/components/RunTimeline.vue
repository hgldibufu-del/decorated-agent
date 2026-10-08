<script setup lang="ts">
import { formatDateTime } from "@/utils/format";
import type { RunEvent } from "@/types/agent";

const props = defineProps<{ events: RunEvent[] }>();

const KIND_LABEL: Record<string, string> = {
  run: "Run",
  task: "Task",
  tool_call: "Tool",
};

const TONE: Record<string, string> = {
  completed: "border-emerald-500/30 text-emerald-300",
  success: "border-emerald-500/30 text-emerald-300",
  running: "border-sky-500/30 text-sky-300",
  pending: "border-surface-line text-slate-400",
  failed: "border-rose-500/30 text-rose-300",
  timeout: "border-amber-500/30 text-amber-300",
  denied: "border-amber-500/30 text-amber-300",
  awaiting_approval: "border-amber-500/30 text-amber-300",
};
</script>

<template>
  <article class="panel" data-testid="run-timeline">
    <header class="panel-title">执行时间线</header>
    <ul class="divide-y divide-surface-line">
      <li
        v-for="(event, index) in props.events"
        :key="index"
        class="flex items-center justify-between gap-3 px-4 py-2"
        data-testid="timeline-item"
      >
        <div class="flex items-center gap-2">
          <span class="tag">{{ KIND_LABEL[event.kind] ?? event.kind }}</span>
          <span class="font-mono text-xs text-slate-300">{{ event.summary }}</span>
        </div>
        <div class="flex items-center gap-3">
          <span
            class="rounded border px-2 py-0.5 text-xs"
            :class="TONE[event.status] ?? 'border-surface-line text-slate-400'"
          >
            {{ event.status }}
          </span>
          <span class="text-xs text-slate-600">{{ formatDateTime(event.at) }}</span>
        </div>
      </li>
      <li v-if="!props.events.length" class="px-4 py-3 text-xs text-slate-600">暂无事件</li>
    </ul>
  </article>
</template>
