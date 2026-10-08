/**
 * 后端 `dw_schemas.health` 契约在前端的镜像。
 *
 * 契约不一致会让前端静默显示错数据，因此这里刻意不加任何可选/兜底字段：
 * 后端一旦改动形状，类型检查会立刻报错，避免破坏 `§16 必须保留 provenance` 之类的约束。
 */
export type ComponentStatus = "healthy" | "degraded" | "unhealthy";
export type SystemStatus = "healthy" | "degraded" | "unhealthy";

export interface ComponentHealth {
  name: string;
  status: ComponentStatus;
  critical: boolean;
  latency_ms: number;
  detail: string | null;
  metadata: Record<string, string | number>;
}

export interface HealthReport {
  status: SystemStatus;
  service: string;
  version: string;
  environment: string;
  timestamp: string;
  components: ComponentHealth[];
}
