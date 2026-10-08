import { describe, expect, it } from "vitest";

import { navigationGuard, type GuardResult } from "@/router";

describe("navigationGuard", () => {
  it("未登录访问受保护页 → 去登录页并带 redirect", () => {
    const result = navigationGuard(
      { name: "workbench", fullPath: "/workbench", meta: {} },
      false,
    ) as Exclude<GuardResult, true>;
    expect(result).toEqual({ name: "login", query: { redirect: "/workbench" } });
  });

  it("已登录访问受保护页 → 放行", () => {
    expect(navigationGuard({ name: "workbench", fullPath: "/workbench", meta: {} }, true)).toBe(true);
  });

  it("未登录访问公开页 → 放行", () => {
    expect(
      navigationGuard({ name: "system", fullPath: "/system", meta: { public: true } }, false),
    ).toBe(true);
  });

  it("已登录访问登录页 → 回工作台", () => {
    const result = navigationGuard(
      { name: "login", fullPath: "/login", meta: { public: true } },
      true,
    ) as Exclude<GuardResult, true>;
    expect(result).toEqual({ name: "workbench" });
  });
});
