<template>
  <section class="clx-card" data-testid="performance-charts">
    <div class="clx-card__header">
      <div>
        <span class="clx-card__kicker">组合表现</span>
        <h3>净值、回撤与年度收益</h3>
      </div>
      <el-tag size="small" effect="plain">{{ splitLabel }}</el-tag>
    </div>
    <ClxChart :option="option" :loading="loading" :empty="!points.length" height="520px" empty-text="该组合暂无资金曲线" />
  </section>
</template>

<script setup>
import { computed } from "vue";
import ClxChart from "./ClxChart.vue";
const props = defineProps({
  points: { type: Array, required: true },
  loading: { type: Boolean, default: false },
  splitId: { type: String, default: "VALIDATION" },
  seriesName: { type: String, default: "组合净值" },
});
const splitLabel = computed(() => ({ TRAIN: "\u7814\u7A76\u96C6", VALIDATION: "\u9A8C\u8BC1\u96C6", HOLDOUT: "\u9501\u5B9A\u6D4B\u8BD5\u96C6" })[props.splitId] ?? props.splitId);
const normalizedEquity = computed(() => {
  const first = props.points.find((point) => Number.isFinite(point.equity))?.equity || 1;
  return props.points.map((point) => point.equity / first);
});
const normalizedBenchmark = computed(() => {
  const first = props.points.find((point) => Number.isFinite(Number(point.benchmark)))?.benchmark;
  return props.points.map((point) => first && point.benchmark !== null && point.benchmark !== void 0 ? point.benchmark / first : null);
});
const drawdowns = computed(() => {
  let peak = -Infinity;
  return props.points.map((point, index) => {
    if (point.drawdown !== null && point.drawdown !== void 0) return point.drawdown;
    const value = normalizedEquity.value[index];
    peak = Math.max(peak, value);
    return peak ? value / peak - 1 : 0;
  });
});
const annual = computed(() => {
  const grouped = /* @__PURE__ */ new Map();
  props.points.forEach((point, index) => {
    const year = point.date.slice(0, 4);
    if (!year) return;
    const values = grouped.get(year) ?? [];
    values.push(normalizedEquity.value[index]);
    grouped.set(year, values);
  });
  return [...grouped].map(([year, values]) => ({ year, value: values.length > 1 ? values.at(-1) / values[0] - 1 : 0 }));
});
const percent = (value) => `${(Number(value) * 100).toFixed(2)}%`;
const option = computed(() => ({
  animationDuration: 350,
  backgroundColor: "transparent",
  color: ["#89b4fa", "#f9e2af", "#f38ba8"],
  tooltip: { trigger: "axis", confine: true, valueFormatter: (value) => Number(value).toFixed(4) },
  legend: { top: 0, right: 8, textStyle: { color: "#a6adc8" }, data: [props.seriesName, "\u57FA\u51C6"] },
  axisPointer: { link: [{ xAxisIndex: [0, 1] }] },
  grid: [
    { left: 58, right: 24, top: 38, height: "42%" },
    { left: 58, right: 24, top: "56%", height: "14%" },
    { left: 58, right: 24, top: "77%", bottom: 32 }
  ],
  xAxis: [
    { type: "category", data: props.points.map((point) => point.date), boundaryGap: false, axisLabel: { show: false }, axisLine: { lineStyle: { color: "#45475a" } } },
    { type: "category", gridIndex: 1, data: props.points.map((point) => point.date), boundaryGap: false, axisLabel: { color: "#6c7086", fontSize: 9 }, axisLine: { lineStyle: { color: "#45475a" } } },
    { type: "category", gridIndex: 2, data: annual.value.map((point) => point.year), axisLabel: { color: "#a6adc8" }, axisLine: { lineStyle: { color: "#45475a" } } }
  ],
  yAxis: [
    { type: "value", scale: true, axisLabel: { color: "#a6adc8", formatter: (value) => value.toFixed(2) }, splitLine: { lineStyle: { color: "rgba(255,255,255,.05)" } } },
    { type: "value", gridIndex: 1, max: 0, axisLabel: { color: "#a6adc8", formatter: percent }, splitLine: { lineStyle: { color: "rgba(255,255,255,.05)" } } },
    { type: "value", gridIndex: 2, axisLabel: { color: "#a6adc8", formatter: percent }, splitLine: { lineStyle: { color: "rgba(255,255,255,.05)" } } }
  ],
  series: [
    { name: props.seriesName, type: "line", showSymbol: false, data: normalizedEquity.value, lineStyle: { width: 2 }, areaStyle: { opacity: 0.08 } },
    { name: "\u57FA\u51C6", type: "line", showSymbol: false, data: normalizedBenchmark.value, lineStyle: { width: 1, type: "dashed" } },
    { name: "\u56DE\u64A4", type: "line", xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, data: drawdowns.value, lineStyle: { color: "#f38ba8", width: 1 }, areaStyle: { color: "#f38ba8", opacity: 0.22 }, tooltip: { valueFormatter: percent } },
    { name: "\u5E74\u5EA6\u6536\u76CA", type: "bar", xAxisIndex: 2, yAxisIndex: 2, data: annual.value.map((point) => ({ value: point.value, itemStyle: { color: point.value >= 0 ? "#f38ba8" : "#94e2d5" } })), tooltip: { valueFormatter: percent } }
  ]
}));
</script>

<style scoped>
.clx-card { background: var(--fq-panel-bg); border: 1px solid var(--fq-border-soft); border-radius: 10px; padding: 16px; min-width: 0; }
.clx-card__header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.clx-card__header h3 { margin: 3px 0 0; font-size: 14px; }
.clx-card__kicker { color: var(--fq-text-muted); font-size: 10px; letter-spacing: .08em; }
</style>