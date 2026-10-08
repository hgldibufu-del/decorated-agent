/** UI 状态枚举：与需求文档 §19 要求的展示状态一一对应。 */
export type PanelState =
  | "loading"
  | "empty"
  | "error"
  | "permission"
  | "ready";

/** 通用数据加载状态机：idle → loading → ready | error。 */
export type LoadState = "idle" | "loading" | "ready" | "error";
