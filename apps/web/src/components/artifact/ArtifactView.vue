<script setup lang="ts">
import { computed } from "vue";

import { ARTIFACT_LABELS, type ArtifactOut } from "@/types/agent";
import type {
  AftersalesPayload,
  ConstructionPayload,
  DesignPayload,
  ProjectSnapshotPayload,
  QuotePayload,
} from "@/types/artifact";

import AftersalesArtifact from "./AftersalesArtifact.vue";
import ConstructionArtifact from "./ConstructionArtifact.vue";
import DesignArtifact from "./DesignArtifact.vue";
import ProjectSnapshotArtifact from "./ProjectSnapshotArtifact.vue";
import QuoteArtifact from "./QuoteArtifact.vue";
import RawArtifact from "./RawArtifact.vue";

const props = defineProps<{ artifact: ArtifactOut }>();

const type = computed(() => props.artifact.artifact_type);
const label = computed(() => ARTIFACT_LABELS[type.value] ?? type.value);

// 各分支的 payload 形状由后端 SkillRunner 保证；这里只做类型收窄，不做运行时兜底。
const snapshot = computed(() => props.artifact.payload as unknown as ProjectSnapshotPayload);
const aftersales = computed(() => props.artifact.payload as unknown as AftersalesPayload);
const quote = computed(() => props.artifact.payload as unknown as QuotePayload);
const design = computed(() => props.artifact.payload as unknown as DesignPayload);
const construction = computed(() => props.artifact.payload as unknown as ConstructionPayload);
</script>

<template>
  <article class="panel" data-testid="artifact-card">
    <header class="panel-title flex items-center justify-between">
      <span>{{ label }}</span>
      <span class="font-mono text-xs text-slate-500">
        {{ props.artifact.producer }} · v{{ props.artifact.version }}
      </span>
    </header>
    <div class="p-4">
      <ProjectSnapshotArtifact v-if="type === 'project_snapshot'" :payload="snapshot" />
      <AftersalesArtifact v-else-if="type === 'aftersales_diagnosis'" :payload="aftersales" />
      <QuoteArtifact v-else-if="type === 'quote_estimate'" :payload="quote" />
      <DesignArtifact v-else-if="type === 'design_proposal'" :payload="design" />
      <ConstructionArtifact v-else-if="type === 'construction_review'" :payload="construction" />
      <RawArtifact v-else :payload="props.artifact.payload" />
    </div>
  </article>
</template>
