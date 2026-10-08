<script setup lang="ts">
import { computed } from "vue";

import { formatPercent } from "@/utils/format";
import type { AftersalesPayload } from "@/types/artifact";

const props = defineProps<{ payload: AftersalesPayload }>();

const chunkText = computed<string[]>(() =>
  (props.payload.evidence ?? []).map((chunk) =>
    typeof chunk.content === "string" ? chunk.content : JSON.stringify(chunk),
  ),
);
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <span class="tag">根因假设：{{ props.payload.hypothesis }}</span>
      <span class="tag">置信度 {{ formatPercent(props.payload.confidence) }}</span>
    </div>

    <div v-if="props.payload.suggested_actions?.length">
      <h4 class="mb-1 text-xs font-semibold text-slate-400">处置建议</h4>
      <ul class="list-disc space-y-1 pl-5 text-xs text-slate-300">
        <li v-for="(action, index) in props.payload.suggested_actions" :key="index">{{ action }}</li>
      </ul>
    </div>

    <div v-if="chunkText.length">
      <h4 class="mb-1 text-xs font-semibold text-slate-400">检索证据</h4>
      <ul class="space-y-1">
        <li
          v-for="(content, index) in chunkText"
          :key="index"
          class="rounded border border-surface-line bg-surface px-3 py-2 text-xs text-slate-400"
        >
          {{ content }}
        </li>
      </ul>
    </div>

    <div v-if="props.payload.similar_cases?.length">
      <h4 class="mb-1 text-xs font-semibold text-slate-400">
        相似历史案例（{{ props.payload.similar_cases.length }}）
      </h4>
      <pre class="overflow-x-auto rounded border border-surface-line bg-surface p-3 font-mono text-xs text-slate-500">{{ JSON.stringify(props.payload.similar_cases, null, 2) }}</pre>
    </div>
  </div>
</template>
