<template>
  <div class="clx-compare" data-testid="clx-compare-panel">
    <section class="clx-compare__hero workbench-toolbar">
      <div>
        <span class="clx-section-kicker">FREEZE · REVEAL ONCE · AUDIT</span>
        <h2>组合对比与锁定测试</h2>
        <p>先在 TRAIN / VALIDATION 完成选择并冻结规则；HOLDOUT 只允许对冻结版本揭示一次。</p>
      </div>
      <div class="clx-compare__run">
        <label>已完成实验</label>
        <el-select v-model="selectedRunId" :loading="loading" filterable style="min-width: 300px" placeholder="选择实验">
          <el-option v-for="option in runOptions" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
      </div>
    </section>

    <el-alert v-if="error" type="error" :title="error" closable @close="error = ''" />
    <el-empty v-if="!loading && !runs.length" class="clx-page-empty" description="暂无可对比的已完成实验。" />

    <template v-else-if="selectedRun">
      <section class="clx-card workbench-panel clx-compare-controls">
        <div class="clx-compare-controls__selection">
          <el-select
            v-model="selectedComboIds"
            multiple
            filterable
            clearable
            collapse-tags
            :max-collapse-tags="4"
            :multiple-limit="4"
            placeholder="选择 2～4 个组合"
            style="min-width: 360px; flex: 1"
            aria-label="对比组合"
            @change="updateComboSelection"
          >
            <el-option v-for="option in comboOptions" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
          <el-select v-model="compareSplit" style="width: 180px" aria-label="对比样本段">
            <el-option v-for="option in compareSplitOptions" :key="option.value" :label="option.label" :value="option.value" :disabled="option.disabled" />
          </el-select>
          <el-input-number v-model="compareHorizon" :min="1" placeholder="周期（日）" style="width: 125px" />
          <el-button type="primary" :disabled="selectedComboIds.length < 2" :loading="comparing" data-testid="compare-button" @click="runComparison">开始对比</el-button>
        </div>
        <div class="clx-compare-controls__contract">
          <div><span>已选</span><b>{{ selectedComboIds.length }} / 4</b></div>
          <div><span>规则状态</span><b :class="selectedRun.frozen ? 'clx-negative' : 'clx-warning'">{{ selectedRun.frozen ? '已冻结' : '待冻结' }}</b></div>
          <div><span>HOLDOUT</span><b :class="selectedRun.holdoutRevealed ? 'clx-warning' : 'clx-negative'">{{ selectedRun.holdoutRevealed ? '已揭示（1/1）' : '封存中（0/1）' }}</b></div>
          <div><span>配置 SHA</span><b>{{ hashShort(selectedRun.configSha256) }}</b></div>
        </div>
        <div class="clx-compare-controls__actions">
          <el-button type="success" plain :disabled="selectedRun.frozen || !freezeReady" :loading="freezing" @click="confirmFreeze">冻结当前规则</el-button>
          <el-button type="warning" plain :disabled="!selectedRun.frozen || selectedRun.holdoutRevealed || !activeFreezeId" @click="openReveal">一次性揭示 HOLDOUT</el-button>
          <span>{{ freezeReadinessText }}</span>
        </div>
      </section>

      <section class="clx-card workbench-panel" data-testid="comparison-results">
        <div class="clx-card__header"><div><span class="clx-section-kicker">SIDE-BY-SIDE</span><h3>多组合指标与资金曲线</h3></div><el-tag size="small" effect="plain">{{ compareSplit }}</el-tag></div>
        <el-empty v-if="!comparison.items.length && !comparing" description="选择 2～4 个组合后开始对比；界面不会预填任何盈利结果。" />
        <div v-loading="comparing" class="clx-comparison-body">
          <template v-if="comparison.items.length">
            <el-table :data="comparison.items" :row-key="row => row.comboId" size="small">
              <el-table-column label="组合" width="250" fixed="left"><template #default="{ row }"><div class="clx-combo-cell"><strong>{{ row.name }}</strong><small>{{ row.comboId }}</small></div></template></el-table-column>
              <el-table-column label="总收益" width="100"><template #default="{ row }"><span :class="Number(row.metrics.totalReturn) >= 0 ? 'clx-positive' : 'clx-negative'">{{ formatPercent(row.metrics.totalReturn) }}</span></template></el-table-column>
              <el-table-column label="年化" width="94"><template #default="{ row }">{{ formatPercent(row.metrics.annualizedReturn) }}</template></el-table-column>
              <el-table-column label="Sharpe" width="86"><template #default="{ row }">{{ formatNumber(row.metrics.sharpe, 3) }}</template></el-table-column>
              <el-table-column label="最大回撤" width="96"><template #default="{ row }">{{ formatPercent(row.metrics.maxDrawdown) }}</template></el-table-column>
              <el-table-column label="胜率" width="84"><template #default="{ row }">{{ formatPercent(row.metrics.winRate) }}</template></el-table-column>
              <el-table-column label="稳定性" width="90"><template #default="{ row }">{{ formatPercent(row.metrics.stabilityScore) }}</template></el-table-column>
              <el-table-column label="FDR q" width="86"><template #default="{ row }">{{ formatPercent(row.metrics.fdrQValue) }}</template></el-table-column>
              <el-table-column label="样本数" width="88"><template #default="{ row }">{{ formatInteger(row.metrics.sampleCount) }}</template></el-table-column>
            </el-table>
            <ClxChart :option="comparisonOption" :empty="!hasComparisonCurve" height="420px" empty-text="API 尚未生成所选组合的资金曲线" />
          </template>
        </div>
      </section>

      <div class="clx-audit-grid">
        <section class="clx-card workbench-panel" data-testid="quality-report">
          <div class="clx-card__header"><div><span class="clx-section-kicker">DATA QUALITY</span><h3>质量审计与偏差披露</h3></div><el-tag :type="qualityTagType" size="small" effect="plain">{{ quality?.status ?? '待核验' }}</el-tag></div>
          <div class="clx-quality-stats">
            <div><span>源数据行</span><b>{{ formatInteger(quality?.sourceRows) }}</b></div><div><span>信号事实</span><b>{{ formatInteger(quality?.signalRows) }}</b></div><div><span>排除行</span><b>{{ formatInteger(quality?.excludedRows) }}</b></div><div><span>复权缺口</span><b>{{ formatInteger(quality?.adjustmentGapCount) }}</b></div>
          </div>
          <div class="clx-disclosures">
            <el-alert v-for="item in mandatoryDisclosures" :key="item.title" :type="item.type" :closable="false" :show-icon="false"><template #title><b>{{ item.title }}</b></template><span>{{ item.detail }}</span></el-alert>
          </div>
          <el-collapse v-if="quality?.issues.length" class="clx-findings">
            <el-collapse-item :title="`审计发现 (${quality.issues.length})`" name="findings">
              <div v-for="issue in quality.issues" :key="issue.code" class="clx-finding">
                <el-tag size="small" :type="issue.severity === 'ERROR' ? 'danger' : issue.severity === 'WARNING' ? 'warning' : 'info'" effect="plain">{{ issue.severity }}</el-tag>
                <div><b>{{ issue.title }}</b><p>{{ issue.detail }}</p></div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </section>

        <section class="clx-card workbench-panel" data-testid="manifest-card">
          <div class="clx-card__header"><div><span class="clx-section-kicker">REPRODUCIBILITY</span><h3>Manifest 与导出</h3></div><el-button size="small" link @click="copyManifest">复制 manifest</el-button></div>
          <div class="clx-manifest">
            <div><span>manifest SHA-256</span><code>{{ manifest?.sha256 ?? '--' }}</code></div><div><span>snapshot_id</span><code>{{ manifest?.snapshotId ?? '--' }}</code></div><div><span>signal_set_id</span><code>{{ manifest?.signalSetId ?? '--' }}</code></div><div><span>集合 UUID</span><code>{{ manifest?.sourceCollectionUuid ?? '--' }}</code></div><div><span>日期范围</span><code>{{ manifest?.dateMin ?? '--' }} ～ {{ manifest?.dateMax ?? '--' }}</code></div><div><span>代码 / 行数</span><code>{{ formatInteger(manifest?.codeCount) }} / {{ formatInteger(manifest?.sourceCount) }}</code></div><div><span>artifact</span><code>{{ manifest?.artifactUri ?? '--' }}</code></div>
          </div>
          <el-collapse><el-collapse-item title="原始 manifest JSON" name="manifest"><pre>{{ manifestJson }}</pre></el-collapse-item></el-collapse>
          <div class="clx-export">
            <el-select v-model="exportForm.resource" size="small" style="width: 130px"><el-option v-for="option in exportResourceOptions" :key="option.value" :label="option.label" :value="option.value" /></el-select>
            <el-select v-model="exportForm.format" size="small" style="width: 105px"><el-option v-for="option in exportFormatOptions" :key="option.value" :label="option.label" :value="option.value" /></el-select>
            <el-button size="small" type="primary" plain :disabled="!selectedComboIds.length" :loading="exporting" @click="startExport">创建可审计导出</el-button>
          </div>
          <div v-if="exportJobs.length" class="clx-export-jobs">
            <div v-for="job in exportJobs" :key="job.jobId"><span>{{ job.resource }}.{{ job.format }} · {{ job.splitId ?? compareSplit }}</span><el-tag size="small" :type="job.status === 'FAILED' ? 'danger' : job.status === 'COMPLETE' ? 'success' : 'info'" effect="plain">{{ job.status }}</el-tag><a v-if="job.downloadUrl" class="fq-link" :href="job.downloadUrl" target="_blank" rel="noopener">下载</a><small v-else>{{ job.jobId }}</small></div>
          </div>
        </section>
      </div>
    </template>

    <el-dialog v-model="revealVisible" title="一次性揭示锁定测试集" width="min(570px, 94vw)" :close-on-click-modal="false">
      <el-alert type="warning" :closable="false" show-icon title="此操作会永久记录 HOLDOUT 揭示时间与次数。揭示后不可重新冻结、重新筛选或再次揭示来挑选更好结果。" />
      <div class="clx-reveal-summary"><div><span>实验</span><b>{{ selectedRun?.name }}</b></div><div><span>freeze_id</span><code>{{ activeFreezeId }}</code></div><div><span>冻结组合数</span><b>{{ freezeMaterial.selectedComboIds.length }}</b></div><div><span>配置 SHA</span><code>{{ selectedRun?.configSha256 }}</code></div></div>
      <el-checkbox v-model="revealAcknowledged">我确认当前规则已冻结，理解 HOLDOUT 只有一次揭示机会。</el-checkbox>
      <el-input v-model="revealPhrase" placeholder="输入：揭示HOLDOUT" style="margin-top: 12px" data-testid="reveal-phrase" />
      <template #footer><div class="clx-modal-actions"><el-button @click="revealVisible = false">取消</el-button><el-button type="warning" :disabled="!canReveal" :loading="revealing" data-testid="confirm-reveal" @click="revealHoldout">确认永久揭示</el-button></div></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { clxBacktestApi, describeApiError } from "@/api/clxBacktestApi";
import { buildFrozenRankDigest } from "@/utils/clxFreeze";
import { formatInteger, formatNumber, formatPercent, hashShort } from "@/utils/clxFormat";
import ClxChart from "./ClxChart.vue";
const message = ElMessage;
const runs = ref([]);
const rankings = ref([]);
const selectedRunId = ref(null);
const selectedComboIds = ref([]);
const compareSplit = ref("VALIDATION");
const compareHorizon = ref(null);
const comparison = ref({ runId: "", splitId: "VALIDATION", items: [] });
const quality = ref(null);
const manifest = ref(null);
const loading = ref(false);
const comparing = ref(false);
const freezing = ref(false);
const revealing = ref(false);
const exporting = ref(false);
const error = ref("");
const activeFreezeId = ref(null);
const revealVisible = ref(false);
const revealAcknowledged = ref(false);
const revealPhrase = ref("");
const exportJobs = ref([]);
const exportForm = reactive({ resource: "metrics", format: "csv" });
const runOptions = computed(() => runs.value.map((run) => ({ label: `${run.name} \xB7 ${run.runId}`, value: run.runId })));
const selectedRun = computed(() => runs.value.find((run) => run.runId === selectedRunId.value) ?? null);
const comboOptions = computed(() => rankings.value.map((row) => ({ label: `#${row.rank} ${row.name}`, value: row.comboId })));
const compareSplitOptions = computed(() => [
  { label: "\u7814\u7A76\u96C6 TRAIN", value: "TRAIN" },
  { label: "\u9A8C\u8BC1\u96C6 VALIDATION", value: "VALIDATION" },
  { label: selectedRun.value?.holdoutRevealed ? "\u9501\u5B9A\u6D4B\u8BD5 HOLDOUT" : "\u9501\u5B9A\u6D4B\u8BD5 HOLDOUT\uFF08\u5C01\u5B58\uFF09", value: "HOLDOUT", disabled: !selectedRun.value?.holdoutRevealed }
]);
const canReveal = computed(() => revealAcknowledged.value && revealPhrase.value.trim() === "\u63ED\u793AHOLDOUT" && Boolean(activeFreezeId.value));
const qualityTagType = computed(() => quality.value?.status === "PASS" ? "success" : quality.value?.issues.some((item) => item.severity === "ERROR") ? "danger" : "warning");
const hasComparisonCurve = computed(() => comparison.value.items.some((item) => item.equity?.length));
const manifestJson = computed(() => JSON.stringify(manifest.value?.payload ?? manifest.value ?? {}, null, 2));
const exportResourceOptions = ["rankings", "metrics", "equity", "trades", "signals"].map((value) => ({ label: value, value }));
const exportFormatOptions = ["csv", "json", "parquet"].map((value) => ({ label: value.toUpperCase(), value }));
const objectRecord = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};
const freezeMaterial = computed(() => {
  const payload = objectRecord(manifest.value?.payload);
  const freezeInput = objectRecord(payload.freeze_input);
  const freezeValidation = objectRecord(freezeInput.validation);
  const rankingConfig = objectRecord(freezeInput.ranking_config);
  const rankOrder = Array.isArray(freezeValidation.rank_order) ? freezeValidation.rank_order.map(String) : [];
  const frozenSelectedComboIds = Array.isArray(freezeValidation.selected_combo_ids) ? freezeValidation.selected_combo_ids.map(String) : [];
  return {
    rankingConfig,
    rankOrder,
    selectedComboIds: frozenSelectedComboIds,
    rankingConfigSha256: String(freezeInput.ranking_config_sha256 ?? ""),
    splitConfigSha256: String(freezeInput.split_config_sha256 ?? ""),
    suppliedFrozenRankDigest: String(freezeInput.frozen_rank_digest ?? "")
  };
});
const freezeReady = computed(() => {
  const material = freezeMaterial.value;
  return Boolean(
    material.selectedComboIds.length && material.rankOrder.length && material.selectedComboIds.every((comboId) => material.rankOrder.includes(comboId)) && Object.keys(material.rankingConfig).length && /^sha256:[0-9a-f]{64}$/.test(material.rankingConfigSha256) && /^sha256:[0-9a-f]{64}$/.test(material.splitConfigSha256) && /^sha256:[0-9a-f]{64}$/.test(material.suppliedFrozenRankDigest)
  );
});
const freezeReadinessText = computed(() => freezeReady.value ? `服务端已发布完整 VALIDATION 排名与固定入选 ${freezeMaterial.value.selectedComboIds.length} 项。` : "等待 manifest.freeze_input 发布完整排名、入选组合及校验哈希。");
const mandatoryDisclosures = computed(() => [
  { type: "warning", title: "\u5E78\u5B58\u8005\u504F\u5DEE", detail: "\u5F53\u524D\u80A1\u7968\u6C60\u4E0E\u5386\u53F2\u8BC1\u5238\u72B6\u6001\u5E76\u975E\u5B8C\u6574\u7684 point-in-time universe\uFF0C\u8DE8\u5E74\u4EE3\u8868\u73B0\u53EF\u80FD\u504F\u4E50\u89C2\u3002" },
  { type: "warning", title: "\u5386\u53F2 ST / \u9000\u5E02\u72B6\u6001", detail: "\u5386\u53F2 ST\u3001\u9000\u5E02\u4E0E IPO \u65E0\u6DA8\u8DCC\u5E45\u9636\u6BB5\u4FE1\u606F\u4E0D\u5B8C\u6574\uFF1B\u53EF\u4EA4\u6613\u6027\u5224\u65AD\u5305\u542B\u8FD1\u4F3C\u3002" },
  { type: quality.value?.adjustmentGapCount ? "warning" : "info", title: "\u590D\u6743\u4E0E\u516C\u53F8\u884C\u52A8", detail: quality.value?.adjustmentGapCount !== void 0 ? `\u672C run manifest \u8BB0\u5F55 ${quality.value.adjustmentGapCount} \u6761\u590D\u6743\u7F3A\u53E3\uFF1B\u4FEE\u590D\u6216\u9694\u79BB\u660E\u7EC6\u4EE5\u8D28\u91CF artifact \u4E3A\u51C6\u3002` : "\u590D\u6743\u7F3A\u53E3\u3001\u4FEE\u590D\u548C\u9694\u79BB\u8303\u56F4\u4EE5\u672C run manifest \u4E3A\u51C6\uFF1B\u516C\u53F8\u884C\u52A8\u672A\u5B8C\u6574\u8FDB\u5165\u73B0\u91D1\u8D26\u3002" },
  { type: "info", title: "\u6210\u4EA4\u5236\u5EA6\u8FD1\u4F3C", detail: "\u5DF2\u5EFA\u6A21 T+1\u3001\u6DA8\u8DCC\u505C\u3001\u505C\u724C\u3001\u6574\u624B\u548C\u8D39\u7528\uFF1B\u5F00\u76D8\u5BB9\u91CF\u3001\u90E8\u5206\u6210\u4EA4\u7B49\u5E02\u573A\u51B2\u51FB\u5C1A\u672A\u5B8C\u6574\u5EFA\u6A21\u3002" }
]);
const comparisonOption = computed(() => {
  const colors = ["#89b4fa", "#f38ba8", "#94e2d5", "#f9e2af"];
  return {
    animationDuration: 350,
    color: colors,
    backgroundColor: "transparent",
    tooltip: { trigger: "axis", confine: true },
    legend: { top: 4, textStyle: { color: "#a6adc8" } },
    grid: { left: 60, right: 24, top: 44, bottom: 46 },
    xAxis: { type: "category", data: comparison.value.items.find((item) => item.equity?.length)?.equity?.map((point) => point.date) ?? [], axisLabel: { color: "#a6adc8", fontSize: 9 }, axisLine: { lineStyle: { color: "#45475a" } } },
    yAxis: { type: "value", scale: true, axisLabel: { color: "#a6adc8" }, splitLine: { lineStyle: { color: "rgba(255,255,255,.05)" } } },
    dataZoom: [{ type: "inside" }, { type: "slider", bottom: 6, height: 16 }],
    series: comparison.value.items.map((item, index) => {
      const first = item.equity?.[0]?.equity || 1;
      return { name: item.name, type: "line", showSymbol: false, lineStyle: { width: 2, color: colors[index] }, data: item.equity?.map((point) => point.equity / first) ?? [] };
    })
  };
});
function updateComboSelection(values) {
  if (values.length > 4) {
    message.warning("\u540C\u5C4F\u6700\u591A\u5BF9\u6BD4 4 \u4E2A\u7EC4\u5408");
    return;
  }
  selectedComboIds.value = values;
}
async function loadRuns() {
  loading.value = true;
  error.value = "";
  try {
    const page = await clxBacktestApi.listRuns({ status: "COMPLETE", pageSize: 100 });
    runs.value = page.items;
    if (!selectedRunId.value && runs.value.length) selectedRunId.value = runs.value[0].runId;
  } catch (reason) {
    error.value = describeApiError(reason);
  } finally {
    loading.value = false;
  }
}
async function loadValidationRankings(runId) {
  const items = [];
  let cursor;
  for (let pageIndex = 0; pageIndex < 50; pageIndex += 1) {
    const page = await clxBacktestApi.listRankings(runId, { splitId: "VALIDATION", pageSize: 200, cursor });
    items.push(...page.items);
    if (!page.nextCursor) return items;
    cursor = page.nextCursor;
  }
  throw new Error("VALIDATION \u6392\u540D\u8D85\u8FC7 10,000 \u6761\uFF0C\u51BB\u7ED3\u6750\u6599\u672A\u5B8C\u6574\u52A0\u8F7D");
}
async function loadRunData() {
  const runId = selectedRunId.value;
  if (!runId) return;
  loading.value = true;
  selectedComboIds.value = [];
  comparison.value = { runId, splitId: "VALIDATION", items: [] };
  exportJobs.value = [];
  const results = await Promise.allSettled([
    loadValidationRankings(runId),
    clxBacktestApi.getQuality(runId),
    clxBacktestApi.getManifest(runId),
    clxBacktestApi.getRun(runId)
  ]);
  rankings.value = results[0].status === "fulfilled" ? results[0].value : [];
  quality.value = results[1].status === "fulfilled" ? results[1].value : null;
  manifest.value = results[2].status === "fulfilled" ? results[2].value : null;
  if (results[3].status === "fulfilled") {
    const fresh = results[3].value;
    const index = runs.value.findIndex((run) => run.runId === fresh.runId);
    if (index >= 0) runs.value[index] = fresh;
    activeFreezeId.value = fresh.freezeId ?? null;
    if (!fresh.holdoutRevealed && compareSplit.value === "HOLDOUT") compareSplit.value = "VALIDATION";
  } else activeFreezeId.value = selectedRun.value?.freezeId ?? null;
  const rejected = results.find((item) => item.status === "rejected");
  if (rejected) error.value = `\u90E8\u5206\u5BA1\u8BA1\u6570\u636E\u52A0\u8F7D\u5931\u8D25\uFF1A${describeApiError(rejected.reason)}`;
  loading.value = false;
}
async function runComparison() {
  if (!selectedRunId.value || selectedComboIds.value.length < 2) return;
  comparing.value = true;
  error.value = "";
  try {
    const result = await clxBacktestApi.compare(selectedRunId.value, selectedComboIds.value, compareSplit.value, compareHorizon.value ?? void 0);
    const byId = new Map(result.items.map((item) => [item.comboId, item]));
    const curves = await Promise.allSettled(selectedComboIds.value.map((comboId) => clxBacktestApi.getEquity(selectedRunId.value, comboId, { splitId: compareSplit.value })));
    comparison.value = {
      ...result,
      items: selectedComboIds.value.map((comboId, index) => {
        const ranking = rankings.value.find((item2) => item2.comboId === comboId);
        const item = byId.get(comboId) ?? { comboId, name: ranking?.name ?? comboId, metrics: ranking?.metrics ?? {} };
        return { ...item, equity: curves[index].status === "fulfilled" ? curves[index].value.items : item.equity ?? [] };
      })
    };
  } catch (reason) {
    error.value = describeApiError(reason);
  } finally {
    comparing.value = false;
  }
}
function confirmFreeze() {
  if (!selectedRun.value) return;
  ElMessageBox.confirm(
    `将冻结服务端固定入选的 ${freezeMaterial.value.selectedComboIds.length} 个组合及完整 VALIDATION 排序口径。当前 2～4 项同屏对比不改变冻结范围。冻结后只允许一次 HOLDOUT 揭示。`,
    "\u51BB\u7ED3\u7814\u7A76\u89C4\u5219\uFF1F",
    { confirmButtonText: "\u786E\u8BA4\u51BB\u7ED3", cancelButtonText: "\u7EE7\u7EED\u68C0\u67E5", type: "warning" }
  ).then(freezeRun).catch(() => {
  });
}
async function freezeRun() {
  if (!selectedRunId.value) return;
  freezing.value = true;
  try {
    const material = freezeMaterial.value;
    if (!freezeReady.value) throw new Error("manifest \u51BB\u7ED3\u6750\u6599\u4E0D\u5B8C\u6574");
    const { rankingConfigSha256, frozenRankDigest } = await buildFrozenRankDigest(
      selectedRunId.value,
      material.rankOrder,
      material.rankingConfig
    );
    if (material.rankingConfigSha256 !== rankingConfigSha256) {
      throw new Error("freeze_input 的 ranking_config_sha256 校验失败");
    }
    const factHashes = [...new Set(rankings.value.map((item) => item.rankingConfigSha256).filter(Boolean))];
    if (factHashes.length && (factHashes.length !== 1 || factHashes[0] !== rankingConfigSha256)) {
      throw new Error("ranking_config \u4E0E VALIDATION \u6392\u540D\u4E8B\u5B9E\u4E0D\u4E00\u81F4");
    }
    if (material.suppliedFrozenRankDigest && material.suppliedFrozenRankDigest !== frozenRankDigest) {
      throw new Error("freeze_input \u7684 frozen_rank_digest \u6821\u9A8C\u5931\u8D25");
    }
    const freeze = await clxBacktestApi.freezeRun(selectedRunId.value, {
      validation: {
        selectedComboIds: material.selectedComboIds,
        rankOrder: material.rankOrder
      },
      rankingConfig: material.rankingConfig,
      splitConfigSha256: material.splitConfigSha256,
      frozenRankDigest
    });
    activeFreezeId.value = freeze.freezeId;
    const run = selectedRun.value;
    if (run) {
      run.frozen = true;
      run.freezeId = freeze.freezeId;
    }
    message.success("\u7814\u7A76\u89C4\u5219\u5DF2\u51BB\u7ED3\u5E76\u8BB0\u5F55\u54C8\u5E0C");
  } catch (reason) {
    error.value = describeApiError(reason);
  } finally {
    freezing.value = false;
  }
}
function openReveal() {
  revealAcknowledged.value = false;
  revealPhrase.value = "";
  revealVisible.value = true;
}
async function revealHoldout() {
  if (!selectedRunId.value || !activeFreezeId.value || !canReveal.value) return;
  revealing.value = true;
  try {
    await clxBacktestApi.revealHoldout(selectedRunId.value, activeFreezeId.value);
    if (selectedRun.value) selectedRun.value.holdoutRevealed = true;
    revealVisible.value = false;
    compareSplit.value = "HOLDOUT";
    message.warning("HOLDOUT \u5DF2\u5B8C\u6210\u552F\u4E00\u4E00\u6B21\u63ED\u793A\uFF0C\u64CD\u4F5C\u5DF2\u5199\u5165\u5BA1\u8BA1\u4E8B\u5B9E");
    await loadRunData();
  } catch (reason) {
    error.value = describeApiError(reason);
  } finally {
    revealing.value = false;
  }
}
async function startExport() {
  if (!selectedRunId.value || !selectedComboIds.value.length) return;
  exporting.value = true;
  try {
    const job = await clxBacktestApi.createExport(selectedRunId.value, {
      ...exportForm,
      comboIds: selectedComboIds.value,
      splitId: compareSplit.value
    });
    exportJobs.value.unshift(job);
    message.success("\u5BFC\u51FA\u4EFB\u52A1\u5DF2\u5165\u961F");
    pollExport(job);
  } catch (reason) {
    error.value = describeApiError(reason);
  } finally {
    exporting.value = false;
  }
}
async function pollExport(job, attempt = 0) {
  if (attempt >= 8 || ["COMPLETE", "FAILED"].includes(job.status)) return;
  setTimeout(async () => {
    try {
      const updated = await clxBacktestApi.getExport(job.jobId);
      const index = exportJobs.value.findIndex((item) => item.jobId === job.jobId);
      if (index >= 0) exportJobs.value[index] = updated;
      pollExport(updated, attempt + 1);
    } catch {
    }
  }, 1500 * (attempt + 1));
}
async function copyManifest() {
  await navigator.clipboard?.writeText(manifestJson.value);
  message.success("manifest JSON \u5DF2\u590D\u5236");
}
watch(selectedRunId, loadRunData);
onMounted(loadRuns);
</script>

<style scoped>
.clx-compare { display: flex; flex-direction: column; gap: 14px; }
.clx-compare__hero { display: flex; justify-content: space-between; align-items: flex-start; gap: 18px; }.clx-compare__hero h2 { margin: 3px 0; font-size: 17px; }.clx-compare__hero p { margin: 0; color: var(--fq-text-muted); font-size: 12px; }.clx-section-kicker { color: var(--fq-text-muted); font-size: 10px; letter-spacing: .09em; }
.clx-compare__run { display: flex; align-items: center; gap: 8px; }.clx-compare__run label { color: var(--fq-text-muted); font-size: 11px; white-space: nowrap; }.clx-page-empty { padding: 60px 0; border: 1px dashed var(--fq-border-soft); border-radius: 10px; }
.clx-card { background: var(--fq-panel-bg); border: 1px solid var(--fq-border-soft); border-radius: 10px; padding: 16px; min-width: 0; }.clx-card__header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }.clx-card__header h3 { margin: 3px 0 0; font-size: 14px; }
.clx-compare-controls__selection, .clx-compare-controls__actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }.clx-compare-controls__contract { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; overflow: hidden; border: 1px solid var(--fq-border-soft); border-radius: 8px; background: var(--fq-border-soft); margin: 12px 0; }.clx-compare-controls__contract > div { display: flex; flex-direction: column; gap: 5px; padding: 10px 12px; background: var(--fq-panel-bg-muted); }.clx-compare-controls__contract span { color: var(--fq-text-muted); font-size: 10px; }.clx-compare-controls__contract b { font-size: 11px; word-break: break-word; }.clx-compare-controls__actions span { color: var(--fq-text-muted); font-size: 10px; }
.clx-audit-grid { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(380px, .85fr); gap: 14px; }.clx-quality-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }.clx-quality-stats div { display: flex; flex-direction: column; gap: 4px; padding: 10px; border-radius: 7px; background: var(--fq-panel-bg-muted); }.clx-quality-stats span { color: var(--fq-text-muted); font-size: 10px; }.clx-quality-stats b { font-size: 15px; }
.clx-disclosures { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; }.clx-disclosures :deep(.el-alert__content) { font-size: 10px; line-height: 1.5; }.clx-findings { margin-top: 10px; }.clx-finding { display: flex; gap: 8px; align-items: flex-start; padding: 7px 0; border-bottom: 1px solid var(--fq-border-soft); }.clx-finding b { font-size: 11px; }.clx-finding p { margin: 3px 0 0; color: var(--fq-text-muted); font-size: 10px; }
.clx-manifest { display: flex; flex-direction: column; border: 1px solid var(--fq-border-soft); border-radius: 7px; overflow: hidden; }.clx-manifest > div { display: grid; grid-template-columns: 135px minmax(0, 1fr); gap: 8px; padding: 8px 10px; background: var(--fq-panel-bg-muted); border-bottom: 1px solid var(--fq-border-soft); }.clx-manifest > div:last-child { border-bottom: 0; }.clx-manifest span { color: var(--fq-text-muted); font-size: 10px; }.clx-manifest code { color: var(--fq-status-success); font-size: 9px; overflow-wrap: anywhere; }.clx-card pre { max-height: 230px; overflow: auto; color: var(--fq-text-muted); font: 10px/1.55 ui-monospace, Consolas, monospace; white-space: pre-wrap; }
.clx-export { display: flex; gap: 7px; align-items: center; flex-wrap: wrap; padding-top: 12px; border-top: 1px solid var(--fq-border-soft); }.clx-export-jobs { display: flex; flex-direction: column; gap: 5px; margin-top: 10px; }.clx-export-jobs > div { display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 8px; padding: 7px 9px; background: var(--fq-panel-bg-muted); border-radius: 6px; font-size: 10px; }.clx-export-jobs small { color: var(--fq-text-muted); }
.clx-reveal-summary { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; margin: 14px 0; border-radius: 7px; overflow: hidden; background: var(--fq-border-soft); border: 1px solid var(--fq-border-soft); }.clx-reveal-summary div { display: flex; flex-direction: column; gap: 4px; padding: 9px; background: var(--fq-panel-bg-muted); }.clx-reveal-summary span { color: var(--fq-text-muted); font-size: 10px; }.clx-reveal-summary b, .clx-reveal-summary code { font-size: 10px; word-break: break-all; }.clx-modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
:deep(.clx-combo-cell) { display: flex; flex-direction: column; gap: 3px; }:deep(.clx-combo-cell strong) { font-size: 11px; }:deep(.clx-combo-cell small) { color: var(--fq-text-muted); font-size: 9px; }
@media (max-width: 1100px) { .clx-audit-grid { grid-template-columns: 1fr; } }
@media (max-width: 760px) { .clx-compare__hero, .clx-compare__run { flex-direction: column; }.clx-compare__run { width: 100%; align-items: stretch; }.clx-compare__run :deep(.el-select) { width: 100% !important; min-width: 0 !important; }.clx-compare-controls__selection > * { flex: 1 1 140px !important; min-width: 0 !important; width: auto !important; }.clx-compare-controls__contract, .clx-quality-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 480px) { .clx-compare-controls__contract, .clx-quality-stats, .clx-reveal-summary { grid-template-columns: 1fr; }.clx-manifest > div { grid-template-columns: 1fr; } }
</style>
