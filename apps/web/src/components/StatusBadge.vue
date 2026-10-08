<script setup lang="ts">
import type { ComponentStatus, SystemStatus } from "@/types/health";

const props = defineProps<{
  status: ComponentStatus | SystemStatus;
  label?: string;
}>();

const TONE: Record<string, string> = {
  healthy: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  degraded: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  unhealthy: "border-rose-500/30 bg-rose-500/10 text-rose-300",
};

const TEXT: Record<string, string> = {
  healthy: "正常",
  degraded: "降级",
  unhealthy: "不可用",
};
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs"
    :class="TONE[props.status]"
  >
    <span class="h-1.5 w-1.5 rounded-full bg-current" />
    {{ props.label ?? TEXT[props.status] ?? props.status }}
  </span>
</template>
