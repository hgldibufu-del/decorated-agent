<script setup lang="ts">
import { formatDeviation, formatPercent } from "@/utils/format";
import type { ConstructionPayload } from "@/types/artifact";

const props = defineProps<{ payload: ConstructionPayload }>();

const STATUS_LABEL: Record<string, string> = {
  completed: "已完成",
  in_progress: "进行中",
  pending: "未开始",
};
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <span
        class="tag"
        :class="props.payload.progress.at_risk ? 'border-rose-500/40 text-rose-300' : 'border-emerald-500/40 text-emerald-300'"
      >
        {{ props.payload.progress.at_risk ? "存在延期风险" : "进度可控" }}
      </span>
      <span class="tag">完成度 {{ formatPercent(props.payload.progress.progress_ratio) }}</span>
      <span class="tag">
        计划 {{ props.payload.progress.total_planned_days }} 天 · 实际
        {{ props.payload.progress.total_actual_days }} 天
      </span>
      <span class="tag">验收得分 {{ formatPercent(props.payload.quality.score) }}</span>
    </div>

    <div>
      <h4 class="mb-1 text-xs font-semibold text-slate-400">施工阶段</h4>
      <table class="w-full">
        <thead>
          <tr class="border-b border-surface-line">
            <th class="th text-left">阶段</th>
            <th class="th text-left">状态</th>
            <th class="th text-right">计划</th>
            <th class="th text-right">实际</th>
            <th class="th text-right">偏差</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(stage, index) in props.payload.progress.stages"
            :key="index"
            class="border-b border-surface-line/60"
          >
            <td class="td">{{ stage.stage }}</td>
            <td class="td text-slate-500">{{ STATUS_LABEL[stage.status ?? ""] ?? stage.status ?? "-" }}</td>
            <td class="td text-right font-mono">{{ stage.planned_days }} 天</td>
            <td class="td text-right font-mono">{{ stage.actual_days ?? "-" }}</td>
            <td
              class="td text-right font-mono"
              :class="(stage.deviation_days ?? 0) > 0 ? 'text-rose-300' : ''"
            >
              {{ formatDeviation(stage.deviation_days) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="props.payload.quality.defects?.length">
      <h4 class="mb-1 text-xs font-semibold text-slate-400">验收缺陷</h4>
      <ul class="space-y-1">
        <li
          v-for="(defect, index) in props.payload.quality.defects"
          :key="index"
          class="rounded border border-rose-500/20 bg-rose-500/5 px-3 py-2 text-xs text-rose-200"
        >
          [{{ defect.severity ?? "-" }}] {{ defect.category ?? "-" }} · {{ defect.item }}
        </li>
      </ul>
    </div>

    <div v-if="props.payload.suggestions?.length">
      <h4 class="mb-1 text-xs font-semibold text-slate-400">建议</h4>
      <ul class="list-disc space-y-1 pl-5 text-xs text-slate-300">
        <li v-for="(tip, index) in props.payload.suggestions" :key="index">{{ tip }}</li>
      </ul>
    </div>
  </div>
</template>
