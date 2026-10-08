import { describe, expect, it } from "vitest";

import { formatDeviation, formatMoney, formatPercent } from "@/utils/format";

describe("format 工具", () => {
  it("金额按币种加符号，空值给占位", () => {
    expect(formatMoney("156000.00")).toBe("¥156000.00");
    expect(formatMoney(null)).toBe("-");
    expect(formatMoney("12", "USD")).toBe("USD 12");
  });

  it("比例转百分比", () => {
    expect(formatPercent(0.5)).toBe("50%");
    expect(formatPercent(null)).toBe("-");
  });

  it("工期偏差正值为延期", () => {
    expect(formatDeviation(3)).toBe("+3 天");
    expect(formatDeviation(-2)).toBe("-2 天");
    expect(formatDeviation(0)).toBe("按计划");
    expect(formatDeviation(null)).toBe("-");
  });
});
