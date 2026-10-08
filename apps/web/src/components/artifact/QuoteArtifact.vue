<script setup lang="ts">
import { formatMoney, formatPercent } from "@/utils/format";
import type { QuotePayload } from "@/types/artifact";

const props = defineProps<{ payload: QuotePayload }>();
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <p class="text-xs text-slate-500">推荐套餐</p>
        <p class="text-sm font-semibold text-slate-100">
          {{ props.payload.recommended_package.name }}
          <span v-if="props.payload.recommended_package.tier" class="tag ml-2">
            {{ props.payload.recommended_package.tier }}
          </span>
        </p>
        <p class="mt-1 text-xs text-slate-500">
          户型 {{ props.payload.layout ?? "-" }}
        </p>
      </div>
      <div class="text-right">
        <p class="text-xs text-slate-500">估算总价</p>
        <p class="text-xl font-semibold text-emerald-300" data-testid="quote-total">
          {{ formatMoney(props.payload.estimate.total, props.payload.estimate.currency) }}
        </p>
        <p class="text-xs text-slate-500">置信度 {{ formatPercent(props.payload.confidence) }}</p>
      </div>
    </div>

    <div>
      <h4 class="mb-1 text-xs font-semibold text-slate-400">费用明细</h4>
      <table class="w-full">
        <thead>
          <tr class="border-b border-surface-line">
            <th class="th text-left">项目</th>
            <th class="th text-left">说明</th>
            <th class="th text-right">金额</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(item, index) in props.payload.estimate.line_items"
            :key="index"
            class="border-b border-surface-line/60"
          >
            <td class="td">{{ item.label }}</td>
            <td class="td text-slate-500">{{ item.detail }}</td>
            <td class="td text-right font-mono">{{ formatMoney(item.amount) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="props.payload.comparison?.length">
      <h4 class="mb-1 text-xs font-semibold text-slate-400">套餐对比</h4>
      <table class="w-full">
        <thead>
          <tr class="border-b border-surface-line">
            <th class="th text-left">套餐</th>
            <th class="th text-right">总价</th>
            <th class="th text-right">每平米</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(pkg, index) in props.payload.comparison"
            :key="index"
            class="border-b border-surface-line/60"
          >
            <td class="td">{{ pkg.name }}</td>
            <td class="td text-right font-mono">{{ formatMoney(pkg.total ?? "-") }}</td>
            <td class="td text-right font-mono">{{ formatMoney(pkg.per_sqm_effective ?? "-") }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="props.payload.materials?.length">
      <h4 class="mb-1 text-xs font-semibold text-slate-400">工艺 / 材料</h4>
      <div class="flex flex-wrap gap-2">
        <span v-for="(material, index) in props.payload.materials" :key="index" class="tag">
          {{ material.category }} · {{ material.name }} · {{ formatMoney(material.unit_price) }}/{{ material.unit }}
        </span>
      </div>
    </div>

    <ul v-if="props.payload.assumptions?.length" class="list-disc space-y-1 pl-5 text-xs text-slate-500">
      <li v-for="(note, index) in props.payload.assumptions" :key="index">{{ note }}</li>
    </ul>
  </div>
</template>
