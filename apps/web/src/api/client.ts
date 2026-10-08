/**
 * 后端统一错误信封（需求文档 §25）的前端解析层。
 *
 * 所有出口错误都必须变成 `ApiError`，页面只需要处理一种结构：
 * `{ code, message, requestId, retryable, details }` + HTTP 状态码。
 */

import { getAccessToken } from "./session";

export interface ErrorPayload {
  code: string;
  message: string;
  request_id: string;
  retryable: boolean;
  category?: string;
  details?: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string;
  readonly retryable: boolean;
  readonly details: Record<string, unknown>;

  constructor(status: number, payload: ErrorPayload) {
    super(payload.message || `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = payload.code || "UNKNOWN";
    this.requestId = payload.request_id || "-";
    this.retryable = Boolean(payload.retryable);
    this.details = payload.details ?? {};
  }

  /** 401 / 403 需要展示「无权限」而不是「出错了」，二者用户动作完全不同。 */
  get isPermissionDenied(): boolean {
    return this.status === 401 || this.status === 403;
  }

  /** status=0 表示请求没有到达后端（网络中断 / CORS / 进程未启动）。 */
  get isNetworkError(): boolean {
    return this.status === 0;
  }

  toJSON(): Record<string, unknown> {
    return {
      status: this.status,
      code: this.code,
      message: this.message,
      requestId: this.requestId,
      retryable: this.retryable,
      details: this.details,
    };
  }
}

const FALLBACK_PAYLOAD: ErrorPayload = {
  code: "UNEXPECTED_RESPONSE",
  message: "后端返回了无法解析的响应",
  request_id: "-",
  retryable: false,
};

export interface ApiClientOptions {
  baseUrl?: string;
  fetchImpl?: typeof fetch;
  /** 取访问令牌；返回 null 时不注入 Authorization（保持与无鉴权请求一致的行为）。 */
  tokenProvider?: () => string | null;
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly tokenProvider: () => string | null;

  constructor(options: ApiClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? "/api";
    this.fetchImpl =
      options.fetchImpl ??
      ((input: RequestInfo | URL, init?: RequestInit) => fetch(input, init));
    this.tokenProvider = options.tokenProvider ?? getAccessToken;
  }

  async getJson<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await this.request(path, init);
    return (await response.json()) as T;
  }

  async postJson<T>(path: string, body: unknown, init: RequestInit = {}): Promise<T> {
    const response = await this.request(path, {
      ...init,
      method: init.method ?? "POST",
      body: JSON.stringify(body),
      headers: { "content-type": "application/json", ...(init.headers ?? {}) },
    });
    return (await response.json()) as T;
  }

  async putJson<T>(path: string, body: unknown, init: RequestInit = {}): Promise<T> {
    const response = await this.request(path, {
      ...init,
      method: "PUT",
      body: JSON.stringify(body),
      headers: { "content-type": "application/json", ...(init.headers ?? {}) },
    });
    return (await response.json()) as T;
  }

  /** DELETE 通常返回 204（无响应体），因此不尝试解析 JSON。 */
  async delete(path: string, init: RequestInit = {}): Promise<void> {
    await this.request(path, { ...init, method: "DELETE" });
  }

  async request(path: string, init: RequestInit = {}): Promise<Response> {
    // 无令牌时不注入 Authorization：既有调用（如健康检查）的请求头保持 byte 级一致
    const token = this.tokenProvider();
    const authHeaders: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        ...init,
        headers: { Accept: "application/json", ...authHeaders, ...(init.headers ?? {}) },
      });
    } catch (error) {
      // 请求根本没到后端：转成可重试的 ApiError，而不是让原始 TypeError 冒泡到 UI
      throw new ApiError(0, {
        code: "NETWORK_ERROR",
        message: "无法连接到后端服务",
        request_id: "-",
        retryable: true,
        details: { reason: error instanceof Error ? error.message : String(error) },
      });
    }

    if (!response.ok) {
      throw await toApiError(response);
    }
    return response;
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  let payload: ErrorPayload = FALLBACK_PAYLOAD;
  try {
    const body = (await response.json()) as Partial<ErrorPayload>;
    payload = {
      code: body.code ?? FALLBACK_PAYLOAD.code,
      message: body.message ?? FALLBACK_PAYLOAD.message,
      request_id: body.request_id ?? FALLBACK_PAYLOAD.request_id,
      retryable: body.retryable ?? FALLBACK_PAYLOAD.retryable,
      category: body.category,
      details: body.details,
    };
  } catch {
    // 响应体不是 JSON（例如网关返回的 HTML）。保留 HTTP 状态码，让调用方仍能区分类型。
    payload = { ...FALLBACK_PAYLOAD, code: `HTTP_${response.status}` };
  }

  // 响应头里的 X-Request-ID 由中间件统一注入，优先级高于 body
  const headerRequestId = response.headers.get("x-request-id");
  if (headerRequestId) {
    payload = { ...payload, request_id: headerRequestId };
  }
  return new ApiError(response.status, payload);
}
