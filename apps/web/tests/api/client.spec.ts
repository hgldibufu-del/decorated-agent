import { describe, expect, it, vi } from "vitest";

import { ApiClient, ApiError } from "@/api/client";

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

function htmlResponse(status = 502) {
  return new Response("<html>gateway error</html>", {
    status,
    headers: { "content-type": "text/html" },
  });
}

function clientReturning(response: Response) {
  const fetchImpl = vi.fn().mockResolvedValue(response);
  return { client: new ApiClient({ baseUrl: "/api", fetchImpl }), fetchImpl };
}

describe("ApiClient", () => {
  it("解析成功响应体", async () => {
    const { client, fetchImpl } = clientReturning(jsonResponse({ status: "alive" }));

    const body = await client.getJson<{ status: string }>("/v1/live");

    expect(body).toEqual({ status: "alive" });
    expect(fetchImpl).toHaveBeenCalledWith("/api/v1/live", {
      headers: { Accept: "application/json" },
    });
  });

  it("把后端统一错误信封转成 ApiError", async () => {
    const { client } = clientReturning(
      jsonResponse(
        {
          code: "TOOL_TIMEOUT",
          message: "材料价格查询超时",
          request_id: "rid-1",
          retryable: true,
          category: "tool_error",
        },
        504,
      ),
    );

    const error = await client.getJson("/v1/health").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 504,
      code: "TOOL_TIMEOUT",
      message: "材料价格查询超时",
      requestId: "rid-1",
      retryable: true,
    });
  });

  it("响应头的 request_id 优先级高于响应体", async () => {
    const { client } = clientReturning(
      jsonResponse({ code: "X", message: "m", request_id: "body-id" }, 500, {
        "x-request-id": "header-id",
      }),
    );

    const error = await client.getJson("/v1/health").catch((e: unknown) => e);
    expect((error as ApiError).requestId).toBe("header-id");
  });

  it("非 JSON 错误响应用 HTTP 状态码兜底，而不是崩在未处理异常上", async () => {
    const { client } = clientReturning(htmlResponse(502));

    const error = await client.getJson("/v1/health").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("HTTP_502");
    expect((error as ApiError).status).toBe(502);
  });

  it("网络中断时抛出可重试的 ApiError", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError("fetch failed"));
    const client = new ApiClient({ fetchImpl });

    const error = await client.getJson("/v1/health").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(0);
    expect((error as ApiError).retryable).toBe(true);
    expect((error as ApiError).isNetworkError).toBe(true);
  });

  it("401 / 403 判定为权限问题，其余不是", async () => {
    const denied = new ApiError(403, {
      code: "PERMISSION_DENIED",
      message: "无权限",
      request_id: "-",
      retryable: false,
    });
    const unavailable = new ApiError(503, {
      code: "DEPENDENCY_UNAVAILABLE",
      message: "依赖不可用",
      request_id: "-",
      retryable: true,
    });

    expect(denied.isPermissionDenied).toBe(true);
    expect(unavailable.isPermissionDenied).toBe(false);
  });
});
