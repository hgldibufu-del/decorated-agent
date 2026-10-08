import { createRouter, createWebHistory } from "vue-router";

import { getAccessToken } from "@/api/session";

interface GuardTarget {
  // Vue Router 的 name 类型是 string | symbol | undefined，这里保持兼容
  name?: string | symbol | null;
  fullPath: string;
  meta: { public?: boolean };
}

export type GuardResult = true | { name: string; query?: Record<string, string> };

/**
 * 导航守卫（纯函数，便于单测）：
 * * 需要登录且无令牌 → 去登录页，并带上 redirect；
 * * 已有令牌访问登录页 → 回工作台。
 */
export function navigationGuard(to: GuardTarget, authed: boolean): GuardResult {
  if (to.name === "login" && authed) {
    return { name: "workbench" };
  }
  if (!to.meta.public && !authed) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  return true;
}

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/login",
      name: "login",
      component: () => import("@/views/LoginView.vue"),
      meta: { title: "登录", public: true },
    },
    {
      path: "/workbench",
      name: "workbench",
      component: () => import("@/views/WorkbenchView.vue"),
      meta: { title: "AI 工作台" },
    },
    {
      path: "/projects",
      name: "projects",
      component: () => import("@/views/ProjectsView.vue"),
      meta: { title: "项目" },
    },
    {
      path: "/registry",
      name: "registry",
      component: () => import("@/views/RegistryView.vue"),
      meta: { title: "注册中心" },
    },
    {
      path: "/system",
      name: "system",
      component: () => import("@/views/HealthView.vue"),
      meta: { title: "系统健康", public: true },
    },
    { path: "/", redirect: "/workbench" },
    { path: "/:pathMatch(.*)*", redirect: "/workbench" },
  ],
});

router.beforeEach((to) => navigationGuard(to, Boolean(getAccessToken())));

export default router;
