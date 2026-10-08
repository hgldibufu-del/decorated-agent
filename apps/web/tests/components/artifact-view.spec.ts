import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import ArtifactView from "@/components/artifact/ArtifactView.vue";
import type { ArtifactOut } from "@/types/agent";

function artifact(type: string, payload: Record<string, unknown>): ArtifactOut {
  return {
    id: "a-1",
    run_id: "r-1",
    artifact_type: type,
    producer: type,
    payload,
    version: 1,
    created_at: "2026-10-05T10:00:00Z",
  };
}

describe("ArtifactView 分发与定制渲染", () => {
  it("project_snapshot 渲染项目要点", () => {
    const wrapper = mount(ArtifactView, {
      props: {
        artifact: artifact("project_snapshot", {
          project: {
            id: "p1",
            code: "GC-2026-001",
            name: "星河湾现代简约整装",
            status: "active",
            customer_name: "刘女士",
            house_address: "星河湾 3 期",
            budget_amount: "380000.00",
            member_role: "owner",
          },
          upstream_artifacts: [],
        }),
      },
    });
    expect(wrapper.text()).toContain("GC-2026-001");
    expect(wrapper.text()).toContain("¥380000.00");
  });

  it("aftersales_diagnosis 渲染根因与置信度", () => {
    const wrapper = mount(ArtifactView, {
      props: {
        artifact: artifact("aftersales_diagnosis", {
          issue: "卫生间渗水",
          hypothesis: "防水/管道渗漏",
          suggested_actions: ["重做防水层"],
          confidence: 0.6,
          evidence: [],
          similar_cases: [],
        }),
      },
    });
    expect(wrapper.text()).toContain("防水/管道渗漏");
    expect(wrapper.text()).toContain("60%");
  });

  it("quote_estimate 渲染总价", () => {
    const wrapper = mount(ArtifactView, {
      props: {
        artifact: artifact("quote_estimate", {
          project_id: "p1",
          layout: "三室两厅",
          recommended_package: { name: "标准整装包", tier: "标准", base_price: "28000.00", price_per_sqm: "1280.00" },
          estimate: { line_items: [{ label: "面积计价", amount: "128000.00", detail: "100 m²" }], total: "156000.00", currency: "CNY" },
          comparison: [],
          materials: [],
          assumptions: [],
          confidence: 0.85,
        }),
      },
    });
    expect(wrapper.get('[data-testid="quote-total"]').text()).toContain("¥156000.00");
    expect(wrapper.text()).toContain("标准整装包");
  });

  it("design_proposal 渲染推荐风格", () => {
    const wrapper = mount(ArtifactView, {
      props: {
        artifact: artifact("design_proposal", {
          project_id: "p1",
          layout: "三室两厅",
          area_sqm: "100.00",
          space_planning: [],
          recommended_styles: [
            {
              name: "现代简约",
              style_family: "现代简约",
              description: "留白",
              suitable_layouts: ["三室两厅"],
              palette: ["#FFFFFF"],
              characteristics: {},
              tags: ["现代"],
              score: 2,
            },
          ],
          recommended_palette: ["#FFFFFF"],
          suggested_material_categories: ["主材"],
          assumptions: [],
          confidence: 0.8,
        }),
      },
    });
    expect(wrapper.text()).toContain("现代简约");
  });

  it("construction_review 渲染风险标记", () => {
    const wrapper = mount(ArtifactView, {
      props: {
        artifact: artifact("construction_review", {
          project_id: "p1",
          progress: {
            stages: [],
            total_planned_days: 31,
            total_actual_days: 20,
            progress_ratio: 0.5,
            delayed_stages: [],
            at_risk: true,
          },
          quality: { items: [], score: 1, defects: [], passed: true },
          suggestions: ["补充人力"],
          assumptions: [],
          confidence: 0.82,
        }),
      },
    });
    expect(wrapper.text()).toContain("存在延期风险");
    expect(wrapper.text()).toContain("补充人力");
  });

  it("未知类型兜底为原始 JSON", () => {
    const wrapper = mount(ArtifactView, {
      props: { artifact: artifact("some_new_type", { foo: "bar" }) },
    });
    expect(wrapper.text()).toContain('"foo"');
  });
});
