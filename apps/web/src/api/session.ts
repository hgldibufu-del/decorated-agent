/**
 * 访问令牌的存放处（与框架解耦）。
 *
 * 刻意不放进 Pinia：ApiClient 需要令牌，而 ApiClient 是纯 TS、被 stores 与测试直接构造。
 * 让 ApiClient 依赖一个「取令牌的回调」，而不是依赖 store，可避免 store ↔ client 循环依赖。
 */

const STORAGE_KEY = "dw.access_token";

// 内存副本：localStorage 在部分环境（隐私模式 / SSR）不可用，内存兜底保证同会话可用。
let inMemory: string | null = null;

function storage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

export function getAccessToken(): string | null {
  if (inMemory) return inMemory;
  const store = storage();
  return store ? store.getItem(STORAGE_KEY) : null;
}

export function setAccessToken(token: string): void {
  inMemory = token;
  storage()?.setItem(STORAGE_KEY, token);
}

export function clearAccessToken(): void {
  inMemory = null;
  storage()?.removeItem(STORAGE_KEY);
}
