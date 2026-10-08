import { defineStore } from "pinia";

import { ApiClient } from "@/api/client";
import {
  addProjectMember as addMemberApi,
  createProject as createProjectApi,
  deleteProject as deleteProjectApi,
  getProject,
  listProjects,
  updateProject as updateProjectApi,
} from "@/api/projects";
import type {
  ProjectCreate,
  ProjectDetail,
  ProjectMember,
  ProjectRole,
  ProjectSummary,
  ProjectUpdate,
} from "@/types/project";
import type { LoadState } from "@/types/ui";

interface ProjectsState {
  items: ProjectSummary[];
  detail: ProjectDetail | null;
  state: LoadState;
  detailState: LoadState;
  errorMessage: string | null;
  errorCode: string | null;
  retryable: boolean;
  permissionDenied: boolean;
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export const useProjectsStore = defineStore("projects", {
  state: (): ProjectsState => ({
    items: [],
    detail: null,
    state: "idle",
    detailState: "idle",
    errorMessage: null,
    errorCode: null,
    retryable: false,
    permissionDenied: false,
  }),

  getters: {
    isLoading: (state): boolean => state.state === "loading",
    isEmpty: (state): boolean => state.state === "ready" && state.items.length === 0,
  },

  actions: {
    async load(client: ApiClient = new ApiClient()): Promise<void> {
      this.state = "loading";
      this.errorMessage = null;
      this.errorCode = null;
      this.retryable = false;
      this.permissionDenied = false;
      try {
        this.items = await listProjects(client);
        this.state = "ready";
      } catch (error) {
        this.items = [];
        this.state = "error";
        this.errorCode = (error as { code?: string }).code ?? "UNKNOWN";
        this.errorMessage = messageOf(error);
        this.retryable = Boolean((error as { retryable?: boolean }).retryable);
        this.permissionDenied = Boolean((error as { isPermissionDenied?: boolean }).isPermissionDenied);
      }
    },

    async loadDetail(projectId: string, client: ApiClient = new ApiClient()): Promise<void> {
      this.detailState = "loading";
      this.errorMessage = null;
      this.errorCode = null;
      try {
        this.detail = await getProject(client, projectId);
        this.detailState = "ready";
      } catch (error) {
        this.detail = null;
        this.detailState = "error";
        this.errorCode = (error as { code?: string }).code ?? "UNKNOWN";
        this.errorMessage = messageOf(error);
        this.retryable = Boolean((error as { retryable?: boolean }).retryable);
        this.permissionDenied = Boolean((error as { isPermissionDenied?: boolean }).isPermissionDenied);
      }
    },

    /** 新建项目（创建者自动成为 owner）；成功后刷新列表。 */
    async createProject(
      payload: ProjectCreate, client: ApiClient = new ApiClient()
    ): Promise<ProjectDetail | null> {
      this.errorMessage = null;
      this.errorCode = null;
      try {
        const detail = await createProjectApi(client, payload);
        this.detail = detail;
        this.detailState = "ready";
        await this.load(client);
        return detail;
      } catch (error) {
        this.errorCode = (error as { code?: string }).code ?? "UNKNOWN";
        this.errorMessage = messageOf(error);
        this.retryable = Boolean((error as { retryable?: boolean }).retryable);
        this.permissionDenied = Boolean((error as { isPermissionDenied?: boolean }).isPermissionDenied);
        return null;
      }
    },

    /** 编辑项目（乐观锁）：版本冲突时返回 null，`errorCode` 为 CONFLICT。 */
    async updateProject(
      projectId: string, payload: ProjectUpdate, client: ApiClient = new ApiClient()
    ): Promise<ProjectDetail | null> {
      this.errorMessage = null;
      this.errorCode = null;
      try {
        const detail = await updateProjectApi(client, projectId, payload);
        this.detail = detail;
        await this.load(client);
        return detail;
      } catch (error) {
        this.errorCode = (error as { code?: string }).code ?? "UNKNOWN";
        this.errorMessage = messageOf(error);
        this.retryable = Boolean((error as { retryable?: boolean }).retryable);
        this.permissionDenied = Boolean((error as { isPermissionDenied?: boolean }).isPermissionDenied);
        return null;
      }
    },

    /** 删除项目；被 Run / 施工记录引用时返回 false（errorCode=CONFLICT）。 */
    async removeProject(projectId: string, client: ApiClient = new ApiClient()): Promise<boolean> {
      this.errorMessage = null;
      this.errorCode = null;
      try {
        await deleteProjectApi(client, projectId);
        this.detail = null;
        this.detailState = "idle";
        await this.load(client);
        return true;
      } catch (error) {
        this.errorCode = (error as { code?: string }).code ?? "UNKNOWN";
        this.errorMessage = messageOf(error);
        this.retryable = Boolean((error as { retryable?: boolean }).retryable);
        this.permissionDenied = Boolean((error as { isPermissionDenied?: boolean }).isPermissionDenied);
        return false;
      }
    },

    /** 新增或更新项目成员；成功后就地刷新详情里的成员列表。 */
    async addMember(
      projectId: string,
      userId: string,
      role: ProjectRole,
      client: ApiClient = new ApiClient(),
    ): Promise<ProjectMember[] | null> {
      this.errorMessage = null;
      this.errorCode = null;
      try {
        const members = await addMemberApi(client, projectId, { user_id: userId, role });
        if (this.detail) {
          this.detail = { ...this.detail, members };
        }
        return members;
      } catch (error) {
        this.errorCode = (error as { code?: string }).code ?? "UNKNOWN";
        this.errorMessage = messageOf(error);
        this.retryable = Boolean((error as { retryable?: boolean }).retryable);
        this.permissionDenied = Boolean((error as { isPermissionDenied?: boolean }).isPermissionDenied);
        return null;
      }
    },
  },
});
