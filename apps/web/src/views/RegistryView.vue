<script setup lang="ts">
import { computed, onMounted } from "vue";

import StatePanel from "@/components/StatePanel.vue";
import { useRegistryStore } from "@/stores/registry";
import type { PanelState } from "@/types/ui";

const registry = useRegistryStore();

const panelState = computed<PanelState>(() => {
  if (registry.isLoading) return "loading";
  if (registry.state === "error") return "error";
  if (!registry.agents.length && !registry.skills.length && !registry.tools.length) return "empty";
  return "ready";
});

onMounted(async () => {
  if (registry.state === "idle") await registry.load();
});
</script>

<template>
  <section class="space-y-6">
    <header>
      <h2 class="text-lg font-semibold text-slate-100">注册中心</h2>
      <p class="mt-1 text-xs text-slate-500">
        Supervisor 只能从注册中心选「真实存在且已启用」的 Agent / Skill / Tool（只读）。
      </p>
    </header>

    <StatePanel
      :state="panelState"
      :message="registry.errorMessage"
      :code="registry.errorCode"
      :retryable="registry.retryable"
      @retry="registry.load()"
    >
      <article class="panel overflow-hidden">
        <header class="panel-title">Agents（{{ registry.agents.length }}）</header>
        <table class="w-full">
          <thead>
            <tr class="border-b border-surface-line bg-surface">
              <th class="th text-left">Agent</th>
              <th class="th text-left">类型</th>
              <th class="th text-left">支持技能</th>
              <th class="th text-left">Scopes</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="agent in registry.agents" :key="agent.agent_id" class="border-b border-surface-line/60">
              <td class="td font-mono">{{ agent.agent_id }}</td>
              <td class="td text-slate-500">{{ agent.agent_type }}</td>
              <td class="td text-slate-500">{{ agent.supported_skills.join(", ") }}</td>
              <td class="td text-slate-500">{{ agent.required_scopes.join(", ") }}</td>
            </tr>
          </tbody>
        </table>
      </article>

      <article class="panel mt-4 overflow-hidden">
        <header class="panel-title">Skills（{{ registry.skills.length }}）</header>
        <table class="w-full">
          <thead>
            <tr class="border-b border-surface-line bg-surface">
              <th class="th text-left">Skill</th>
              <th class="th text-left">Agent</th>
              <th class="th text-left">风险</th>
              <th class="th text-left">允许工具</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="skill in registry.skills" :key="skill.skill_id" class="border-b border-surface-line/60">
              <td class="td font-mono">{{ skill.skill_id }}</td>
              <td class="td text-slate-500">{{ skill.agent_type }}</td>
              <td class="td">
                <span
                  class="tag"
                  :class="skill.risk_level === 'L2' || skill.risk_level === 'L3' ? 'border-amber-500/40 text-amber-300' : ''"
                >
                  {{ skill.risk_level }}
                </span>
              </td>
              <td class="td text-slate-500">{{ skill.allowed_tools.join(", ") }}</td>
            </tr>
          </tbody>
        </table>
      </article>

      <article class="panel mt-4 overflow-hidden">
        <header class="panel-title">Tools（{{ registry.tools.length }}）</header>
        <table class="w-full">
          <thead>
            <tr class="border-b border-surface-line bg-surface">
              <th class="th text-left">Tool</th>
              <th class="th text-left">风险</th>
              <th class="th text-left">Scopes</th>
              <th class="th text-right">超时</th>
              <th class="th text-right">重试</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="tool in registry.tools" :key="tool.tool_id" class="border-b border-surface-line/60">
              <td class="td font-mono">{{ tool.tool_id }}</td>
              <td class="td"><span class="tag">{{ tool.risk_level }}</span></td>
              <td class="td text-slate-500">{{ tool.required_scopes.join(", ") }}</td>
              <td class="td text-right font-mono">{{ tool.timeout_ms }} ms</td>
              <td class="td text-right font-mono">{{ tool.retry_max_attempts }}</td>
            </tr>
          </tbody>
        </table>
      </article>
    </StatePanel>
  </section>
</template>
