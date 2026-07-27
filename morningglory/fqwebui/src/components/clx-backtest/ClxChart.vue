<template>
  <div v-loading="loading" class="clx-chart-shell" :style="{ height }" :aria-busy="loading">
    <div ref="chartEl" class="clx-chart" data-testid="clx-chart" />
    <el-empty v-if="!loading && empty" class="clx-chart__state" :image-size="48" :description="emptyText" />
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as echarts from "echarts";
const props = defineProps({
  option: { type: Object, required: true },
  height: { type: String, default: "320px" },
  loading: { type: Boolean, default: false },
  empty: { type: Boolean, default: false },
  emptyText: { type: String, default: "暂无可绘制数据" },
});
const chartEl = ref(null);
let chart = null;
let observer = null;
function render() {
  if (!chartEl.value || props.empty || props.loading) {
    chart?.clear();
    return;
  }
  if (!chart) chart = echarts.init(chartEl.value, void 0, { renderer: "canvas" });
  chart.setOption(props.option, { notMerge: true, lazyUpdate: true });
  chart.resize();
}
onMounted(async () => {
  await nextTick();
  render();
  if (chartEl.value && typeof ResizeObserver !== "undefined") {
    observer = new ResizeObserver(() => chart?.resize());
    observer.observe(chartEl.value);
  }
});
watch(() => [props.option, props.empty, props.loading], async () => {
  await nextTick();
  render();
}, { deep: true });
onBeforeUnmount(() => {
  observer?.disconnect();
  chart?.dispose();
  chart = null;
});
</script>

<style scoped>
.clx-chart-shell {
  position: relative;
  width: 100%;
  min-height: 180px;
}
.clx-chart { width: 100%; height: 100%; }
.clx-chart__state {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--fq-text-muted);
  background: color-mix(in srgb, var(--fq-panel-bg) 86%, transparent);
}
</style>
