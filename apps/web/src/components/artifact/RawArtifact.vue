<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ payload: Record<string, unknown> }>();

const json = computed(() => JSON.stringify(props.payload, null, 2));
</script>

<template>
  <pre class="overflow-x-auto rounded border border-surface-line bg-surface p-3 font-mono text-xs text-slate-400">{{ json }}</pre>
</template>
