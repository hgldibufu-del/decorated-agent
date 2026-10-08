/** 展示层的小工具（纯函数，可单测）。 */

export function formatMoney(amount: string | number | null | undefined, currency = "CNY"): string {
  if (amount === null || amount === undefined || amount === "") return "-";
  const symbol = currency === "CNY" ? "¥" : `${currency} `;
  return `${symbol}${amount}`;
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return `${Math.round(value * 100)}%`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

/** 工期偏差：正值为延期。 */
export function formatDeviation(days: number | null | undefined): string {
  if (days === null || days === undefined) return "-";
  if (days > 0) return `+${days} 天`;
  if (days < 0) return `${days} 天`;
  return "按计划";
}
