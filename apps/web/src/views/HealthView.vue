<script setup lang="ts">
import { computed, onMounted, onUnmounted } from "vue";

import StatePanel from "@/components/StatePanel.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import { useSystemStore } from "@/stores/system";
import type { SystemStatus } from "@/types/health";
import type { PanelState } from "@/types/ui";

const AUTO_REFRESH_MS = 15_000;

const store = useSystemStore();
let timer: ReturnType<typeof setInterval> | null = null;

const panelState = computed<PanelState>(() => {
  if (store.isLoading) return "loading";
  if (store.hasError) return store.permissionDenied ? "permission" : "error";
  if (store.isEmpty) return "empty";
  return "ready";
});

const overallStatus = computed<SystemStatus | null>(() => store.report?.status ?? null);

const reportJson = computed<string>(() =>
  store.report ? JSON.stringify(store.report, null, 2) : "",
);

async function refresh(): Promise<void> {
  await store.load();
}

onMounted(async () => {
  await refresh();
  timer = setInterval(() => {
    void store.load();
  }, AUTO_REFRESH_MS);
});

onUnmounted(() => {
  if (timer !== null) {
    clearInterval(timer);
    timer = null;
  }
});
</script>

<template>
  <section class="space-y-6">
    <header class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold text-slate-100">基础设施健康</h2>
        <p class="mt-1 text-xs text-slate-500">
          PostgreSQL 是业务事实源（不可降级）；Redis 与 Kafka 异常时系统降级但仍可服务。
        </p>
      </div>

      <div class="flex items-center gap-3">
        <StatusBadge
          v-if="overallStatus"
          :status="overallStatus"
          :label="`系统 ${overallStatus}`"
        />
        <button
          type="button"
          class="rounded border border-surface-line px-3 py-1.5 text-xs text-slate-200 hover:bg-surface-line disabled:opacity-40"
          :disabled="store.isLoading"
          data-testid="refresh-button"
          @click="refresh"
        >
          {{ store.isLoading ? "刷新中…" : "立即刷新" }}
        </button>
      </div>
    </header>

    <StatePanel
      :state="panelState"
      :message="store.errorMessage"
      :code="store.errorCode"
      :retryable="store.retryable"
      @retry="refresh"
    >
      <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <article
          v-for="component in store.components"
          :key="component.name"
          class="panel p-4"
          data-testid="component-card"
        >
          <div class="flex items-center justify-between">
            <h3 class="font-mono text-sm text-slate-100">{{ component.name }}</h3>
            <StatusBadge :status="component.status" />
          </div>

          <p class="mt-1 text-xs text-slate-500">
            {{ component.critical ? "不可降级依赖" : "可降级依赖" }}
          </p>

          <dl class="mt-3">
            <div class="kv">
              <dt class="kv-key">探针耗时</dt>
              <dd class="kv-value">{{ component.latency_ms }} ms</dd>
            </div>
            <div
              v-for="(value, key) in component.metadata"
              :key="key"
              class="kv"
            >
              <dt class="kv-key">{{ key }}</dt>
              <dd class="kv-value">{{ value }}</dd>
            </div>
          </dl>

          <p v-if="component.detail" class="mt-3 text-xs text-rose-300">
            {{ component.detail }}
          </p>
        </article>
      </div>

      <details class="panel mt-4">
        <summary class="panel-title cursor-pointer select-none">原始响应</summary>
        <pre class="overflow-x-auto p-4 font-mono text-xs text-slate-400">{{ reportJson }}</pre>
      </details>

      <p v-if="store.lastUpdatedAt" class="mt-3 text-xs text-slate-600">
        最近更新：{{ store.lastUpdatedAt }}（每 {{ AUTO_REFRESH_MS / 1000 }} 秒自动刷新）
      </p>
    </StatePanel>
  </section>
</template>
