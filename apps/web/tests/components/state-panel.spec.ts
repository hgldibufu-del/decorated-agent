import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import StatePanel from "@/components/StatePanel.vue";
import type { PanelState } from "@/types/ui";

function render(state: PanelState, props: Record<string, unknown> = {}) {
  return mount(StatePanel, { props: { state, ...props } });
}

describe("StatePanel", () => {
  it.each<[PanelState, string]>([
    ["loading", "state-loading"],
    ["empty", "state-empty"],
    ["error", "state-error"],
    ["permission", "state-permission"],
  ])("%s 状态渲染对应的区域", (state, testId) => {
    const wrapper = render(state);
    expect(wrapper.find(`[data-testid="${testId}"]`).exists()).toBe(true);
  });

  it("正常态渲染默认插槽，不渲染任何状态区", () => {
    const wrapper = mount(StatePanel, {
      props: { state: "ready" },
      slots: { default: "<p data-testid=\"content\">业务内容</p>" },
    });

    expect(wrapper.find('[data-testid="content"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="state-error"]').exists()).toBe(false);
  });

  it("可重试的错误才展示重试按钮，且点击会抛出 retry 事件", async () => {
    const wrapper = render("error", {
      message: "后端不可用",
      code: "DATABASE_ERROR",
      retryable: true,
    });

    await wrapper.find('[data-testid="retry-button"]').trigger("click");
    expect(wrapper.emitted("retry")).toHaveLength(1);
  });

  it("不可重试的错误不展示重试按钮", () => {
    const wrapper = render("error", { message: "参数非法", retryable: false });
    expect(wrapper.find('[data-testid="retry-button"]').exists()).toBe(false);
  });
});
