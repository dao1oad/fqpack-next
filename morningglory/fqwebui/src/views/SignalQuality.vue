<template>
  <WorkbenchPage class="signal-quality-page" data-testid="sq-workbench">
    <MyHeader />
    <div class="workbench-body workbench-body--scroll sq-body">
      <WorkbenchToolbar class="sq-toolbar">
        <div class="workbench-toolbar__header">
          <div class="sq-identity">
            <div class="sq-mark">SQ</div>
            <div class="workbench-title-group">
              <span class="sq-eyebrow">FRESHQUANT RESEARCH</span>
              <h1 class="workbench-page-title">CLX 信号质量基准</h1>
              <div class="workbench-page-meta">18 模型 × 触发语义 × 方向 · 5 日超额收益 · FDR / 随机对照 / 年度稳定性</div>
            </div>
          </div>
          <div class="workbench-toolbar__actions sq-status">
            <el-tag v-if="summary" size="small" type="info" effect="plain" round>{{ summary.cellCount }} cells · {{ generatedAtText }}</el-tag>
            <StatusChip variant="success">CORE {{ summary?.statusCounts?.CORE ?? 0 }}</StatusChip>
            <StatusChip variant="warning">WATCH {{ summary?.statusCounts?.WATCH ?? 0 }}</StatusChip>
          </div>
        </div>
        <div class="sq-filters" data-testid="sq-filters">
          <el-select v-model="splitId" size="small" style="width: 140px" aria-label="分割">
            <el-option label="TRAIN 2005-19" value="TRAIN" />
            <el-option label="VALIDATION 2020-23" value="VALIDATION" />
            <el-option label="HOLDOUT 2024-26" value="HOLDOUT" />
          </el-select>
          <el-select v-model="direction" size="small" style="width: 120px" aria-label="方向">
            <el-option label="全部方向" value="all" />
            <el-option label="买入 +1" value="1" />
            <el-option label="卖出 -1" value="-1" />
          </el-select>
          <el-select v-model="modelCode" size="small" style="width: 120px" clearable placeholder="全部模型" aria-label="模型">
            <el-option v-for="code in summary?.models ?? []" :key="code" :label="code" :value="code" />
          </el-select>
          <el-select v-model="trigger" size="small" style="width: 220px" clearable placeholder="全部触发语义" aria-label="触发语义">
            <el-option v-for="item in summary?.triggers ?? []" :key="item" :label="item" :value="item" />
          </el-select>
          <el-select v-model="status" size="small" style="width: 130px" clearable placeholder="全部判定" aria-label="判定">
            <el-option label="CORE" value="CORE" />
            <el-option label="WATCH" value="WATCH" />
            <el-option label="REJECTED" value="REJECTED" />
          </el-select>
          <el-input-number v-model="minExecutable" size="small" :min="0" :step="100" controls-position="right" style="width: 130px" aria-label="最小样本数" />
          <span class="sq-filter-hint">最小可执行样本（{{ splitId }}）</span>
        </div>
        <div v-if="splitId === 'HOLDOUT'" class="sq-holdout-warning" data-testid="sq-holdout-warning">
          ⚠️ HOLDOUT 仅作确认，不得用于选择；且该分割在历史 run 中已被揭示过一次，存在污染，数字应打折看待。
        </div>
      </WorkbenchToolbar>

      <main class="sq-content">
        <el-alert v-if="errorText" :title="errorText" type="error" show-icon :closable="false" data-testid="sq-error" />
        <template v-else>
          <SqHeatmap v-model:metric="heatmapMetric" :cells="filteredCells" :split-id="splitId" :loading="loading" />
          <SqRankingTable :cells="filteredCells" :split-id="splitId" @select="selectedCell = $event" />
          <section v-if="summary" class="sq-methodology" data-testid="sq-methodology">
            <h3>方法学快照</h3>
            <pre>{{ methodologyText }}</pre>
          </section>
        </template>
      </main>
    </div>
    <SqCellDetail :cell="selectedCell" :split-id="splitId" @close="selectedCell = null" />
  </WorkbenchPage>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { clxBacktestApi } from "@/api/clxBacktestApi";
import { signalQualityApi } from "@/api/signalQualityApi";
import MyHeader from "./MyHeader.vue";
import WorkbenchPage from "@/components/workbench/WorkbenchPage.vue";
import WorkbenchToolbar from "@/components/workbench/WorkbenchToolbar.vue";
import StatusChip from "@/components/workbench/StatusChip.vue";
import SqHeatmap from "@/components/signal-quality/SqHeatmap.vue";
import SqRankingTable from "@/components/signal-quality/SqRankingTable.vue";
import SqCellDetail from "@/components/signal-quality/SqCellDetail.vue";

const route = useRoute();
const runId = ref(String(route.query.run_id ?? ""));
const summary = ref(null);
const cells = ref([]);
const loading = ref(true);
const errorText = ref("");
const selectedCell = ref(null);

const splitId = ref("TRAIN");
const direction = ref("all");
const modelCode = ref("");
const trigger = ref("");
const status = ref("");
const minExecutable = ref(0);
const heatmapMetric = ref("meanExcess");

const generatedAtText = computed(() => (summary.value?.generatedAt ? summary.value.generatedAt.slice(0, 16).replace("T", " ") : ""));
const methodologyText = computed(() => JSON.stringify(summary.value?.methodology ?? {}, null, 2));

const filteredCells = computed(() => cells.value.filter((cell) => {
  if (direction.value !== "all" && cell.direction !== Number(direction.value)) return false;
  if (modelCode.value && cell.modelCode !== modelCode.value) return false;
  if (trigger.value && cell.trigger !== trigger.value) return false;
  if (status.value && cell.qualification.status !== status.value) return false;
  const stats = cell.splits?.[splitId.value];
  if (!stats) return false;
  if ((minExecutable.value ?? 0) > 0 && stats.nExecutable < minExecutable.value) return false;
  return true;
}));

async function resolveRunId() {
  if (runId.value) return runId.value;
  const page = await clxBacktestApi.listRuns({ status: "COMPLETE", pageSize: 1 });
  runId.value = page.items[0]?.runId ?? page.items[0]?.id ?? "";
  return runId.value;
}

async function load() {
  loading.value = true;
  errorText.value = "";
  try {
    const id = await resolveRunId();
    if (!id) throw new Error("未找到已完成的回测 run");
    const [summaryResult, cellResult] = await Promise.all([
      signalQualityApi.summary(id),
      signalQualityApi.cells(id),
    ]);
    summary.value = summaryResult;
    cells.value = cellResult.items;
  } catch (error) {
    errorText.value = error?.response?.data?.error?.message ?? error?.message ?? "加载信号质量基准失败";
  } finally {
    loading.value = false;
  }
}

watch(splitId, () => { selectedCell.value = null; });
onMounted(load);
</script>

<style scoped>
.sq-identity { display: flex; align-items: center; gap: 13px; min-width: 0; }
.sq-mark { width: 46px; height: 46px; display: grid; place-items: center; border: 1px solid color-mix(in srgb, var(--fq-status-primary) 48%, transparent); border-radius: 11px; background: linear-gradient(145deg, color-mix(in srgb, var(--fq-status-primary) 16%, var(--fq-panel-bg)), var(--fq-panel-bg)); color: var(--fq-status-primary); font: 700 13px ui-monospace, monospace; flex: 0 0 auto; }
.sq-eyebrow { color: var(--fq-status-primary); font-size: 9px; letter-spacing: .16em; }
.sq-status { display: flex; align-items: center; justify-content: flex-end; gap: 6px; flex-wrap: wrap; }
.sq-filters { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 8px 2px 2px; }
.sq-filter-hint { color: var(--fq-text-muted); font-size: 11px; }
.sq-holdout-warning { margin-top: 8px; padding: 8px 12px; border: 1px solid color-mix(in srgb, var(--fq-status-warning, #f9e2af) 50%, transparent); border-radius: 8px; color: var(--fq-status-warning, #f9e2af); font-size: 12px; background: color-mix(in srgb, var(--fq-status-warning, #f9e2af) 8%, transparent); }
.sq-content { min-width: 0; padding-bottom: 20px; display: flex; flex-direction: column; gap: 14px; }
.sq-methodology { background: var(--fq-panel-bg); border: 1px solid var(--fq-border-soft); border-radius: 10px; padding: 16px; }
.sq-methodology h3 { margin: 0 0 8px; font-size: 14px; }
.sq-methodology pre { margin: 0; font-size: 11px; color: var(--fq-text-muted); white-space: pre-wrap; word-break: break-all; max-height: 320px; overflow: auto; }
@media (max-width: 760px) { .sq-status { justify-content: flex-start; } }
</style>
