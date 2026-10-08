import type { UserBrief } from "@/types/iam";
import type {
  Customer,
  CustomerCreate,
  CustomerUpdate,
  House,
  HouseCreate,
  HouseUpdate,
} from "@/types/project";
import type { ApiClient } from "./client";

export function listCustomers(client: ApiClient): Promise<Customer[]> {
  return client.getJson<Customer[]>("/v1/customers");
}

export function createCustomer(client: ApiClient, payload: CustomerCreate): Promise<Customer> {
  return client.postJson<Customer>("/v1/customers", payload);
}

export function listHouses(client: ApiClient, customerId?: string): Promise<House[]> {
  const query = customerId ? `?customer_id=${encodeURIComponent(customerId)}` : "";
  return client.getJson<House[]>(`/v1/houses${query}`);
}

export function createHouse(client: ApiClient, payload: HouseCreate): Promise<House> {
  return client.postJson<House>("/v1/houses", payload);
}

export function listUsers(client: ApiClient): Promise<UserBrief[]> {
  return client.getJson<UserBrief[]>("/v1/users");
}

export function updateCustomer(
  client: ApiClient,
  customerId: string,
  payload: CustomerUpdate,
): Promise<Customer> {
  return client.putJson<Customer>(`/v1/customers/${customerId}`, payload);
}

export function deleteCustomer(client: ApiClient, customerId: string): Promise<void> {
  return client.delete(`/v1/customers/${customerId}`);
}

export function updateHouse(
  client: ApiClient,
  houseId: string,
  payload: HouseUpdate,
): Promise<House> {
  return client.putJson<House>(`/v1/houses/${houseId}`, payload);
}

export function deleteHouse(client: ApiClient, houseId: string): Promise<void> {
  return client.delete(`/v1/houses/${houseId}`);
}
