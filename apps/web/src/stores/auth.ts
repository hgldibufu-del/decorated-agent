import { defineStore } from "pinia";

import { ApiClient } from "@/api/client";
import { fetchMe, login as loginApi } from "@/api/auth";
import { clearAccessToken, getAccessToken, setAccessToken } from "@/api/session";
import type { UserSummary } from "@/types/iam";
import type { LoadState } from "@/types/ui";

interface AuthState {
  token: string | null;
  user: UserSummary | null;
  state: LoadState;
  errorMessage: string | null;
  errorCode: string | null;
  retryable: boolean;
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export const useAuthStore = defineStore("auth", {
  state: (): AuthState => ({
    token: getAccessToken(),
    user: null,
    state: "idle",
    errorMessage: null,
    errorCode: null,
    retryable: false,
  }),

  getters: {
    isAuthenticated: (state): boolean => Boolean(state.token && state.user),
    isLoading: (state): boolean => state.state === "loading",
    displayName: (state): string => state.user?.full_name ?? state.user?.email ?? "未登录",
    /** 是否能写项目（决定是否展示「新建项目 / 加成员」入口，避免点了就 403 的死路）。 */
    canWriteProjects: (state): boolean =>
      Boolean(
        state.user &&
          (state.user.roles.includes("admin") || state.user.permissions.includes("project:write")),
      ),
  },

  actions: {
    async login(email: string, password: string, client: ApiClient = new ApiClient()): Promise<void> {
      this.state = "loading";
      this.errorMessage = null;
      this.errorCode = null;
      this.retryable = false;
      try {
        const token = await loginApi(client, { email, password });
        setAccessToken(token.access_token);
        this.token = token.access_token;
        this.user = await fetchMe(client);
        this.state = "ready";
      } catch (error) {
        clearAccessToken();
        this.token = null;
        this.user = null;
        this.state = "error";
        this.errorCode = (error as { code?: string }).code ?? "UNKNOWN";
        this.errorMessage = messageOf(error);
        this.retryable = Boolean((error as { retryable?: boolean }).retryable);
      }
    },

    /** 应用启动时用已有令牌回查身份；令牌失效则登出。 */
    async restore(client: ApiClient = new ApiClient()): Promise<void> {
      if (!this.token) return;
      this.state = "loading";
      try {
        this.user = await fetchMe(client);
        this.state = "ready";
      } catch {
        this.logout();
      }
    },

    logout(): void {
      clearAccessToken();
      this.token = null;
      this.user = null;
      this.state = "idle";
      this.errorMessage = null;
      this.errorCode = null;
      this.retryable = false;
    },
  },
});
