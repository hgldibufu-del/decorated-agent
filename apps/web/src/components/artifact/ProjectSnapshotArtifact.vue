<script setup lang="ts">
import { formatMoney } from "@/utils/format";
import type { ProjectSnapshotPayload } from "@/types/artifact";

const props = defineProps<{ payload: ProjectSnapshotPayload }>();
</script>

<template>
  <div class="space-y-3">
    <div class="flex items-center gap-2">
      <span class="tag">{{ props.payload.project.code }}</span>
      <span class="text-sm font-semibold text-slate-100">{{ props.payload.project.name }}</span>
    </div>
    <dl>
      <div class="kv"><dt class="kv-key">状态</dt><dd class="kv-value">{{ props.payload.project.status }}</dd></div>
      <div class="kv"><dt class="kv-key">客户</dt><dd class="kv-value">{{ props.payload.project.customer_name }}</dd></div>
      <div class="kv"><dt class="kv-key">房屋</dt><dd class="kv-value">{{ props.payload.project.house_address }}</dd></div>
      <div class="kv">
        <dt class="kv-key">预算</dt>
        <dd class="kv-value">{{ formatMoney(props.payload.project.budget_amount) }}</dd>
      </div>
    </dl>
  </div>
</template>
