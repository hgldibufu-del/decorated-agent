import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/api/client";
import { useSystemStore } from "@/stores/system";
import type { HealthReport } from "@/types/health";

const report: HealthReport = {
  status: "healthy",
  service: "dw-api",
  version: "0.1.0",
  environment: "production",
  timestamp: "2026-01-01T00:00:00Z",
  components: [
    {
      name: "postgres",
      status: "healthy",
      critical: true,
      latency_ms: 12.5,
      detail: null,
      metadata: { pgvector: "0.8.7" },
    },
  ],
};

function fakeClient(implementation: () => Promise<unknown>): ApiClient {
  return { getJson: vi.fn(implementation) } as unknown as ApiClient;
}

describe("useSystemStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("加载成功后进入 ready 且暴露组件列表", async () => {
    const store = useSystemStore();

    await store.load(fakeClient(async () => report));

    expect(store.state).toBe("ready");
    expect(store.components).toHaveLength(1);
    expect(store.isEmpty).toBe(false);
    expect(store.lastUpdatedAt).not.toBeNull();
  });

  it("后端返回空组件列表时判定为 empty", async () => {
    const store = useSystemStore();

    await store.load(fakeClient(async () => ({ ...report, components: [] })));

    expect(store.isEmpty).toBe(true);
  });

  it("普通失败进入 error 并保留是否可重试", async () => {
    const store = useSystemStore();

    await store.load(
      fakeClient(async () => {
        throw {
          name: "ApiError",
          code: "DATABASE_ERROR",
          message: "数据库不可用",
          retryable: true,
          isPermissionDenied: false,
        };
      }),
    );

    expect(store.state).toBe("error");
    expect(store.errorCode).toBe("DATABASE_ERROR");
    expect(store.retryable).toBe(true);
    expect(store.permissionDenied).toBe(false);
  });

  it("权限类失败与普通失败分开处理", async () => {
    const store = useSystemStore();

    await store.load(
      fakeClient(async () => {
        throw {
          name: "ApiError",
          code: "PERMISSION_DENIED",
          message: "无权限",
          retryable: false,
          isPermissionDenied: true,
        };
      }),
    );

    expect(store.state).toBe("error");
    expect(store.permissionDenied).toBe(true);
    expect(store.report).toBeNull();
  });
});
