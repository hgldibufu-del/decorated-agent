<script setup lang="ts">
import type { PanelState } from "@/types/ui";

/**
 * 统一承载 loading / empty / error / permission denied 四种非正常态。
 *
 * 需求文档 §19 明确要求界面必须能表达这些状态，而不是只在数据正常时能看。
 * 正常态通过默认插槽透出，避免每个页面重复写骨架屏。
 */
const props = withDefaults(
  defineProps<{
    state: PanelState;
    message?: string | null;
    code?: string | null;
    requestId?: string | null;
    retryable?: boolean;
  }>(),
  {
    message: null,
    code: null,
    requestId: null,
    retryable: false,
  },
);

const emit = defineEmits<{ retry: [] }>();
</script>

<template>
  <div
    v-if="props.state === 'loading'"
    class="panel animate-pulse p-6 text-sm text-slate-400"
    data-testid="state-loading"
  >
    正在连接后端服务…
  </div>

  <div
    v-else-if="props.state === 'permission'"
    class="panel border-amber-500/30 p-6 text-sm"
    data-testid="state-permission"
  >
    <p class="font-semibold text-amber-300">当前角色无权访问该资源</p>
    <p class="mt-1 text-xs text-slate-400">
      错误码 {{ props.code ?? "PERMISSION_DENIED" }}，请确认已登录并具备相应角色。
    </p>
  </div>

  <div
    v-else-if="props.state === 'error'"
    class="panel border-rose-500/30 p-6 text-sm"
    data-testid="state-error"
  >
    <p class="font-semibold text-rose-300">后端请求失败</p>
    <p class="mt-1 text-slate-300">{{ props.message }}</p>
    <p v-if="props.code || props.requestId" class="mt-1 text-xs text-slate-500">
      code={{ props.code ?? "-" }} request_id={{ props.requestId ?? "-" }}
    </p>
    <button
      v-if="props.retryable"
      type="button"
      class="mt-3 rounded border border-surface-line px-3 py-1.5 text-xs text-slate-200 hover:bg-surface-line"
      data-testid="retry-button"
      @click="emit('retry')"
    >
      重试
    </button>
  </div>

  <div
    v-else-if="props.state === 'empty'"
    class="panel p-6 text-sm text-slate-400"
    data-testid="state-empty"
  >
    后端没有返回任何组件状态。
  </div>

  <slot v-else />
</template>
