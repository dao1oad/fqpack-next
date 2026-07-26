<template>
  <section class="sq-card" data-testid="sq-heatmap">
    <div class="sq-card__header">
      <div><span class="sq-card__kicker">信号质量基准</span><h3>18 模型 × 触发语义 · 5 日超额收益热力图</h3></div>
      <div class="sq-card__controls">
        <el-select :model-value="metric" size="small" style="width: 170px" aria-label="热力图指标" @change="$emit('update:metric', $event)">
          <el-option v-for="option in metricOptions" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
      </div>
    </div>
    <ClxChart :option="option" :loading="loading" :empty="!cells.length" height="480px" empty-text="当前筛选下暂无信号统计" />
    <div class="sq-card__footnote">主指标为 T+1 开盘入场、持有 5 个交易日的开盘-开盘超额收益（相对上证指数）。悬停可查看可执行样本数与 FDR q 值。</div>
  </section>
</template>

<script setup>
import { computed } from "vue";
import ClxChart from "@/components/clx-backtest/ClxChart.vue";

const props = defineProps({
  cells: { type: Array, required: true },
  splitId: { type: String, default: "TRAIN" },
  loading: { type: Boolean, default: false },
  metric: { type: String, default: "meanExcess" },
});
defineEmits(["update:metric"]);

const modelIds = Array.from({ length: 18 }, (_, index) => `S${String(index).padStart(4, "0")}`);
const metricOptions = [
  { label: "平均超额收益", value: "meanExcess" },
  { label: "扣费净超额", value: "netMeanExcess" },
  { label: "胜率", value: "winRate" },
  { label: "FDR q 值", value: "fdrQValue" },
  { label: "信息比率", value: "informationRatio" },
  { label: "可执行样本数", value: "nExecutable" },
];
const percentMetrics = new Set(["meanExcess", "netMeanExcess", "winRate"]);

const triggerKeys = computed(() => [...new Set(props.cells.map((cell) => cell.trigger).filter(Boolean))].sort());
const cellLookup = computed(() => new Map(props.cells.map((cell) => [`${cell.modelCode}|${cell.trigger}`, cell])));

const values = computed(() => modelIds.flatMap((modelCode, y) => triggerKeys.value.map((trigger, x) => {
  const cell = cellLookup.value.get(`${modelCode}|${trigger}`);
  const stats = cell?.splits?.[props.splitId];
  const value = stats ? stats[props.metric] : null;
  return [x, y, value ?? null, stats?.nExecutable ?? 0, stats?.fdrQValue ?? null, cell?.qualification?.status ?? ""];
})));

const finiteValues = computed(() => values.value.map((item) => item[2]).filter((value) => value !== null && Number.isFinite(value)));
const bound = computed(() => Math.max(...finiteValues.value.map(Math.abs), 1e-4));
const isDiverging = computed(() => !["fdrQValue", "nExecutable", "winRate"].includes(props.metric));

const formatValue = (value) => {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "无样本";
  if (percentMetrics.has(props.metric)) return `${(Number(value) * 100).toFixed(2)}%`;
  if (props.metric === "nExecutable") return Number(value).toLocaleString("zh-CN");
  return Number(value).toFixed(4);
};

const option = computed(() => ({
  animation: false,
  backgroundColor: "transparent",
  grid: { left: 72, right: 30, top: 22, bottom: 96 },
  tooltip: {
    confine: true,
    formatter: (params) => {
      const [x, y, value, sample, q, status] = params.data;
      const qText = q === null || q === undefined ? "-" : Number(q).toFixed(4);
      return `<b>${modelIds[y]} · ${triggerKeys.value[x]}</b><br/>${formatValue(value)}<br/>可执行样本：${Number(sample).toLocaleString("zh-CN")}<br/>FDR q：${qText}<br/>判定：${status || "-"}`;
    },
  },
  xAxis: {
    type: "category",
    data: triggerKeys.value,
    splitArea: { show: true },
    axisLabel: { color: "#a6adc8", rotate: 32, fontSize: 10, interval: 0 },
    axisLine: { lineStyle: { color: "#45475a" } },
  },
  yAxis: {
    type: "category",
    data: modelIds,
    splitArea: { show: true },
    axisLabel: { color: "#bac2de", fontFamily: "monospace", fontSize: 10 },
    axisLine: { lineStyle: { color: "#45475a" } },
  },
  visualMap: {
    min: isDiverging.value ? -bound.value : 0,
    max: props.metric === "winRate" ? 1 : bound.value,
    calculable: true,
    orient: "horizontal",
    left: "center",
    bottom: 8,
    textStyle: { color: "#a6adc8" },
    inRange: {
      color: isDiverging.value
        ? ["#94e2d5", "#313244", "#f38ba8"]
        : ["#313244", "#89b4fa", "#f38ba8"],
    },
  },
  series: [{
    type: "heatmap",
    data: values.value,
    emphasis: { itemStyle: { shadowBlur: 8, shadowColor: "rgba(137,180,250,.6)" } },
    itemStyle: { borderColor: "#1e1e2e", borderWidth: 1 },
  }],
}));
</script>

<style scoped>
.sq-card { background: var(--fq-panel-bg); border: 1px solid var(--fq-border-soft); border-radius: 10px; padding: 16px; min-width: 0; }
.sq-card__header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.sq-card__header h3 { margin: 3px 0 0; font-size: 14px; }
.sq-card__kicker { color: var(--fq-text-muted); font-size: 10px; letter-spacing: .08em; text-transform: uppercase; }
.sq-card__controls { display: flex; align-items: center; gap: 8px; }
.sq-card__footnote { font-size: 11px; color: var(--fq-text-muted); border-top: 1px solid var(--fq-border-soft); padding-top: 9px; margin-top: 8px; }
@media (max-width: 640px) { .sq-card__header { align-items: flex-start; flex-direction: column; } }
</style>
