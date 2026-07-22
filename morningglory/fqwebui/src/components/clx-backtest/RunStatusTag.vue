<template>
  <el-tag :type="meta.type" size="small" effect="plain" round>
    <span v-if="status === 'RUNNING' || status === 'QUEUED'" class="clx-status-dot" />
    {{ meta.label }}
  </el-tag>
</template>

<script setup>
import { computed } from "vue";
import { runStatusMeta } from "@/utils/clxFormat";
const props = defineProps({ status: { type: String, required: true } });
const meta = computed(() => {
  const value = runStatusMeta[props.status] ?? { label: props.status, type: "info" };
  return { ...value, type: value.type === "error" ? "danger" : value.type === "default" ? "info" : value.type };
});
</script>

<style scoped>
.clx-status-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-right: 5px;
  background: currentColor;
  animation: clx-pulse 1.6s ease-in-out infinite;
}
@keyframes clx-pulse { 50% { opacity: .35; } }
</style>