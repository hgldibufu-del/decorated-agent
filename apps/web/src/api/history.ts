/**
 * 最近 Run 的客户端本地记录。
 *
 * 后端没有 `GET /runs` 列表端点，因此「运行历史」由前端自行留痕：
 * 只存最小元数据（id + 目标 + 状态），打开时再用 `GET /runs/{id}` 拉最新详情。
 */

const STORAGE_KEY = "dw.recent_runs";
const MAX_ENTRIES = 20;

export interface RecentRun {
  id: string;
  objective: string;
  intent: string | null;
  status: string;
  project_id: string | null;
  at: string;
}

function storage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

export function listRecentRuns(): RecentRun[] {
  const raw = storage()?.getItem(STORAGE_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? (parsed as RecentRun[]) : [];
  } catch {
    return [];
  }
}

export function rememberRun(entry: RecentRun): RecentRun[] {
  const others = listRecentRuns().filter((item) => item.id !== entry.id);
  const next = [entry, ...others].slice(0, MAX_ENTRIES);
  storage()?.setItem(STORAGE_KEY, JSON.stringify(next));
  return next;
}

export function clearRecentRuns(): void {
  storage()?.removeItem(STORAGE_KEY);
}
