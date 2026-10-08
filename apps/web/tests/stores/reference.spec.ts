import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import { useReferenceStore } from "@/stores/reference";
import type { Customer, House } from "@/types/project";
import type { UserBrief } from "@/types/iam";
import { makeFakeClient } from "../helpers/fake-client";

const CUSTOMER: Customer = {
  id: "c1",
  name: "刘女士",
  phone: "13800000001",
  email: null,
  note: null,
  created_at: "2026-10-05T10:00:00Z",
};

const HOUSE: House = {
  id: "h1",
  customer_id: "c1",
  address: "星河湾 3 期",
  city: "上海",
  area_sqm: "118.50",
  layout: "三室两厅",
  note: null,
};

const USER: UserBrief = { id: "u1", email: "pm.wang@dw.local", full_name: "王志远" };

describe("useReferenceStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("load 拉齐客户 / 房屋 / 成员候选", async () => {
    const store = useReferenceStore();
    const client = makeFakeClient({
      "GET /v1/customers": () => [CUSTOMER],
      "GET /v1/houses": () => [HOUSE],
      "GET /v1/users": () => [USER],
    });

    await store.load(client);

    expect(store.state).toBe("ready");
    expect(store.customers).toHaveLength(1);
    expect(store.houses[0]?.layout).toBe("三室两厅");
    expect(store.users[0]?.full_name).toBe("王志远");
  });

  it("addCustomer 后置顶新客户", async () => {
    const store = useReferenceStore();
    const client = makeFakeClient({
      "POST /v1/customers": (body) => ({
        ...CUSTOMER,
        id: "c2",
        name: (body as { name: string }).name,
      }),
    });

    const created = await store.addCustomer({ name: "新客户", phone: "139" }, client);

    expect(created.id).toBe("c2");
    expect(store.customers[0]?.name).toBe("新客户");
  });

  it("addHouse 后置顶新房屋", async () => {
    const store = useReferenceStore();
    const client = makeFakeClient({
      "POST /v1/houses": () => ({ ...HOUSE, id: "h2", address: "新地址" }),
    });

    await store.addHouse({ customer_id: "c1", address: "新地址" }, client);

    expect(store.houses[0]?.id).toBe("h2");
  });

  it("editCustomer 就地替换列表项", async () => {
    const store = useReferenceStore();
    store.$patch({ customers: [CUSTOMER] });
    const client = makeFakeClient({
      "PUT /v1/customers/c1": () => ({ ...CUSTOMER, name: "改名后" }),
    });

    const updated = await store.editCustomer("c1", { name: "改名后" }, client);

    expect(updated?.name).toBe("改名后");
    expect(store.customers[0]?.name).toBe("改名后");
  });

  it("removeCustomer 成功移除；被引用时返回 false 且记录冲突", async () => {
    const store = useReferenceStore();
    store.$patch({ customers: [CUSTOMER] });

    const okClient = makeFakeClient({ "DELETE /v1/customers/c1": () => undefined });
    expect(await store.removeCustomer("c1", okClient)).toBe(true);
    expect(store.customers).toHaveLength(0);

    const blockedClient = makeFakeClient({
      "DELETE /v1/customers/c1": () =>
        Promise.reject({ code: "CONFLICT", message: "名下仍有房屋", retryable: false }),
    });
    expect(await store.removeCustomer("c1", blockedClient)).toBe(false);
    expect(store.errorCode).toBe("CONFLICT");
  });

  it("editHouse / removeHouse 就地更新列表", async () => {
    const store = useReferenceStore();
    store.$patch({ houses: [HOUSE] });

    const editClient = makeFakeClient({
      "PUT /v1/houses/h1": () => ({ ...HOUSE, area_sqm: "120.00" }),
    });
    await store.editHouse("h1", { area_sqm: "120.00" }, editClient);
    expect(store.houses[0]?.area_sqm).toBe("120.00");

    const removeClient = makeFakeClient({ "DELETE /v1/houses/h1": () => undefined });
    expect(await store.removeHouse("h1", removeClient)).toBe(true);
    expect(store.houses).toHaveLength(0);
  });
});
