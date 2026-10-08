<script setup lang="ts">
import { reactive, ref, watch } from "vue";

import { useReferenceStore } from "@/stores/reference";

const reference = useReferenceStore();

const selectedCustomerId = ref("");
const selectedHouseId = ref("");
const customerForm = reactive({ name: "", phone: "", email: "", note: "" });
const houseForm = reactive({ address: "", area_sqm: "", layout: "" });
const message = ref<string | null>(null);
const error = ref<string | null>(null);

watch(selectedCustomerId, (id) => {
  const customer = reference.customers.find((item) => item.id === id);
  if (customer) {
    customerForm.name = customer.name;
    customerForm.phone = customer.phone;
    customerForm.email = customer.email ?? "";
    customerForm.note = customer.note ?? "";
  }
});

watch(selectedHouseId, (id) => {
  const house = reference.houses.find((item) => item.id === id);
  if (house) {
    houseForm.address = house.address;
    houseForm.area_sqm = house.area_sqm ?? "";
    houseForm.layout = house.layout ?? "";
  }
});

async function saveCustomer(): Promise<void> {
  if (!selectedCustomerId.value) return;
  error.value = null;
  const updated = await reference.editCustomer(selectedCustomerId.value, {
    name: customerForm.name,
    phone: customerForm.phone,
    email: customerForm.email || null,
    note: customerForm.note || null,
  });
  message.value = updated ? `客户已更新：${updated.name}` : null;
  if (!updated) error.value = reference.errorMessage ?? "保存失败";
}

async function removeCustomer(): Promise<void> {
  if (!selectedCustomerId.value) return;
  error.value = null;
  const ok = await reference.removeCustomer(selectedCustomerId.value);
  if (ok) {
    message.value = "客户已删除";
    selectedCustomerId.value = "";
  } else {
    error.value = reference.errorMessage ?? "删除失败（可能名下仍有房屋）";
  }
}

async function saveHouse(): Promise<void> {
  if (!selectedHouseId.value) return;
  error.value = null;
  const updated = await reference.editHouse(selectedHouseId.value, {
    address: houseForm.address,
    area_sqm: houseForm.area_sqm || null,
    layout: houseForm.layout || null,
  });
  message.value = updated ? `房屋已更新：${updated.address}` : null;
  if (!updated) error.value = reference.errorMessage ?? "保存失败";
}

async function removeHouse(): Promise<void> {
  if (!selectedHouseId.value) return;
  error.value = null;
  const ok = await reference.removeHouse(selectedHouseId.value);
  if (ok) {
    message.value = "房屋已删除";
    selectedHouseId.value = "";
  } else {
    error.value = reference.errorMessage ?? "删除失败（可能仍被项目引用）";
  }
}
</script>

<template>
  <article class="panel" data-testid="reference-manage">
    <header class="panel-title">管理客户 / 房屋（编辑与删除）</header>
    <div class="grid gap-4 p-4 md:grid-cols-2">
      <form class="space-y-2" @submit.prevent="saveCustomer">
        <h4 class="text-xs font-semibold text-slate-400">客户</h4>
        <select v-model="selectedCustomerId" class="input" data-testid="manage-customer-select">
          <option value="">选择客户</option>
          <option v-for="customer in reference.customers" :key="customer.id" :value="customer.id">
            {{ customer.name }} · {{ customer.phone }}
          </option>
        </select>
        <input v-model="customerForm.name" class="input" placeholder="姓名" />
        <input v-model="customerForm.phone" class="input" placeholder="手机号" />
        <input v-model="customerForm.email" class="input" placeholder="邮箱" />
        <input v-model="customerForm.note" class="input" placeholder="备注" />
        <div class="flex gap-2">
          <button type="submit" class="btn btn-primary" :disabled="!selectedCustomerId" data-testid="save-customer">
            保存客户
          </button>
          <button type="button" class="btn" :disabled="!selectedCustomerId" data-testid="delete-customer" @click="removeCustomer">
            删除客户
          </button>
        </div>
      </form>

      <form class="space-y-2" @submit.prevent="saveHouse">
        <h4 class="text-xs font-semibold text-slate-400">房屋</h4>
        <select v-model="selectedHouseId" class="input" data-testid="manage-house-select">
          <option value="">选择房屋</option>
          <option v-for="house in reference.houses" :key="house.id" :value="house.id">
            {{ house.address }}
          </option>
        </select>
        <input v-model="houseForm.address" class="input" placeholder="地址" />
        <input v-model="houseForm.area_sqm" class="input" placeholder="面积 m²" />
        <input v-model="houseForm.layout" class="input" placeholder="户型" />
        <div class="flex gap-2">
          <button type="submit" class="btn btn-primary" :disabled="!selectedHouseId" data-testid="save-house">
            保存房屋
          </button>
          <button type="button" class="btn" :disabled="!selectedHouseId" data-testid="delete-house" @click="removeHouse">
            删除房屋
          </button>
        </div>
      </form>
    </div>

    <p v-if="message" class="border-t border-surface-line px-4 py-2 text-xs text-emerald-300" data-testid="manage-message">
      {{ message }}
    </p>
    <p v-if="error" class="border-t border-surface-line px-4 py-2 text-xs text-rose-300" data-testid="manage-error">
      {{ error }}
    </p>
  </article>
</template>
