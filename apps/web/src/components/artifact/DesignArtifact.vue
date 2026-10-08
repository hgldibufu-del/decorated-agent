<script setup lang="ts">
import { formatPercent } from "@/utils/format";
import type { DesignPayload } from "@/types/artifact";

const props = defineProps<{ payload: DesignPayload }>();
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <span class="tag">户型 {{ props.payload.layout ?? "-" }}</span>
      <span class="tag">面积 {{ props.payload.area_sqm ?? "-" }} m²</span>
      <span class="tag">置信度 {{ formatPercent(props.payload.confidence) }}</span>
    </div>

    <div v-if="props.payload.recommended_styles?.length">
      <h4 class="mb-2 text-xs font-semibold text-slate-400">推荐风格</h4>
      <div class="space-y-2">
        <article
          v-for="(style, index) in props.payload.recommended_styles"
          :key="index"
          class="rounded border border-surface-line bg-surface p-3"
        >
          <div class="flex items-center justify-between">
            <span class="text-sm font-semibold text-slate-100">{{ style.name }}</span>
            <span class="tag">匹配分 {{ style.score }}</span>
          </div>
          <p v-if="style.description" class="mt-1 text-xs text-slate-500">{{ style.description }}</p>
          <div class="mt-2 flex items-center gap-1.5">
            <span
              v-for="(color, ci) in style.palette"
              :key="ci"
              class="h-4 w-4 rounded border border-surface-line"
              :style="{ backgroundColor: color }"
              :title="color"
            />
          </div>
          <div class="mt-2 flex flex-wrap gap-1.5">
            <span v-for="(tag, ti) in style.tags" :key="ti" class="tag">{{ tag }}</span>
          </div>
        </article>
      </div>
    </div>

    <div v-if="props.payload.space_planning?.length">
      <h4 class="mb-1 text-xs font-semibold text-slate-400">空间规划</h4>
      <table class="w-full">
        <thead>
          <tr class="border-b border-surface-line">
            <th class="th text-left">空间</th>
            <th class="th text-left">功能</th>
            <th class="th text-left">设计原则</th>
            <th class="th text-left">建议材料</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(space, index) in props.payload.space_planning"
            :key="index"
            class="border-b border-surface-line/60"
          >
            <td class="td">{{ space.room_type }}</td>
            <td class="td text-slate-500">{{ space.suggested_function ?? "-" }}</td>
            <td class="td text-slate-500">{{ space.design_principle ?? "-" }}</td>
            <td class="td text-slate-500">{{ space.recommended_material_category ?? "-" }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="props.payload.recommended_palette?.length">
      <h4 class="mb-1 text-xs font-semibold text-slate-400">推荐色板</h4>
      <div class="flex items-center gap-2">
        <span
          v-for="(color, index) in props.payload.recommended_palette"
          :key="index"
          class="h-6 w-10 rounded border border-surface-line"
          :style="{ backgroundColor: color }"
          :title="color"
        />
      </div>
    </div>

    <ul v-if="props.payload.assumptions?.length" class="list-disc space-y-1 pl-5 text-xs text-slate-500">
      <li v-for="(note, index) in props.payload.assumptions" :key="index">{{ note }}</li>
    </ul>
  </div>
</template>
