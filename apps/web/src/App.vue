<script setup lang="ts">
import { computed, onMounted } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";

import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const NAV = [
  { name: "workbench", title: "AI 工作台" },
  { name: "projects", title: "项目" },
  { name: "registry", title: "注册中心" },
  { name: "system", title: "系统健康" },
];

// 持有令牌即展示工作台外壳（用户信息可随后补齐），避免刷新时闪一下无导航骨架
const showShell = computed(() => Boolean(auth.token));

onMounted(async () => {
  await auth.restore();
  if (!auth.token && !route.meta.public) {
    void router.push({ name: "login" });
  }
});

function logout(): void {
  auth.logout();
  void router.push({ name: "login" });
}
</script>

<template>
  <div class="flex min-h-full flex-col">
    <header
      class="flex items-center justify-between border-b border-surface-line bg-surface-soft px-6 py-3"
    >
      <div class="flex items-baseline gap-3">
        <span class="text-sm font-semibold text-slate-100">装修 AI Agent Workbench</span>
        <span class="text-xs text-slate-500">Phase 7 · 四 Specialist 工作台</span>
      </div>
      <div class="flex items-center gap-3 text-xs text-slate-400">
        <template v-if="auth.token">
          <span class="rounded border border-surface-line px-2 py-0.5">
            {{ auth.displayName }}
          </span>
          <button type="button" class="btn" data-testid="logout-button" @click="logout">退出</button>
        </template>
      </div>
    </header>

    <div v-if="showShell" class="flex flex-1">
      <aside class="w-52 border-r border-surface-line bg-surface-soft px-3 py-4">
        <nav class="space-y-1">
          <RouterLink
            v-for="item in NAV"
            :key="item.name"
            :to="{ name: item.name }"
            class="block rounded px-3 py-2 text-sm text-slate-400 hover:bg-surface-line hover:text-slate-100"
            active-class="bg-surface-line text-slate-100"
          >
            {{ item.title }}
          </RouterLink>
        </nav>

        <p class="mt-6 px-3 text-xs leading-relaxed text-slate-600">
          自然语言入口 → Supervisor 规划 → Specialist 执行 → 产出可追溯的 Artifact。
        </p>
      </aside>

      <main class="flex-1 overflow-x-hidden px-6 py-6">
        <RouterView />
      </main>
    </div>

    <main v-else class="flex flex-1 items-start justify-center px-6 py-16">
      <RouterView />
    </main>
  </div>
</template>
