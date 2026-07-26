<template>
  <section class="sq-card" data-testid="sq-ranking-table">
    <div class="sq-card__header">
      <div><span class="sq-card__kicker">信号质量基准</span><h3>信号 Cell 排名表（{{ splitId }}）</h3></div>
      <span class="sq-card__count">{{ rows.length }} 个 cell</span>
    </div>
    <el-table
      :data="rows"
      size="small"
      height="560"
      :default-sort="{ prop: 'informationRatio', order: 'descending' }"
      @row-click="(row) => $emit('select', row.cell)"
    >
      <el-table-column label="判定" width="86" sortable :sort-by="(row) => row.statusRank">
        <template #default="{ row }">
          <el-tag :type="row.status === 'CORE' ? 'success' : row.status === 'WATCH' ? 'warning' : 'info'" size="small" effect="plain">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="modelCode" label="模型" width="82" sortable />
      <el-table-column prop="trigger" label="触发语义" min-width="170" sortable show-overflow-tooltip />
      <el-table-column label="方向" width="70" sortable :sort-by="(row) => row.direction">
        <template #default="{ row }"><span :class="row.direction === 1 ? 'sq-pos' : 'sq-neg'">{{ row.direction === 1 ? '买入' : '卖出' }}</span></template>
      </el-table-column>
      <el-table-column prop="nExecutable" label="样本" width="92" sortable align="right">
        <template #default="{ row }">{{ row.nExecutable.toLocaleString('zh-CN') }}</template>
      </el-table-column>
      <el-table-column prop="meanExcess" label="均值超额" width="104" sortable align="right">
        <template #default="{ row }"><span :class="colorClass(row.meanExcess)">{{ percent(row.meanExcess) }}</span></template>
      </el-table-column>
      <el-table-column prop="netMeanExcess" label="扣费净超额" width="112" sortable align="right">
        <template #default="{ row }"><span :class="colorClass(row.netMeanExcess)">{{ percent(row.netMeanExcess) }}</span></template>
      </el-table-column>
      <el-table-column prop="winRate" label="胜率" width="86" sortable align="right">
        <template #default="{ row }">{{ percent(row.winRate) }}</template>
      </el-table-column>
      <el-table-column prop="informationRatio" label="信息比率" width="100" sortable align="right">
        <template #default="{ row }">{{ fixed(row.informationRatio, 4) }}</template>
      </el-table-column>
      <el-table-column prop="tStat" label="t 值" width="86" sortable align="right">
        <template #default="{ row }">{{ fixed(row.tStat, 2) }}</template>
      </el-table-column>
      <el-table-column prop="fdrQValue" label="FDR q" width="96" sortable align="right">
        <template #default="{ row }"><span :class="{ 'sq-sig': row.fdrQValue !== null && row.fdrQValue < 0.05 }">{{ fixed(row.fdrQValue, 4) }}</span></template>
      </el-table-column>
      <el-table-column prop="worstYearMean" label="最差年份" width="100" sortable align="right">
        <template #default="{ row }"><span :class="colorClass(row.worstYearMean)">{{ percent(row.worstYearMean) }}</span></template>
      </el-table-column>
      <el-table-column prop="positiveYearRatio" label="为正年份" width="96" sortable align="right">
        <template #default="{ row }">{{ percent(row.positiveYearRatio) }}</template>
      </el-table-column>
      <el-table-column prop="randomPoolPct" label="随机池分位" width="104" sortable align="right">
        <template #default="{ row }">{{ percent(row.randomPoolPct) }}</template>
      </el-table-column>
      <el-table-column prop="dateShiftPct" label="平移分位" width="96" sortable align="right">
        <template #default="{ row }">{{ percent(row.dateShiftPct) }}</template>
      </el-table-column>
    </el-table>
    <div class="sq-card__footnote">点击行查看年度稳定性、衰减曲线与随机对照明细。q&lt;0.05 以高亮标记；判定为预注册标准（见方法学）。</div>
  </section>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  cells: { type: Array, required: true },
  splitId: { type: String, default: "TRAIN" },
});
defineEmits(["select"]);

const statusRank = { CORE: 0, WATCH: 1, REJECTED: 2 };

const rows = computed(() => props.cells
  .map((cell) => {
    const stats = cell.splits?.[props.splitId];
    if (!stats) return null;
    return {
      cell,
      cellId: cell.cellId,
      status: cell.qualification?.status ?? "REJECTED",
      statusRank: statusRank[cell.qualification?.status] ?? 3,
      modelCode: cell.modelCode,
      trigger: cell.trigger,
      direction: cell.direction,
      nExecutable: stats.nExecutable ?? 0,
      meanExcess: stats.meanExcess,
      netMeanExcess: stats.netMeanExcess,
      winRate: stats.winRate,
      informationRatio: stats.informationRatio,
      tStat: stats.tStat,
      fdrQValue: stats.fdrQValue,
      worstYearMean: stats.worstYearMean,
      positiveYearRatio: stats.positiveYearRatio,
      randomPoolPct: stats.randomPoolControl?.percentile ?? null,
      dateShiftPct: stats.dateShiftControl?.percentile ?? null,
    };
  })
  .filter(Boolean));

const percent = (value) => (value === null || value === undefined ? "-" : `${(Number(value) * 100).toFixed(2)}%`);
const fixed = (value, digits) => (value === null || value === undefined ? "-" : Number(value).toFixed(digits));
const colorClass = (value) => (value === null || value === undefined ? "" : Number(value) > 0 ? "sq-pos" : Number(value) < 0 ? "sq-neg" : "");
</script>

<style scoped>
.sq-card { background: var(--fq-panel-bg); border: 1px solid var(--fq-border-soft); border-radius: 10px; padding: 16px; min-width: 0; }
.sq-card__header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.sq-card__header h3 { margin: 3px 0 0; font-size: 14px; }
.sq-card__kicker { color: var(--fq-text-muted); font-size: 10px; letter-spacing: .08em; text-transform: uppercase; }
.sq-card__count { color: var(--fq-text-muted); font-size: 11px; }
.sq-card__footnote { font-size: 11px; color: var(--fq-text-muted); border-top: 1px solid var(--fq-border-soft); padding-top: 9px; margin-top: 8px; }
.sq-pos { color: var(--fq-status-danger, #f38ba8); }
.sq-neg { color: var(--fq-status-success, #94e2d5); }
.sq-sig { color: var(--fq-status-primary, #89b4fa); font-weight: 600; }
:deep(.el-table__row) { cursor: pointer; }
</style>
