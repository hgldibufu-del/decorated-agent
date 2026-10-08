<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import StatePanel from "@/components/StatePanel.vue";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const router = useRouter();
const route = useRoute();

const email = ref("pm.wang@dw.local");
const password = ref("Passw0rd!");

async function submit(): Promise<void> {
  await auth.login(email.value, password.value);
  if (auth.token) {
    const redirect = typeof route.query.redirect === "string" ? route.query.redirect : null;
    void router.push(redirect ?? { name: "workbench" });
  }
}
</script>

<template>
  <section class="panel w-full max-w-md p-6">
    <h1 class="text-base font-semibold text-slate-100">登录工作台</h1>
    <p class="mt-1 text-xs text-slate-500">
      演示账号见 <code class="font-mono">scripts/seed.py</code>，默认口令
      <code class="font-mono">Passw0rd!</code>。
    </p>

    <form class="mt-5 space-y-3" @submit.prevent="submit">
      <label class="block text-xs text-slate-400">
        邮箱
        <input v-model="email" type="text" class="input mt-1" data-testid="email-input" />
      </label>
      <label class="block text-xs text-slate-400">
        口令
        <input v-model="password" type="password" class="input mt-1" data-testid="password-input" />
      </label>

      <button
        type="submit"
        class="btn btn-primary w-full"
        :disabled="auth.isLoading"
        data-testid="login-button"
      >
        {{ auth.isLoading ? "登录中…" : "登录" }}
      </button>
    </form>

    <StatePanel
      v-if="auth.state === 'error'"
      class="mt-4"
      state="error"
      :message="auth.errorMessage"
      :code="auth.errorCode"
      :retryable="auth.retryable"
      @retry="submit"
    />
  </section>
</template>
