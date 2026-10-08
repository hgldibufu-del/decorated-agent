import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import { useProjectsStore } from "@/stores/projects";
import type { ProjectDetail, ProjectMember, ProjectSummary } from "@/types/project";
import { makeFakeClient } from "../helpers/fake-client";

const SUMMARY: ProjectSummary = {
  id: "p1",
  code: "GC-2026-100",
  name: "新项目",
  status: "draft",
  customer_name: "刘女士",
  house_address: "星河湾",
  member_role: "owner",
  created_at: "2026-10-05T10:00:00Z",
};

const DETAIL: ProjectDetail = {
  id: "p1",
  code: "GC-2026-100",
  name: "新项目",
  status: "draft",
  customer_id: "c1",
  house_id: "h1",
  budget_amount: null,
  planned_start_date: null,
  planned_complete_date: null,
  note: null,
  created_at: "2026-10-05T10:00:00Z",
  updated_at: "2026-10-05T10:00:00Z",
  version: 1,
  customer: {
    id: "c1",
    name: "刘女士",
    phone: "13800000001",
    email: null,
    note: null,
    created_at: "2026-10-05T10:00:00Z",
  },
  house: {
    id: "h1",
    customer_id: "c1",
    address: "星河湾",
    city: "上海",
    area_sqm: "118.50",
    layout: "三室两厅",
    note: null,
  },
  members: [],
};

const MEMBER: ProjectMember = {
  project_id: "p1",
  user_id: "u2",
  role: "manager",
  email: "designer.zhao@dw.local",
  full_name: "赵敏",
  joined_at: "2026-10-05T10:00:00Z",
};

describe("useProjectsStore 写操作", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("createProject 成功后刷新列表并返回详情", async () => {
    const store = useProjectsStore();
    const client = makeFakeClient({
      "POST /v1/projects": () => DETAIL,
      "GET /v1/projects": () => [SUMMARY],
    });

    const created = await store.createProject(
      { code: "GC-2026-100", name: "新项目", customer_id: "c1", house_id: "h1" },
      client,
    );

    expect(created?.id).toBe("p1");
    expect(store.items).toHaveLength(1);
    expect(store.detail?.code).toBe("GC-2026-100");
  });

  it("createProject 失败时返回 null 并记录错误", async () => {
    const store = useProjectsStore();
    const client = makeFakeClient({
      "POST /v1/projects": () =>
        Promise.reject({ code: "RESOURCE_CONFLICT", message: "项目编号已存在", retryable: false }),
    });

    const created = await store.createProject(
      { code: "DUP", name: "重复", customer_id: "c1", house_id: "h1" },
      client,
    );

    expect(created).toBeNull();
    expect(store.errorCode).toBe("RESOURCE_CONFLICT");
  });

  it("addMember 成功后就地刷新详情成员", async () => {
    const store = useProjectsStore();
    store.$patch({ detail: DETAIL });
    const client = makeFakeClient({
      "POST /v1/projects/p1/members": () => [MEMBER],
    });

    const members = await store.addMember("p1", "u2", "manager", client);

    expect(members).toHaveLength(1);
    expect(store.detail?.members[0]?.full_name).toBe("赵敏");
  });

  it("updateProject 成功后版本自增并刷新详情", async () => {
    const store = useProjectsStore();
    const client = makeFakeClient({
      "PUT /v1/projects/p1": () => ({ ...DETAIL, name: "改名后", version: 2 }),
      "GET /v1/projects": () => [SUMMARY],
    });

    const updated = await store.updateProject("p1", { version: 1, name: "改名后" }, client);

    expect(updated?.version).toBe(2);
    expect(store.detail?.name).toBe("改名后");
  });

  it("updateProject 版本冲突返回 null 且 errorCode=CONFLICT", async () => {
    const store = useProjectsStore();
    const client = makeFakeClient({
      "PUT /v1/projects/p1": () =>
        Promise.reject({ code: "CONFLICT", message: "版本冲突", retryable: false }),
    });

    const updated = await store.updateProject("p1", { version: 1, name: "x" }, client);

    expect(updated).toBeNull();
    expect(store.errorCode).toBe("CONFLICT");
  });

  it("removeProject 成功后清空详情并刷新列表", async () => {
    const store = useProjectsStore();
    store.$patch({ detail: DETAIL });
    const client = makeFakeClient({
      "DELETE /v1/projects/p1": () => undefined,
      "GET /v1/projects": () => [],
    });

    const ok = await store.removeProject("p1", client);

    expect(ok).toBe(true);
    expect(store.detail).toBeNull();
  });

  it("removeProject 被引用时返回 false 且 errorCode=CONFLICT", async () => {
    const store = useProjectsStore();
    const client = makeFakeClient({
      "DELETE /v1/projects/p1": () =>
        Promise.reject({ code: "CONFLICT", message: "仍被引用", retryable: false }),
    });

    const ok = await store.removeProject("p1", client);

    expect(ok).toBe(false);
    expect(store.errorCode).toBe("CONFLICT");
  });
});
