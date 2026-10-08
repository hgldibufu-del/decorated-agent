<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";

import { useProjectsStore } from "@/stores/projects";
import { useReferenceStore } from "@/stores/reference";

const emit = defineEmits<{ created: [] }>();

const reference = useReferenceStore();
const projects = useProjectsStore();

const customerForm = reactive({ name: "", phone: "", email: "" });
const houseForm = reactive({ customer_id: "", address: "", area_sqm: "", layout: "" });
const projectForm = reactive({
  code: "",
  name: "",
  customer_id: "",
  house_id: "",
  budget_amount: "",
});
const message = ref<string | null>(null);
const error = ref<string | null>(null);

// 房屋必须属于所选客户：只列出该客户名下的房屋，避免选了就 400
const housesForCustomer = computed(() =>
  reference.houses.filter((house) => house.customer_id === projectForm.customer_id),
);

function errText(value: unknown): string {
  return value instanceof Error ? value.message : String(value);
}

onMounted(async () => {
  if (reference.state === "idle") await reference.load();
});

async function submitCustomer(): Promise<void> {
  error.value = null;
  try {
    const created = await reference.addCustomer({
      name: customerForm.name,
      phone: customerForm.phone,
      email: customerForm.email || null,
    });
    houseForm.customer_id = created.id;
    message.value = `客户已创建：${created.name}`;
    customerForm.name = "";
    customerForm.phone = "";
    customerForm.email = "";
    emit("created");
  } catch (err) {
    error.value = errText(err);
  }
}

async function submitHouse(): Promise<void> {
  error.value = null;
  try {
    const created = await reference.addHouse({
      customer_id: houseForm.customer_id,
      address: houseForm.address,
      area_sqm: houseForm.area_sqm || null,
      layout: houseForm.layout || null,
    });
    projectForm.customer_id = created.customer_id;
    projectForm.house_id = created.id;
    message.value = `房屋已创建：${created.address}`;
    houseForm.address = "";
    houseForm.area_sqm = "";
    houseForm.layout = "";
    emit("created");
  } catch (err) {
    error.value = errText(err);
  }
}

async function submitProject(): Promise<void> {
  error.value = null;
  const created = await projects.createProject({
    code: projectForm.code,
    name: projectForm.name,
    customer_id: projectForm.customer_id,
    house_id: projectForm.house_id,
    budget_amount: projectForm.budget_amount || null,
  });
  if (created) {
    message.value = `项目已创建：${created.code}`;
    projectForm.code = "";
    projectForm.name = "";
    projectForm.budget_amount = "";
    emit("created");
  } else {
    error.value = projects.errorMessage ?? "创建项目失败";
  }
}
</script>

<template>
  <article class="panel" data-testid="create-panel">
    <header class="panel-title">新建（客户 → 房屋 → 项目）</header>
    <div class="grid gap-4 p-4 md:grid-cols-3">
      <form class="space-y-2" @submit.prevent="submitCustomer">
        <h4 class="text-xs font-semibold text-slate-400">1. 新建客户</h4>
        <input v-model="customerForm.name" class="input" placeholder="客户姓名" data-testid="customer-name" />
        <input v-model="customerForm.phone" class="input" placeholder="手机号" data-testid="customer-phone" />
        <input v-model="customerForm.email" class="input" placeholder="邮箱（可选）" />
        <button type="submit" class="btn w-full" data-testid="create-customer">创建客户</button>
      </form>

      <form class="space-y-2" @submit.prevent="submitHouse">
        <h4 class="text-xs font-semibold text-slate-400">2. 新建房屋</h4>
        <select v-model="houseForm.customer_id" class="input" data-testid="house-customer">
          <option value="">选择客户</option>
          <option v-for="customer in reference.customers" :key="customer.id" :value="customer.id">
            {{ customer.name }} · {{ customer.phone }}
          </option>
        </select>
        <input v-model="houseForm.address" class="input" placeholder="房屋地址" data-testid="house-address" />
        <div class="flex gap-2">
          <input v-model="houseForm.area_sqm" class="input" placeholder="面积 m²" />
          <input v-model="houseForm.layout" class="input" placeholder="户型" />
        </div>
        <button type="submit" class="btn w-full" data-testid="create-house">创建房屋</button>
      </form>

      <form class="space-y-2" @submit.prevent="submitProject">
        <h4 class="text-xs font-semibold text-slate-400">3. 新建项目</h4>
        <input v-model="projectForm.code" class="input" placeholder="项目编号，如 GC-2026-100" data-testid="project-code" />
        <input v-model="projectForm.name" class="input" placeholder="项目名称" data-testid="project-name" />
        <select v-model="projectForm.customer_id" class="input" data-testid="project-customer">
          <option value="">选择客户</option>
          <option v-for="customer in reference.customers" :key="customer.id" :value="customer.id">
            {{ customer.name }}
          </option>
        </select>
        <select v-model="projectForm.house_id" class="input" data-testid="project-house">
          <option value="">选择房屋</option>
          <option v-for="house in housesForCustomer" :key="house.id" :value="house.id">
            {{ house.address }}
          </option>
        </select>
        <input v-model="projectForm.budget_amount" class="input" placeholder="预算（可选）" />
        <button type="submit" class="btn btn-primary w-full" data-testid="create-project">创建项目</button>
      </form>
    </div>

    <p v-if="message" class="border-t border-surface-line px-4 py-2 text-xs text-emerald-300" data-testid="create-message">
      {{ message }}
    </p>
    <p v-if="error" class="border-t border-surface-line px-4 py-2 text-xs text-rose-300" data-testid="create-error">
      {{ error }}
    </p>
  </article>
</template>
