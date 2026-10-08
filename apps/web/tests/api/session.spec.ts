import { beforeEach, describe, expect, it } from "vitest";

import { clearAccessToken, getAccessToken, setAccessToken } from "@/api/session";

describe("session 令牌存储", () => {
  beforeEach(() => {
    clearAccessToken();
  });

  it("设置后可读取，清除后为空", () => {
    expect(getAccessToken()).toBeNull();
    setAccessToken("tok-1");
    expect(getAccessToken()).toBe("tok-1");
    clearAccessToken();
    expect(getAccessToken()).toBeNull();
  });
});
