<template>
  <div class="clx-results" data-testid="clx-results-panel">
    <section class="clx-toolbar workbench-toolbar">
      <div class="clx-toolbar__run">
        <label>已完成实验</label>
        <el-select
          v-model="selectedRunId"
          :loading="runsLoading"
          filterable
          placeholder="选择一个已完成实验"
          style="min-width: 260px"
          data-testid="results-run-select"
        >
          <el-option v-for="option in runOptions" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
      </div>
      <div v-if="selectedRun" class="clx-toolbar__meta">
        <RunStatusTag :status="selectedRun.status" />
        <el-tag size="small" effect="plain">配置 {{ hashShort(selectedRun.configSha256) }}</el-tag>
        <el-tag v-if="selectedRun.frozen" size="small" type="success" effect="plain">规则已冻结</el-tag>
      </div>
    </section>

    <el-alert v-if="error" type="error" :closable="true" class="clx-alert" @close="error = ''">
      <template #title>{{ error }}</template>
      <el-button size="small" link @click="reload">重试</el-button>
    </el-alert>

    <el-empty v-if="!runsLoading && !runs.length" description="暂无已完成实验；请先在“实验运行”创建并完成一个回测。" class="clx-page-empty" />

    <template v-else-if="selectedRunId">
      <section class="clx-card workbench-panel clx-ranking-card">
        <div class="clx-card__header">
          <div>
            <span class="clx-card__kicker">VALIDATION-FIRST RANKING</span>
            <h3>组合表现排行</h3>
          </div>
          <div class="clx-ranking-card__hint">HOLDOUT 仅附加展示，排行始终沿用 VALIDATION 冻结顺序</div>
        </div>

        <div class="clx-filters" data-testid="ranking-filters">
          <el-select v-model="filters.splitId" size="small" style="width: 150px" aria-label="样本段">
            <el-option v-for="option in splitOptions" :key="option.value" :label="option.label" :value="option.value" :disabled="option.disabled" />
          </el-select>
          <el-select v-model="filters.modelId" size="small" clearable filterable placeholder="全部模型" style="width: 126px" aria-label="模型">
            <el-option v-for="option in modelOptions" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
          <el-select v-model="filters.direction" size="small" clearable placeholder="全部方向" style="width: 125px" aria-label="方向">
            <el-option v-for="option in directionOptions" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
          <el-input v-model="filters.primaryTrigger" size="small" clearable placeholder="主触发类型" style="width: 142px" aria-label="主触发类型" />
          <el-input-number v-model="filters.occurrence" size="small" :min="1" placeholder="次数" style="width: 92px" aria-label="触发次数" />
          <el-input-number v-model="filters.horizon" size="small" :min="1" placeholder="周期" style="width: 92px" aria-label="周期" />
          <el-input-number v-model="filters.minScore" size="small" :disabled="filters.splitId === 'HOLDOUT'" placeholder="最低分" style="width: 106px" aria-label="最低得分" />
          <el-input v-model="filters.keyword" size="small" clearable placeholder="当前页组合 / DSL" style="min-width: 140px; flex: 1" aria-label="当前页关键词" @keyup.enter="applyFilters" />
          <el-button size="small" type="primary" :loading="rankingsLoading" @click="applyFilters">筛选</el-button>
          <el-button size="small" @click="resetFilters">重置</el-button>
        </div>

        <el-table
          v-loading="rankingsLoading"
          :data="displayRankings"
          :row-key="row => row.comboId"
          :row-class-name="rankingRowClassName"
          stripe
          height="430"
          size="small"
          data-testid="ranking-table"
          @row-click="selectRanking"
        >
          <el-table-column prop="rank" label="#" width="54" fixed="left"><template #default="{ row }"><b class="clx-rank">{{ row.rank }}</b></template></el-table-column>
          <el-table-column label="组合" width="270" fixed="left">
            <template #default="{ row }"><div class="clx-table-primary"><strong>{{ row.name }}</strong><small>{{ row.modelIds.join(' + ') || '组合规则' }} · {{ row.primaryTriggers?.join(' / ') || '多触发' }}</small></div></template>
          </el-table-column>
          <el-table-column label="得分" width="88" :sortable="filters.splitId !== 'HOLDOUT'"><template #default="{ row }">{{ formatNumber(row.score, 3) }}</template></el-table-column>
          <el-table-column label="事件均值" width="94"><template #default="{ row }"><span :class="Number(row.metrics.meanReturn) >= 0 ? 'clx-positive' : 'clx-negative'">{{ formatPercent(row.metrics.meanReturn) }}</span></template></el-table-column>
          <el-table-column label="胜率" width="84"><template #default="{ row }">{{ formatPercent(row.metrics.winRate) }}</template></el-table-column>
          <el-table-column label="95% CI" width="150"><template #default="{ row }">{{ formatPercent(row.metrics.confidenceLow) }} ～ {{ formatPercent(row.metrics.confidenceHigh) }}</template></el-table-column>
          <el-table-column label="信号数" width="86"><template #default="{ row }">{{ formatInteger(row.metrics.sampleCount ?? row.metrics.signalCount) }}</template></el-table-column>
          <el-table-column label="FDR q" width="82"><template #default="{ row }">{{ formatPercent(row.metrics.fdrQValue) }}</template></el-table-column>
          <el-table-column label="周期" width="72"><template #default="{ row }">{{ row.horizon ? `${row.horizon}日` : '--' }}</template></el-table-column>
          <el-table-column label="研究状态" width="132">
            <template #default="{ row }"><el-tag size="small" :type="row.holdoutRevealed ? 'warning' : row.frozen ? 'success' : 'info'" effect="plain">{{ row.holdoutRevealed ? 'HOLDOUT 已揭示' : row.frozen ? '规则已冻结' : '验证中' }}</el-tag></template>
          </el-table-column>
          <el-table-column label="" width="78" fixed="right"><template #default="{ row }"><el-button size="small" link :type="selectedRanking?.comboId === row.comboId ? 'primary' : 'info'" @click.stop="selectRanking(row)">下钻</el-button></template></el-table-column>
        </el-table>
        <div class="clx-cursor-pagination">
          <span>第 {{ rankingPage + 1 }} 页 · {{ displayRankings.length }} 条</span>
          <div>
            <el-button size="small" :disabled="rankingPage === 0 || rankingsLoading" @click="previousRankingPage">上一页</el-button>
            <el-button size="small" :disabled="!rankingNextCursor || rankingsLoading" @click="nextRankingPage">下一页</el-button>
          </div>
        </div>
      </section>

      <div v-loading="detailLoading" class="clx-detail-loading">
        <template v-if="selectedRanking">
          <div class="clx-selection-title">
            <div><span>当前下钻组合</span><h2>{{ selectedRanking.name }}</h2></div>
            <div class="clx-selection-title__tags">
              <el-tag v-for="model in selectedRanking.modelIds" :key="model" size="small" effect="plain">{{ model }}</el-tag>
              <el-tag size="small" type="info" effect="plain">{{ selectedRanking.splitId }}</el-tag>
            </div>
          </div>

          <div class="clx-metrics" data-testid="metric-cards">
            <div v-for="metric in metricCards" :key="metric.label" class="clx-metric" :class="metric.tone">
              <span>{{ metric.label }}</span><strong>{{ metric.value }}</strong><small>{{ metric.note }}</small>
            </div>
          </div>

          <div class="clx-analysis-grid">
            <ModelTriggerHeatmap v-model:metric="heatmapMetric" :cells="heatmapCells" :loading="heatmapLoading" @update:metric="loadHeatmap" />
            <section class="clx-card workbench-panel clx-definition" data-testid="combo-detail">
              <div class="clx-card__header">
                <div><span class="clx-card__kicker">COMBINATION CONTRACT</span><h3>组合定义</h3></div>
                <el-tag v-if="comboDetail?.frozen" type="success" size="small" effect="plain">冻结版本</el-tag>
              </div>
              <el-empty v-if="!comboDetail" :image-size="54" description="暂无组合定义" />
              <template v-else>
                <div class="clx-definition__dsl">{{ comboDsl }}</div>
                <div class="clx-definition__facts">
                  <div><span>组合 ID</span><b>{{ comboDetail.comboId }}</b></div>
                  <div><span>逻辑</span><b>{{ comboDetail.definition?.operator ?? '由 DSL 定义' }}</b></div>
                  <div><span>持有期</span><b>{{ comboDetail.definition?.holdingPeriod ?? selectedRanking.horizon ?? '--' }} 日</b></div>
                  <div><span>模型家族去重</span><b>{{ comboDetail.definition?.familyDeduplication === false ? '否' : '是' }}</b></div>
                  <div><span>信号集</span><b>{{ hashShort(comboDetail.signalSetId) }}</b></div>
                  <div><span>配置哈希</span><b>{{ hashShort(comboDetail.configSha256 || selectedRun?.configSha256) }}</b></div>
                </div>
                <div v-if="comboDetail.definition?.rules?.length" class="clx-definition__rules">
                  <div v-for="(rule, index) in comboDetail.definition.rules" :key="index" class="clx-rule">
                    <span class="clx-rule__index">{{ index + 1 }}</span><b>{{ rule.role ?? 'RULE' }}</b><span>{{ rule.modelId ?? rule.model_id ?? '--' }}</span><span>{{ rule.direction ?? '--' }}</span><span>{{ rule.primaryTrigger ?? rule.primary_trigger ?? '--' }}</span>
                  </div>
                </div>
              </template>
            </section>
          </div>

          <PerformanceCharts :points="equity" :loading="detailLoading" :split-id="String(filters.splitId)" :series-name="selectedRanking.name" />

          <section class="clx-card workbench-panel clx-facts" data-testid="facts-detail">
            <el-tabs v-model="factTab">
              <el-tab-pane :label="`成交明细 (${trades.items.length})`" name="trades">
                <el-table :data="trades.items" :row-key="row => row.tradeId" height="420" size="small">
                  <el-table-column prop="tradeDate" label="成交日" width="108" fixed="left" />
                  <el-table-column prop="code" label="代码" width="90" fixed="left" />
                  <el-table-column label="方向" width="82"><template #default="{ row }"><el-tag size="small" :type="String(row.side).toUpperCase().includes('BUY') ? 'danger' : 'success'" effect="plain">{{ row.side }}</el-tag></template></el-table-column>
                  <el-table-column label="价格" width="90"><template #default="{ row }">{{ formatNumber(row.price, 3) }}</template></el-table-column>
                  <el-table-column label="数量" width="90"><template #default="{ row }">{{ formatInteger(row.quantity) }}</template></el-table-column>
                  <el-table-column label="费用" width="90"><template #default="{ row }">{{ formatMoney(row.fees) }}</template></el-table-column>
                  <el-table-column label="盈亏" width="100"><template #default="{ row }">{{ formatMoney(row.pnl) }}</template></el-table-column>
                  <el-table-column label="收益率" width="90"><template #default="{ row }">{{ formatPercent(row.returnRate) }}</template></el-table-column>
                  <el-table-column label="退出 / 受阻原因" min-width="220"><template #default="{ row }">{{ row.exitReason ?? row.blockedReason ?? '--' }}</template></el-table-column>
                </el-table>
                <div class="clx-cursor-pagination"><span>逐笔撮合事实</span><el-button size="small" :disabled="!trades.nextCursor" @click="loadMoreTrades">加载下一页</el-button></div>
              </el-tab-pane>
              <el-tab-pane :label="`信号明细 (${signals.items.length})`" name="signals">
                <el-table :data="signals.items" :row-key="row => row.signalId" height="420" size="small" data-testid="signal-table" @row-click="openSignal">
                  <el-table-column prop="signalDate" label="信号日" width="108" fixed="left" />
                  <el-table-column prop="revealDate" label="可见日" width="108" />
                  <el-table-column prop="code" label="代码" width="86" fixed="left" />
                  <el-table-column prop="modelId" label="模型" width="82"><template #default="{ row }"><code>{{ row.modelId }}</code></template></el-table-column>
                  <el-table-column prop="direction" label="方向" width="80" />
                  <el-table-column prop="occurrence" label="次数" width="64" />
                  <el-table-column prop="primaryTrigger" label="主触发" width="156" />
                  <el-table-column label="同K线并发触发" min-width="280" show-overflow-tooltip><template #default="{ row }">{{ row.concurrentTriggers.join(' · ') || '--' }}</template></el-table-column>
                  <el-table-column prop="rawSignal" label="原始值" width="90" />
                  <el-table-column label="" width="80" fixed="right"><template #default="{ row }"><el-button size="small" link type="primary" @click.stop="openSignal(row)">看K线</el-button></template></el-table-column>
                </el-table>
                <div class="clx-cursor-pagination"><span>点击任一信号打开 K 线下钻</span><el-button size="small" :disabled="!signals.nextCursor" @click="loadMoreSignals">加载下一页</el-button></div>
              </el-tab-pane>
            </el-tabs>
          </section>
        </template>
        <el-empty v-else-if="!rankingsLoading" description="当前筛选下暂无组合，请调整模型、触发或样本段。" class="clx-page-empty" />
      </div>
    </template>

    <SignalKlineDrawer v-model:show="klineVisible" :signal="selectedSignal" />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { clxBacktestApi, describeApiError } from "@/api/clxBacktestApi";
import { formatInteger, formatMoney, formatNumber, formatPercent, hashShort } from "@/utils/clxFormat";
import RunStatusTag from "./RunStatusTag.vue";
import ModelTriggerHeatmap from "./ModelTriggerHeatmap.vue";
import PerformanceCharts from "./PerformanceCharts.vue";
import SignalKlineDrawer from "./SignalKlineDrawer.vue";
const props = defineProps({ initialRunId: { type: String, default: "" } });
const message = ElMessage;
const runs = ref([]);
const runsLoading = ref(false);
const selectedRunId = ref(null);
const rankings = ref([]);
const rankingsLoading = ref(false);
const rankingNextCursor = ref(null);
const rankingCursors = ref([void 0]);
const rankingPage = ref(0);
const selectedRanking = ref(null);
const comboDetail = ref(null);
const equity = ref([]);
const trades = ref({ items: [], nextCursor: null });
const signals = ref({ items: [], nextCursor: null });
const heatmapCells = ref([]);
const heatmapMetric = ref("mean_return");
const heatmapLoading = ref(false);
const detailLoading = ref(false);
const factTab = ref("trades");
const selectedSignal = ref(null);
const klineVisible = ref(false);
const error = ref("");
const filters = reactive({
  splitId: "VALIDATION",
  modelId: null,
  direction: null,
  primaryTrigger: "",
  occurrence: null,
  horizon: null,
  minScore: null,
  keyword: ""
});
const splitOptions = computed(() => [
  { label: "\u7814\u7A76\u96C6 TRAIN", value: "TRAIN" },
  { label: "\u9A8C\u8BC1\u96C6 VALIDATION", value: "VALIDATION" },
  { label: "\u9501\u5B9A\u6D4B\u8BD5 HOLDOUT", value: "HOLDOUT", disabled: !selectedRun.value?.holdoutRevealed }
]);
const modelOptions = Array.from({ length: 18 }, (_, index) => {
  const value = `S${String(index).padStart(4, "0")}`;
  return { label: value, value };
});
const directionOptions = [
  { label: "\u6B63\u5411 / \u4E70\u5165", value: "POSITIVE" },
  { label: "\u8D1F\u5411 / \u9000\u51FA", value: "NEGATIVE" }
];
const runOptions = computed(() => runs.value.map((run) => ({ label: `${run.name} \xB7 ${run.runId}`, value: run.runId })));
const selectedRun = computed(() => runs.value.find((run) => run.runId === selectedRunId.value) ?? null);
const displayRankings = computed(() => rankings.value.filter((row) => {
  const keyword = filters.keyword.trim().toLowerCase();
  return !keyword || `${row.name} ${row.comboId}`.toLowerCase().includes(keyword);
}));
const comboDsl = computed(() => String(comboDetail.value?.definition?.dsl ?? comboDetail.value?.definition?.canonical_dsl ?? selectedRanking.value?.name ?? "--"));
const metricCards = computed(() => {
  const eventMetrics = selectedRanking.value?.metrics ?? {};
  const portfolioMetrics = comboDetail.value?.metrics ?? {};
  const eventNotes = [
    confidenceLabel(eventMetrics.confidenceLow, eventMetrics.confidenceHigh),
    `FDR q ${formatPercent(eventMetrics.fdrQValue)}`,
    `n ${formatInteger(eventMetrics.sampleCount ?? eventMetrics.signalCount)}`
  ].join(" \xB7 ");
  return [
    { label: "\u7EFC\u5408\u5F97\u5206", value: formatNumber(selectedRanking.value?.score, 3), note: "\u9A8C\u8BC1\u96C6\u51BB\u7ED3\u53E3\u5F84", tone: "accent" },
    { label: "\u4E8B\u4EF6\u5E73\u5747\u6536\u76CA", value: formatPercent(eventMetrics.meanReturn), note: eventNotes, tone: Number(eventMetrics.meanReturn) >= 0 ? "up" : "down" },
    { label: "\u7EC4\u5408\u603B\u6536\u76CA", value: formatPercent(portfolioMetrics.totalReturn), note: "\u53EF\u4EA4\u6613\u8D44\u91D1\u66F2\u7EBF", tone: Number(portfolioMetrics.totalReturn) >= 0 ? "up" : "down" },
    { label: "\u7EC4\u5408 CAGR", value: formatPercent(portfolioMetrics.annualizedReturn), note: "252 \u4EA4\u6613\u65E5\u5E74\u5316", tone: Number(portfolioMetrics.annualizedReturn) >= 0 ? "up" : "down" },
    { label: "\u7EC4\u5408 Sharpe", value: formatNumber(portfolioMetrics.sharpe, 3), note: `\u5DF2\u5E73\u4ED3 ${formatInteger(portfolioMetrics.tradeCount)}`, tone: "neutral" },
    { label: "\u7EC4\u5408\u6700\u5927\u56DE\u64A4", value: formatPercent(portfolioMetrics.maxDrawdown), note: "\u8D8A\u63A5\u8FD1 0 \u8D8A\u7A33\u5065", tone: "warning" }
  ];
});
function confidenceLabel(low, high) {
  return low === null || low === void 0 || high === null || high === void 0 ? "\u7F6E\u4FE1\u533A\u95F4\u5F85\u7EDF\u8BA1" : `95% CI ${formatPercent(low)}\uFF5E${formatPercent(high)}`;
}
function rankingRowClassName({ row }) {
  return selectedRanking.value?.comboId === row.comboId ? "clx-row--selected" : "";
}
function openSignal(row) {
  selectedSignal.value = row;
  klineVisible.value = true;
}
async function loadRuns() {
  runsLoading.value = true;
  error.value = "";
  try {
    let page = await clxBacktestApi.listRuns({ status: "COMPLETE", pageSize: 100 });
    if (!page.items.length) page = await clxBacktestApi.listRuns({ pageSize: 100 });
    runs.value = page.items.filter((run) => run.status === "COMPLETE" || page.items.every((item) => item.status !== "COMPLETE"));
    if (props.initialRunId && runs.value.some((run) => run.runId === props.initialRunId)) selectedRunId.value = props.initialRunId;
    else if (!selectedRunId.value && runs.value.length) selectedRunId.value = runs.value[0].runId;
  } catch (reason) {
    error.value = describeApiError(reason);
  } finally {
    runsLoading.value = false;
  }
}
async function loadRankings(cursor) {
  if (!selectedRunId.value) return;
  rankingsLoading.value = true;
  error.value = "";
  try {
    const page = await clxBacktestApi.listRankings(selectedRunId.value, {
      splitId: filters.splitId,
      modelId: filters.modelId || void 0,
      direction: filters.direction || void 0,
      occurrence: filters.occurrence || void 0,
      horizon: filters.horizon || void 0,
      primaryTrigger: filters.primaryTrigger || void 0,
      minScore: filters.splitId === "HOLDOUT" ? void 0 : filters.minScore ?? void 0,
      pageSize: 25,
      cursor
    });
    rankings.value = page.items;
    rankingNextCursor.value = page.nextCursor;
    if (!page.items.some((row) => row.comboId === selectedRanking.value?.comboId)) {
      selectedRanking.value = page.items[0] ?? null;
    } else if (selectedRanking.value) {
      selectedRanking.value = page.items.find((row) => row.comboId === selectedRanking.value?.comboId) ?? null;
    }
  } catch (reason) {
    error.value = describeApiError(reason);
    rankings.value = [];
  } finally {
    rankingsLoading.value = false;
  }
}
async function loadHeatmap() {
  if (!selectedRunId.value) return;
  heatmapLoading.value = true;
  try {
    const page = await clxBacktestApi.getModelHeatmap(selectedRunId.value, { splitId: filters.splitId, metric: heatmapMetric.value });
    heatmapCells.value = page.items;
  } catch (reason) {
    error.value = describeApiError(reason);
    heatmapCells.value = [];
  } finally {
    heatmapLoading.value = false;
  }
}
async function loadDetail() {
  const runId = selectedRunId.value;
  const row = selectedRanking.value;
  if (!runId || !row) {
    comboDetail.value = null;
    equity.value = [];
    trades.value = { items: [], nextCursor: null };
    signals.value = { items: [], nextCursor: null };
    return;
  }
  detailLoading.value = true;
  const requests = await Promise.allSettled([
    clxBacktestApi.getCombo(runId, row.comboId, { splitId: filters.splitId }),
    clxBacktestApi.getEquity(runId, row.comboId, { splitId: filters.splitId, horizon: row.horizon ?? void 0 }),
    clxBacktestApi.listTrades(runId, row.comboId, { splitId: filters.splitId, horizon: row.horizon ?? void 0, pageSize: 50 }),
    clxBacktestApi.listSignals(runId, row.comboId, { splitId: filters.splitId, horizon: row.horizon ?? void 0, pageSize: 50 })
  ]);
  comboDetail.value = requests[0].status === "fulfilled" ? requests[0].value : null;
  equity.value = requests[1].status === "fulfilled" ? requests[1].value.items : [];
  trades.value = requests[2].status === "fulfilled" ? requests[2].value : { items: [], nextCursor: null };
  signals.value = requests[3].status === "fulfilled" ? requests[3].value : { items: [], nextCursor: null };
  const rejected = requests.find((result) => result.status === "rejected");
  if (rejected) error.value = `\u90E8\u5206\u4E0B\u94BB\u6570\u636E\u52A0\u8F7D\u5931\u8D25\uFF1A${describeApiError(rejected.reason)}`;
  detailLoading.value = false;
}
function selectRanking(row) {
  selectedRanking.value = row;
}
function applyFilters() {
  rankingPage.value = 0;
  rankingCursors.value = [void 0];
  loadRankings();
  loadHeatmap();
}
function resetFilters() {
  Object.assign(filters, { splitId: "VALIDATION", modelId: null, direction: null, primaryTrigger: "", occurrence: null, horizon: null, minScore: null, keyword: "" });
  applyFilters();
}
async function nextRankingPage() {
  if (!rankingNextCursor.value) return;
  rankingCursors.value = rankingCursors.value.slice(0, rankingPage.value + 1);
  rankingCursors.value.push(rankingNextCursor.value);
  rankingPage.value += 1;
  await loadRankings(rankingCursors.value[rankingPage.value]);
}
async function previousRankingPage() {
  if (rankingPage.value > 0) {
    rankingPage.value -= 1;
    await loadRankings(rankingCursors.value[rankingPage.value]);
  }
}
async function loadMoreTrades() {
  if (!selectedRunId.value || !selectedRanking.value || !trades.value.nextCursor) return;
  const page = await clxBacktestApi.listTrades(selectedRunId.value, selectedRanking.value.comboId, {
    splitId: filters.splitId,
    horizon: selectedRanking.value.horizon ?? void 0,
    cursor: trades.value.nextCursor,
    pageSize: 50
  });
  trades.value = { items: [...trades.value.items, ...page.items], nextCursor: page.nextCursor };
}
async function loadMoreSignals() {
  if (!selectedRunId.value || !selectedRanking.value || !signals.value.nextCursor) return;
  const page = await clxBacktestApi.listSignals(selectedRunId.value, selectedRanking.value.comboId, {
    splitId: filters.splitId,
    horizon: selectedRanking.value.horizon ?? void 0,
    cursor: signals.value.nextCursor,
    pageSize: 50
  });
  signals.value = { items: [...signals.value.items, ...page.items], nextCursor: page.nextCursor };
}
async function reload() {
  await loadRuns();
  if (selectedRunId.value) {
    await Promise.all([loadRankings(), loadHeatmap()]);
  }
}
watch(() => props.initialRunId, (value) => {
  if (value && runs.value.some((run) => run.runId === value)) selectedRunId.value = value;
});
watch(selectedRunId, async (value, oldValue) => {
  if (!value || value === oldValue) return;
  if (filters.splitId === "HOLDOUT" && !selectedRun.value?.holdoutRevealed) filters.splitId = "VALIDATION";
  rankingPage.value = 0;
  rankingCursors.value = [void 0];
  await Promise.all([loadRankings(), loadHeatmap()]);
});
watch(
  [() => selectedRanking.value?.comboId, () => selectedRanking.value?.horizon, () => filters.splitId],
  loadDetail
);
onMounted(loadRuns);
</script>

<style scoped>
.clx-results { display: flex; flex-direction: column; gap: 14px; }
.clx-toolbar, .clx-toolbar__run, .clx-toolbar__meta, .clx-selection-title, .clx-selection-title__tags { display: flex; align-items: center; gap: 10px; }
.clx-toolbar { justify-content: space-between; padding: 12px 14px; border: 1px solid var(--fq-border-soft); border-radius: 10px; background: var(--fq-panel-bg); }
.clx-toolbar__run label { color: var(--fq-text-muted); font-size: 12px; white-space: nowrap; }
.clx-toolbar__meta { justify-content: flex-end; flex-wrap: wrap; }
.clx-alert { margin: 0; }
.clx-page-empty { padding: 60px 0; border: 1px dashed var(--fq-border-soft); border-radius: 10px; }
.clx-card { background: var(--fq-panel-bg); border: 1px solid var(--fq-border-soft); border-radius: 10px; padding: 16px; min-width: 0; }
.clx-card__header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.clx-card__header h3 { margin: 3px 0 0; font-size: 14px; }
.clx-card__kicker { color: var(--fq-text-muted); font-size: 10px; letter-spacing: .08em; }
.clx-ranking-card__hint { color: var(--fq-status-warning); font-size: 11px; }
.clx-filters { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; padding: 10px; border-radius: 8px; background: var(--fq-panel-bg-muted); }
.clx-cursor-pagination { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--fq-text-muted); font-size: 11px; padding-top: 10px; }
.clx-cursor-pagination > div { display: flex; gap: 6px; }
.clx-selection-title { justify-content: space-between; padding: 5px 2px; }
.clx-selection-title span { color: var(--fq-text-muted); font-size: 11px; }
.clx-selection-title h2 { font-size: 17px; margin: 3px 0 0; }
.clx-selection-title__tags { flex-wrap: wrap; justify-content: flex-end; }
.clx-metrics { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }
.clx-metric { position: relative; overflow: hidden; display: flex; flex-direction: column; gap: 5px; padding: 13px 14px; border: 1px solid var(--fq-border-soft); border-radius: 9px; background: var(--fq-panel-bg); }
.clx-metric::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 2px; background: var(--fq-text-muted); }
.clx-metric.accent::before { background: var(--fq-status-primary); } .clx-metric.up::before { background: var(--fq-status-danger); } .clx-metric.down::before { background: var(--fq-status-success); } .clx-metric.warning::before { background: var(--fq-status-warning); } .clx-metric.mauve::before { background: var(--fq-status-skipped); }
.clx-metric span, .clx-metric small { color: var(--fq-text-muted); font-size: 10px; }
.clx-metric strong { font-size: 19px; font-variant-numeric: tabular-nums; }
.clx-analysis-grid { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(330px, .85fr); gap: 14px; }
.clx-definition__dsl { padding: 12px; border-radius: 7px; background: var(--fq-panel-bg-muted); color: var(--fq-status-success); font: 11px/1.6 ui-monospace, Consolas, monospace; word-break: break-word; margin-bottom: 12px; }
.clx-definition__facts { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; border: 1px solid var(--fq-border-soft); background: var(--fq-border-soft); border-radius: 7px; overflow: hidden; }
.clx-definition__facts > div { display: flex; flex-direction: column; gap: 5px; padding: 10px; background: var(--fq-panel-bg-muted); min-width: 0; }
.clx-definition__facts span { font-size: 10px; color: var(--fq-text-muted); }
.clx-definition__facts b { font-size: 11px; font-weight: 500; word-break: break-all; }
.clx-definition__rules { display: flex; flex-direction: column; gap: 4px; margin-top: 10px; }
.clx-rule { display: grid; grid-template-columns: 24px 54px 58px 64px minmax(80px, 1fr); gap: 6px; align-items: center; padding: 7px; background: var(--fq-panel-bg-muted); border-radius: 6px; font-size: 10px; }
.clx-rule__index { display: grid; place-items: center; width: 20px; height: 20px; border-radius: 50%; color: var(--fq-panel-bg-muted); background: var(--fq-status-primary); }
:deep(.clx-table-primary) { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
:deep(.clx-table-primary strong) { font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
:deep(.clx-table-primary small) { font-size: 10px; color: var(--fq-text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
:deep(.clx-rank) { color: var(--fq-status-warning); font-variant-numeric: tabular-nums; }
:deep(.clx-row--selected td) { background: color-mix(in srgb, var(--fq-status-primary) 10%, var(--fq-panel-bg)) !important; }
@media (max-width: 1280px) { .clx-metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); } .clx-analysis-grid { grid-template-columns: 1fr; } }
@media (max-width: 780px) {
  .clx-toolbar, .clx-toolbar__run, .clx-selection-title { align-items: flex-start; flex-direction: column; }
  .clx-toolbar__run { width: 100%; } .clx-toolbar__run :deep(.el-select) { width: 100% !important; min-width: 0 !important; }
  .clx-toolbar__meta, .clx-selection-title__tags { justify-content: flex-start; }
  .clx-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .clx-filters > * { flex: 1 1 130px !important; width: auto !important; }
  .clx-ranking-card__hint { display: none; }
}
@media (max-width: 480px) { .clx-metrics { grid-template-columns: 1fr; } .clx-definition__facts { grid-template-columns: 1fr; } }
</style>
