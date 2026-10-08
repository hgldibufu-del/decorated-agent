<script setup lang="ts">
import { computed } from "vue";

import { INTENT_LABELS, type Plan } from "@/types/supervisor";

const props = defineProps<{ plan: Plan }>();

const intentLabel = computed(() => INTENT_LABELS[props.plan.intent] ?? props.plan.intent);
</script>

<template>
  <article class="panel" data-testid="plan-preview">
    <header class="panel-title flex items-center justify-between">
      <span>执行计划</span>
      <span class="text-xs text-slate-500">
        意图 {{ intentLabel }} · 模式 {{ props.plan.mode }}
      </span>
    </header>
    <div class="space-y-3 p-4">
      <p v-if="props.plan.rationale" class="text-xs text-slate-500">{{ props.plan.rationale }}</p>

      <ol class="space-y-2">
        <li
          v-for="step in props.plan.steps"
          :key="step.task_key"
          class="rounded border border-surface-line bg-surface p-3"
          data-testid="plan-step"
        >
          <div class="flex items-center justify-between">
            <span class="font-mono text-xs text-slate-400">{{ step.task_key }}</span>
            <span class="tag">{{ step.agent_id }} · {{ step.skill_id }}</span>
          </div>
          <p class="mt-1 text-xs text-slate-300">{{ step.objective }}</p>
          <p v-if="step.depends_on.length" class="mt-1 text-xs text-slate-600">
            依赖：{{ step.depends_on.join(", ") }}
          </p>
        </li>
      </ol>
    </div>
  </article>
</template>
