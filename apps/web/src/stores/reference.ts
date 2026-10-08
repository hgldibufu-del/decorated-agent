import { defineStore } from "pinia";

import { ApiClient } from "@/api/client";
import {
  createCustomer,
  createHouse,
  deleteCustomer as deleteCustomerApi,
  deleteHouse as deleteHouseApi,
  listCustomers,
  listHouses,
  listUsers,
  updateCustomer as updateCustomerApi,
  updateHouse as updateHouseApi,
} from "@/api/reference";
import type { UserBrief } from "@/types/iam";
import type {
  Customer,
  CustomerCreate,
  CustomerUpdate,
  House,
  HouseCreate,
  HouseUpdate,
} from "@/types/project";
import type { LoadState } from "@/types/ui";

interface ReferenceState {
  customers: Customer[];
  houses: House[];
  users: UserBrief[];
  state: LoadState;
  errorMessage: string | null;
  errorCode: string | null;
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * 参考数据（客户 / 房屋 / 成员候选）。
 *
 * 这些数据只服务于「新建项目」与「添加成员」，后端要求 `project:write`；
 * 前端在无权限时不展示相关入口，避免出现点了就 403 的死路。
 */
export const useReferenceStore = defineStore("reference", {
  state: (): ReferenceState => ({
    customers: [],
    houses: [],
    users: [],
    state: "idle",
    errorMessage: null,
    errorCode: null,
  }),

  getters: {
    isLoading: (state): boolean => state.state === "loading",
  },

  actions: {
    async load(client: ApiClient = new ApiClient()): Promise<void> {
      this.state = "loading";
      this.errorMessage = null;
      this.errorCode = null;
      try {
        const [customers, houses, users] = await Promise.all([
          listCustomers(client),
          listHouses(client),
          listUsers(client),
        ]);
        this.customers = customers;
        this.houses = houses;
        this.users = users;
        this.state = "ready";
      } catch (error) {
        this.state = "error";
        this.errorCode = (error as { code?: string }).code ?? "UNKNOWN";
        this.errorMessage = messageOf(error);
      }
    },

    async addCustomer(payload: CustomerCreate, client: ApiClient = new ApiClient()): Promise<Customer> {
      const created = await createCustomer(client, payload);
      this.customers = [created, ...this.customers];
      return created;
    },

    async addHouse(payload: HouseCreate, client: ApiClient = new ApiClient()): Promise<House> {
      const created = await createHouse(client, payload);
      this.houses = [created, ...this.houses];
      return created;
    },

    async editCustomer(
      customerId: string, payload: CustomerUpdate, client: ApiClient = new ApiClient()
    ): Promise<Customer | null> {
      this.errorMessage = null;
      this.errorCode = null;
      try {
        const updated = await updateCustomerApi(client, customerId, payload);
        this.customers = this.customers.map((item) =>
          item.id === customerId ? updated : item,
        );
        return updated;
      } catch (error) {
        this.applyError(error);
        return null;
      }
    },

    async removeCustomer(customerId: string, client: ApiClient = new ApiClient()): Promise<boolean> {
      this.errorMessage = null;
      this.errorCode = null;
      try {
        await deleteCustomerApi(client, customerId);
        this.customers = this.customers.filter((item) => item.id !== customerId);
        return true;
      } catch (error) {
        this.applyError(error);
        return false;
      }
    },

    async editHouse(
      houseId: string, payload: HouseUpdate, client: ApiClient = new ApiClient()
    ): Promise<House | null> {
      this.errorMessage = null;
      this.errorCode = null;
      try {
        const updated = await updateHouseApi(client, houseId, payload);
        this.houses = this.houses.map((item) => (item.id === houseId ? updated : item));
        return updated;
      } catch (error) {
        this.applyError(error);
        return null;
      }
    },

    async removeHouse(houseId: string, client: ApiClient = new ApiClient()): Promise<boolean> {
      this.errorMessage = null;
      this.errorCode = null;
      try {
        await deleteHouseApi(client, houseId);
        this.houses = this.houses.filter((item) => item.id !== houseId);
        return true;
      } catch (error) {
        this.applyError(error);
        return false;
      }
    },

    applyError(error: unknown): void {
      this.errorCode = (error as { code?: string }).code ?? "UNKNOWN";
      this.errorMessage = messageOf(error);
    },
  },
});
