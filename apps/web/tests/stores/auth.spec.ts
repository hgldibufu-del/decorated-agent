import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import { clearAccessToken, getAccessToken, setAccessToken } from "@/api/session";
import { useAuthStore } from "@/stores/auth";
import type { UserSummary } from "@/types/iam";
import { makeFakeClient } from "../helpers/fake-client";

const TOKEN = { access_token: "tok", token_type: "bearer", expires_in: 3600 };
const ME: UserSummary = {
  id: "u1",
  email: "pm.wang@dw.local",
  full_name: "王志远",
  is_active: true,
  roles: ["project_manager"],
  permissions: ["project:read"],
};

describe("useAuthStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    clearAccessToken();
  });

  it("登录成功后保存令牌与用户", async () => {
    const store = useAuthStore();
    const client = makeFakeClient({
      "POST /v1/auth/login": () => TOKEN,
      "GET /v1/auth/me": () => ME,
    });

    await store.login("pm.wang@dw.local", "Passw0rd!", client);

    expect(store.token).toBe("tok");
    expect(store.user?.full_name).toBe("王志远");
    expect(store.isAuthenticated).toBe(true);
    expect(getAccessToken()).toBe("tok");
  });

  it("登录失败进入 error 且不保留令牌", async () => {
    const store = useAuthStore();
    const client = makeFakeClient({
      "POST /v1/auth/login": () =>
        Promise.reject({ code: "AUTHENTICATION_REQUIRED", message: "邮箱或口令错误", retryable: false }),
    });

    await store.login("pm.wang@dw.local", "bad", client);

    expect(store.state).toBe("error");
    expect(store.token).toBeNull();
    expect(store.errorCode).toBe("AUTHENTICATION_REQUIRED");
    expect(getAccessToken()).toBeNull();
  });

  it("logout 清空令牌与用户", async () => {
    const store = useAuthStore();
    const client = makeFakeClient({
      "POST /v1/auth/login": () => TOKEN,
      "GET /v1/auth/me": () => ME,
    });
    await store.login("pm.wang@dw.local", "Passw0rd!", client);

    store.logout();

    expect(store.token).toBeNull();
    expect(store.user).toBeNull();
    expect(getAccessToken()).toBeNull();
  });

  it("restore 时令牌失效则登出", async () => {
    setAccessToken("stale");
    const store = useAuthStore();
    const client = makeFakeClient({
      "GET /v1/auth/me": () => Promise.reject({ code: "AUTHENTICATION_REQUIRED", message: "令牌失效" }),
    });

    await store.restore(client);

    expect(store.token).toBeNull();
    expect(store.user).toBeNull();
  });
});
