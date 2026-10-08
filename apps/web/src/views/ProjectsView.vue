<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";

import ProjectCreatePanel from "@/components/ProjectCreatePanel.vue";
import ReferenceManagePanel from "@/components/ReferenceManagePanel.vue";
import StatePanel from "@/components/StatePanel.vue";
import { useAuthStore } from "@/stores/auth";
import { useProjectsStore } from "@/stores/projects";
import { useReferenceStore } from "@/stores/reference";
import type { ProjectRole, ProjectStatus } from "@/types/project";
import type { PanelState } from "@/types/ui";
import { formatMoney } from "@/utils/format";

const projects = useProjectsStore();
const auth = useAuthStore();
const reference = useReferenceStore();

const memberUserId = ref("");
const memberRole = ref<ProjectRole>("member");
const memberMessage = ref<string | null>(null);

const editForm = reactive({
  name: "",
  status: "draft" as ProjectStatus,
  budget_amount: "",
  note: "",
});
const editMessage = ref<string | null>(null);
const editError = ref<string | null>(null);

// 只有 owner / manager（或 admin）能改本项目：与后端 can_write_project 口径一致
const canManageProject = computed<boolean>(() => {
  if (auth.user?.roles.includes("admin")) return true;
  const me = projects.detail?.members.find((member) => member.email === auth.user?.email);
  return me?.role === "owner" || me?.role === "manager";
});
const canEditProject = computed<boolean>(() => auth.canWriteProjects && canManageProject.value);

watch(
  () => projects.detail,
  (detail) => {
    if (!detail) return;
    editForm.name = detail.name;
    editForm.status = detail.status;
    editForm.budget_amount = detail.budget_amount ?? "";
    editForm.note = detail.note ?? "";
    editMessage.value = null;
    editError.value = null;
  },
);

async function saveProject(): Promise<void> {
  if (!projects.detail) return;
  editMessage.value = null;
  editError.value = null;
  const updated = await projects.updateProject(projects.detail.id, {
    version: projects.detail.version,
    name: editForm.name,
    status: editForm.status,
    budget_amount: editForm.budget_amount || null,
    note: editForm.note || null,
  });
  if (updated) {
    editMessage.value = `已保存（版本 ${updated.version}）`;
  } else if (projects.errorCode === "CONFLICT") {
    editError.value = "版本冲突：项目已被他人修改，请重新打开后再改";
  } else {
    editError.value = projects.errorMessage ?? "保存失败";
  }
}

async function removeProject(): Promise<void> {
  if (!projects.detail) return;
  editMessage.value = null;
  editError.value = null;
  const ok = await projects.removeProject(projects.detail.id);
  if (ok) {
    editMessage.value = "项目已删除";
  } else if (projects.errorCode === "CONFLICT") {
    editError.value = "该项目仍被 Agent Run / 施工记录引用，无法删除";
  } else {
    editError.value = projects.errorMessage ?? "删除失败";
  }
}

const STATUS_LABEL: Record<ProjectStatus, string> = {
  draft: "草稿",
  active: "进行中",
  on_hold: "暂停",
  completed: "已完成",
  cancelled: "已取消",
};

const listState = computed<PanelState>(() => {
  if (projects.isLoading) return "loading";
  if (projects.state === "error") return projects.permissionDenied ? "permission" : "error";
  if (projects.isEmpty) return "empty";
  return "ready";
});

const detailState = computed<PanelState>(() => {
  if (projects.detailState === "loading") return "loading";
  if (projects.detailState === "error") return projects.permissionDenied ? "permission" : "error";
  return "ready";
});

onMounted(async () => {
  if (projects.state === "idle") await projects.load();
  if (auth.canWriteProjects && reference.state === "idle") await reference.load();
});

async function addMember(): Promise<void> {
  if (!projects.detail || !memberUserId.value) return;
  memberMessage.value = null;
  const members = await projects.addMember(projects.detail.id, memberUserId.value, memberRole.value);
  if (members) {
    memberMessage.value = "成员已保存";
    memberUserId.value = "";
  } else {
    memberMessage.value = projects.errorMessage ?? "保存失败";
  }
}
</script>

<template>
  <section class="space-y-6">
    <header>
      <h2 class="text-lg font-semibold text-slate-100">项目</h2>
      <p class="mt-1 text-xs text-slate-500">按 Project ACL 收敛：你只能看到自己参与的项目。</p>
    </header>

    <StatePanel
      :state="listState"
      :message="projects.errorMessage"
      :code="projects.errorCode"
      :retryable="projects.retryable"
      @retry="projects.load()"
    >
      <article class="panel overflow-hidden">
        <table class="w-full">
          <thead>
            <tr class="border-b border-surface-line bg-surface">
              <th class="th text-left">编号</th>
              <th class="th text-left">名称</th>
              <th class="th text-left">状态</th>
              <th class="th text-left">客户</th>
              <th class="th text-left">房屋</th>
              <th class="th text-left">我的角色</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in projects.items"
              :key="item.id"
              class="cursor-pointer border-b border-surface-line/60 hover:bg-surface-line/40"
              data-testid="project-row"
              @click="projects.loadDetail(item.id)"
            >
              <td class="td font-mono">{{ item.code }}</td>
              <td class="td">{{ item.name }}</td>
              <td class="td text-slate-500">{{ STATUS_LABEL[item.status] }}</td>
              <td class="td text-slate-500">{{ item.customer_name }}</td>
              <td class="td text-slate-500">{{ item.house_address }}</td>
              <td class="td text-slate-500">{{ item.member_role ?? "-" }}</td>
            </tr>
          </tbody>
        </table>
      </article>
    </StatePanel>

    <ProjectCreatePanel v-if="auth.canWriteProjects" @created="projects.load()" />

    <ReferenceManagePanel v-if="auth.canWriteProjects" />

    <StatePanel
      v-if="projects.detailState !== 'idle'"
      :state="detailState"
      :message="projects.errorMessage"
      :code="projects.errorCode"
      :retryable="projects.retryable"
    >
      <article v-if="projects.detail" class="panel" data-testid="project-detail">
        <header class="panel-title flex items-center justify-between">
          <span>{{ projects.detail.code }} · {{ projects.detail.name }}</span>
          <span class="text-xs text-slate-500">{{ STATUS_LABEL[projects.detail.status] }}</span>
        </header>
        <div class="grid gap-4 p-4 md:grid-cols-2">
          <dl>
            <div class="kv"><dt class="kv-key">预算</dt><dd class="kv-value">{{ formatMoney(projects.detail.budget_amount) }}</dd></div>
            <div class="kv"><dt class="kv-key">计划开工</dt><dd class="kv-value">{{ projects.detail.planned_start_date ?? "-" }}</dd></div>
            <div class="kv"><dt class="kv-key">计划完工</dt><dd class="kv-value">{{ projects.detail.planned_complete_date ?? "-" }}</dd></div>
            <div class="kv"><dt class="kv-key">客户</dt><dd class="kv-value">{{ projects.detail.customer.name }} · {{ projects.detail.customer.phone }}</dd></div>
            <div class="kv"><dt class="kv-key">房屋</dt><dd class="kv-value">{{ projects.detail.house.address }}</dd></div>
            <div class="kv"><dt class="kv-key">面积 / 户型</dt><dd class="kv-value">{{ projects.detail.house.area_sqm ?? "-" }} m² · {{ projects.detail.house.layout ?? "-" }}</dd></div>
          </dl>
          <div>
            <h4 class="mb-1 text-xs font-semibold text-slate-400">成员（{{ projects.detail.members.length }}）</h4>
            <table class="w-full">
              <thead>
                <tr class="border-b border-surface-line">
                  <th class="th text-left">成员</th>
                  <th class="th text-left">角色</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="member in projects.detail.members"
                  :key="member.user_id"
                  class="border-b border-surface-line/60"
                >
                  <td class="td">{{ member.full_name }} · {{ member.email }}</td>
                  <td class="td text-slate-500">{{ member.role }}</td>
                </tr>
              </tbody>
            </table>

            <div v-if="auth.canWriteProjects" class="mt-3 space-y-2">
              <select v-model="memberUserId" class="input" data-testid="member-user">
                <option value="">选择成员</option>
                <option v-for="user in reference.users" :key="user.id" :value="user.id">
                  {{ user.full_name }} · {{ user.email }}
                </option>
              </select>
              <div class="flex gap-2">
                <select v-model="memberRole" class="input" data-testid="member-role">
                  <option value="manager">manager</option>
                  <option value="member">member</option>
                  <option value="viewer">viewer</option>
                </select>
                <button type="button" class="btn" data-testid="add-member" @click="addMember">
                  添加成员
                </button>
              </div>
              <p v-if="memberMessage" class="text-xs text-slate-400" data-testid="member-message">
                {{ memberMessage }}
              </p>
            </div>
          </div>
        </div>
        <form
          v-if="canEditProject"
          class="space-y-2 border-t border-surface-line px-4 py-3"
          @submit.prevent="saveProject"
        >
          <h4 class="text-xs font-semibold text-slate-400">编辑项目（乐观锁）</h4>
          <div class="grid gap-2 md:grid-cols-2">
            <input v-model="editForm.name" class="input" placeholder="项目名称" data-testid="edit-name" />
            <select v-model="editForm.status" class="input" data-testid="edit-status">
              <option value="draft">草稿</option>
              <option value="active">进行中</option>
              <option value="on_hold">暂停</option>
              <option value="completed">已完成</option>
              <option value="cancelled">已取消</option>
            </select>
            <input v-model="editForm.budget_amount" class="input" placeholder="预算" />
            <input v-model="editForm.note" class="input" placeholder="备注" />
          </div>
          <div class="flex items-center gap-2">
            <button type="submit" class="btn btn-primary" data-testid="save-project">保存</button>
            <button type="button" class="btn" data-testid="delete-project" @click="removeProject">
              删除项目
            </button>
            <span v-if="editMessage" class="text-xs text-slate-400">{{ editMessage }}</span>
            <span v-if="editError" class="text-xs text-rose-300" data-testid="edit-error">{{ editError }}</span>
          </div>
        </form>

        <p v-if="projects.detail.note" class="border-t border-surface-line px-4 py-3 text-xs text-slate-500">
          {{ projects.detail.note }}
        </p>
      </article>
    </StatePanel>
  </section>
</template>
