import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import PlanPreview from "@/components/PlanPreview.vue";
import type { Plan } from "@/types/supervisor";

const PLAN: Plan = {
  intent: "design_proposal",
  mode: "direct",
  rationale: "设计提案意图",
  steps: [
    {
      task_key: "T-001",
      agent_id: "design_agent",
      skill_id: "design_proposal",
      objective: "出一套设计方案",
      depends_on: [],
      input: {},
    },
  ],
};

describe("PlanPreview", () => {
  it("渲染意图中文标签与步骤", () => {
    const wrapper = mount(PlanPreview, { props: { plan: PLAN } });

    expect(wrapper.text()).toContain("设计提案");
    expect(wrapper.findAll('[data-testid="plan-step"]')).toHaveLength(1);
    expect(wrapper.text()).toContain("design_agent · design_proposal");
  });
});
