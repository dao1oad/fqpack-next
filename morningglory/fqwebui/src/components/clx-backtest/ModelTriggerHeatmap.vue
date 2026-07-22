<template>
  <section class="clx-card workbench-panel" data-testid="model-trigger-heatmap">
    <div class="clx-card__header"><div><span class="clx-card__kicker">单模型诊断</span><h3>18 模型 × 主触发热力图</h3></div><el-select :model-value="metric" size="small" style="width: 150px" aria-label="热力图指标" @change="$emit('update:metric', $event)"><el-option v-for="option in metricOptions" :key="option.value" :label="option.label" :value="option.value" /></el-select></div>
    <ClxChart :option="option" :loading="loading" :empty="!cells.length" height="430px" empty-text="当前筛选下暂无模型触发统计" />
    <div class="clx-card__footnote">颜色仅表示所选样本段的统计量；悬停可查看样本数。选择组合仍以验证集、FDR 与稳定性共同判断。</div>
  </section>
</template>

<script setup>
import { computed } from "vue";
import ClxChart from "./ClxChart.vue";
const props = defineProps({
  cells: { type: Array, required: true },
  loading: { type: Boolean, default: false },
  metric: { type: String, default: "mean_return" },
});
defineEmits(["update:metric"]);
const modelIds = Array.from({ length: 18 }, (_, index) => `S${String(index).padStart(4, "0")}`);
const metricOptions = [
  { label: "\u5E73\u5747\u6536\u76CA", value: "mean_return" },
  { label: "\u80DC\u7387", value: "win_rate" },
  { label: "Sharpe", value: "sharpe" },
  { label: "\u6700\u5927\u56DE\u64A4", value: "max_drawdown" },
  { label: "\u6837\u672C\u6570", value: "sample_count" },
  { label: "\u7EFC\u5408\u5F97\u5206", value: "score" }
];
const triggerKeys = computed(() => [...new Set(props.cells.map((cell) => cell.trigger).filter(Boolean))].sort());
const cellLookup = computed(() => new Map(props.cells.map((cell) => [`${cell.modelId}|${cell.trigger}`, cell])));
const values = computed(() => modelIds.flatMap((modelId, y) => triggerKeys.value.map((trigger, x) => {
  const cell = cellLookup.value.get(`${modelId}|${trigger}`);
  return [x, y, cell?.value ?? null, cell?.sampleCount ?? 0];
})));
const finiteValues = computed(() => props.cells.map((item) => item.value).filter((value) => value !== null && Number.isFinite(value)));
const bound = computed(() => Math.max(...finiteValues.value.map(Math.abs), 0.01));
const percentageMetric = computed(() => ["mean_return", "win_rate", "max_drawdown"].includes(props.metric));
const formatValue = (value) => {
  if (value === null || value === void 0 || !Number.isFinite(Number(value))) return "\u65E0\u6837\u672C";
  return percentageMetric.value ? `${(Number(value) * 100).toFixed(2)}%` : Number(value).toFixed(3);
};
const option = computed(() => ({
  animation: false,
  backgroundColor: "transparent",
  grid: { left: 72, right: 30, top: 22, bottom: 96 },
  tooltip: {
    confine: true,
    formatter: (params) => {
      const [x, y, value, sample] = params.data;
      return `<b>${modelIds[y]} \xB7 ${triggerKeys.value[x]}</b><br/>${formatValue(value)}<br/>\u6837\u672C\u6570\uFF1A${Number(sample).toLocaleString("zh-CN")}`;
    }
  },
  xAxis: {
    type: "category",
    data: triggerKeys.value,
    splitArea: { show: true },
    axisLabel: { color: "#a6adc8", rotate: 32, fontSize: 10, interval: 0 },
    axisLine: { lineStyle: { color: "#45475a" } }
  },
  yAxis: {
    type: "category",
    data: modelIds,
    splitArea: { show: true },
    axisLabel: { color: "#bac2de", fontFamily: "monospace", fontSize: 10 },
    axisLine: { lineStyle: { color: "#45475a" } }
  },
  visualMap: {
    min: -bound.value,
    max: bound.value,
    calculable: true,
    orient: "horizontal",
    left: "center",
    bottom: 8,
    textStyle: { color: "#a6adc8" },
    inRange: { color: ["#94e2d5", "#313244", "#f38ba8"] }
  },
  series: [{
    type: "heatmap",
    data: values.value,
    emphasis: { itemStyle: { shadowBlur: 8, shadowColor: "rgba(137,180,250,.6)" } },
    itemStyle: { borderColor: "#1e1e2e", borderWidth: 1 }
  }]
}));
</script>

<style scoped>
.clx-card { background: var(--fq-panel-bg); border: 1px solid var(--fq-border-soft); border-radius: 10px; padding: 16px; min-width: 0; }
.clx-card__header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.clx-card__header h3 { margin: 3px 0 0; font-size: 14px; }
.clx-card__kicker { color: var(--fq-text-muted); font-size: 10px; letter-spacing: .08em; text-transform: uppercase; }
.clx-card__footnote { font-size: 11px; color: var(--fq-text-muted); border-top: 1px solid var(--fq-border-soft); padding-top: 9px; }
@media (max-width: 640px) { .clx-card__header { align-items: flex-start; flex-direction: column; } }
</style>