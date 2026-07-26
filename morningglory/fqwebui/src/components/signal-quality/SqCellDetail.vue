<template>
  <el-drawer :model-value="Boolean(cell)" size="620px" :title="title" @close="$emit('close')">
    <div v-if="cell" class="sq-detail" data-testid="sq-cell-detail">
      <div class="sq-detail__badges">
        <el-tag :type="statusType" effect="dark">{{ cell.qualification.status }}</el-tag>
        <el-tag effect="plain">{{ cell.direction === 1 ? '买入方向' : '卖出方向（仅预测性评估）' }}</el-tag>
      </div>

      <h4>分割对比（5 日超额收益）</h4>
      <el-table :data="splitRows" size="small">
        <el-table-column prop="split" label="分割" width="110" />
        <el-table-column label="样本" width="90" align="right"><template #default="{ row }">{{ row.nExecutable.toLocaleString('zh-CN') }}</template></el-table-column>
        <el-table-column label="执行率" width="80" align="right"><template #default="{ row }">{{ percent(row.executionRate) }}</template></el-table-column>
        <el-table-column label="均值" width="90" align="right"><template #default="{ row }">{{ percent(row.meanExcess) }}</template></el-table-column>
        <el-table-column label="净均值" width="90" align="right"><template #default="{ row }">{{ percent(row.netMeanExcess) }}</template></el-table-column>
        <el-table-column label="胜率" width="80" align="right"><template #default="{ row }">{{ percent(row.winRate) }}</template></el-table-column>
        <el-table-column label="FDR q" align="right"><template #default="{ row }">{{ fixed(row.fdrQValue, 4) }}</template></el-table-column>
      </el-table>
      <p v-if="hasHoldout" class="sq-detail__warning">⚠️ HOLDOUT 仅作确认用途，不参与任何选择；且本轮 HOLDOUT 在历史 run 中已被揭示过一次，应视为受污染的参考值。</p>

      <h4>年度稳定性（{{ splitId }}）</h4>
      <ClxChart :option="yearlyOption" :empty="!yearlyEntries.length" height="220px" empty-text="样本不足，未产生年度统计" />

      <h4>持有期衰减曲线（1/3/5/10/20 日）</h4>
      <ClxChart :option="decayOption" :empty="!decayEntries.length" height="220px" empty-text="样本不足，未产生衰减统计" />

      <h4>随机对照（{{ splitId }}）</h4>
      <el-table :data="controlRows" size="small">
        <el-table-column prop="name" label="对照" min-width="150" />
        <el-table-column label="对照均值" width="110" align="right"><template #default="{ row }">{{ percent(row.controlMean) }}</template></el-table-column>
        <el-table-column label="实际分位" width="100" align="right"><template #default="{ row }">{{ percent(row.percentile) }}</template></el-table-column>
        <el-table-column prop="reps" label="重复次数" width="90" align="right" />
      </el-table>

      <h4>预注册标准逐项检查</h4>
      <ul class="sq-detail__checks">
        <li v-for="(passed, name) in cell.qualification.checks" :key="name">
          <span :class="passed ? 'sq-check-pass' : 'sq-check-fail'">{{ passed ? '✓' : '✗' }}</span>
          {{ checkLabels[name] || name }}
        </li>
      </ul>
    </div>
  </el-drawer>
</template>

<script setup>
import { computed } from "vue";
import ClxChart from "@/components/clx-backtest/ClxChart.vue";

const props = defineProps({
  cell: { type: Object, default: null },
  splitId: { type: String, default: "TRAIN" },
});
defineEmits(["close"]);

const checkLabels = {
  train_fdr: "TRAIN FDR q < 0.05",
  train_samples: "TRAIN 可执行样本 ≥ 500",
  validation_samples: "VALIDATION 可执行样本 ≥ 100",
  validation_sign: "VALIDATION 与 TRAIN 同号",
  net_positive: "扣费净均值 > 0",
  mean_excess_floor: "TRAIN 均值超额 ≥ +0.5%",
  worst_year: "最差年份均值 > -1.5%",
  year_stability: "≥60% 年份为正",
  beats_random_pool: "优于同池随机日期 95 分位",
  beats_date_shift: "优于日期平移对照 95 分位",
};

const title = computed(() => (props.cell ? `${props.cell.modelCode} · ${props.cell.trigger} · ${props.cell.direction === 1 ? "+1" : "-1"}` : ""));
const statusType = computed(() => (props.cell?.qualification.status === "CORE" ? "success" : props.cell?.qualification.status === "WATCH" ? "warning" : "info"));
const stats = computed(() => props.cell?.splits?.[props.splitId] ?? null);
const hasHoldout = computed(() => Boolean(props.cell?.splits?.HOLDOUT));

const splitRows = computed(() => ["TRAIN", "VALIDATION", "HOLDOUT"]
  .map((split) => {
    const item = props.cell?.splits?.[split];
    return item ? { split, ...item } : null;
  })
  .filter(Boolean));

const yearlyEntries = computed(() => Object.entries(stats.value?.yearlyMeanExcess ?? {}).sort((a, b) => a[0].localeCompare(b[0])));
const decayEntries = computed(() => Object.entries(stats.value?.horizonDecay ?? {})
  .filter(([, value]) => value !== null && value !== undefined)
  .sort((a, b) => Number(a[0]) - Number(b[0])));

const controlRows = computed(() => [
  stats.value?.randomPoolControl ? { name: "同池随机日期 bootstrap", ...stats.value.randomPoolControl } : null,
  stats.value?.dateShiftControl ? { name: "同股票日期平移（±20-60日）", ...stats.value.dateShiftControl } : null,
].filter(Boolean));

const percent = (value) => (value === null || value === undefined ? "-" : `${(Number(value) * 100).toFixed(2)}%`);
const fixed = (value, digits) => (value === null || value === undefined ? "-" : Number(value).toFixed(digits));

const axisStyle = { axisLabel: { color: "#a6adc8", fontSize: 10 }, axisLine: { lineStyle: { color: "#45475a" } } };

const yearlyOption = computed(() => ({
  animation: false,
  grid: { left: 56, right: 16, top: 18, bottom: 26 },
  tooltip: { trigger: "axis", valueFormatter: (value) => percent(value) },
  xAxis: { type: "category", data: yearlyEntries.value.map(([year]) => year), ...axisStyle },
  yAxis: { type: "value", axisLabel: { ...axisStyle.axisLabel, formatter: (value) => `${(value * 100).toFixed(1)}%` }, splitLine: { lineStyle: { color: "#313244" } } },
  series: [{
    type: "bar",
    data: yearlyEntries.value.map(([, value]) => ({ value, itemStyle: { color: value >= 0 ? "#f38ba8" : "#94e2d5" } })),
  }],
}));

const decayOption = computed(() => ({
  animation: false,
  grid: { left: 56, right: 16, top: 18, bottom: 26 },
  tooltip: { trigger: "axis", valueFormatter: (value) => percent(value) },
  xAxis: { type: "category", data: decayEntries.value.map(([horizon]) => `${horizon}日`), ...axisStyle },
  yAxis: { type: "value", axisLabel: { ...axisStyle.axisLabel, formatter: (value) => `${(value * 100).toFixed(1)}%` }, splitLine: { lineStyle: { color: "#313244" } } },
  series: [{ type: "line", symbol: "circle", symbolSize: 7, lineStyle: { color: "#89b4fa" }, itemStyle: { color: "#89b4fa" }, data: decayEntries.value.map(([, value]) => value) }],
}));
</script>

<style scoped>
.sq-detail { display: flex; flex-direction: column; gap: 10px; }
.sq-detail h4 { margin: 10px 0 4px; font-size: 13px; }
.sq-detail__badges { display: flex; gap: 8px; }
.sq-detail__warning { font-size: 12px; color: var(--fq-status-warning, #f9e2af); margin: 4px 0 0; }
.sq-detail__checks { list-style: none; margin: 0; padding: 0; font-size: 12px; display: grid; grid-template-columns: 1fr 1fr; gap: 4px 14px; }
.sq-check-pass { color: var(--fq-status-success, #a6e3a1); font-weight: 700; margin-right: 4px; }
.sq-check-fail { color: var(--fq-status-danger, #f38ba8); font-weight: 700; margin-right: 4px; }
</style>
