import { vi } from "vitest";

import type { ApiClient } from "@/api/client";

export type FakeHandler = (body?: unknown, path?: string) => unknown;

/**
 * 按「METHOD path」注册响应的假 ApiClient。
 * handler 可返回普通值，也可返回 Promise.reject(...) 以模拟后端错误。
 */
export function makeFakeClient(routes: Record<string, FakeHandler>): ApiClient {
  const dispatch =
    (method: string) =>
    (path: string, body?: unknown): Promise<unknown> => {
      const handler = routes[`${method} ${path}`];
      if (!handler) {
        return Promise.reject({ code: "NO_FAKE_ROUTE", message: `${method} ${path}` });
      }
      return Promise.resolve(handler(body, path));
    };

  return {
    getJson: vi.fn(dispatch("GET")),
    postJson: vi.fn(dispatch("POST")),
    putJson: vi.fn(dispatch("PUT")),
    delete: vi.fn((path: string) => dispatch("DELETE")(path).then(() => undefined)),
  } as unknown as ApiClient;
}
