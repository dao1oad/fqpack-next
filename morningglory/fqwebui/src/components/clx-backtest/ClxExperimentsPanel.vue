<template>
  <div class="clx-experiments" data-testid="clx-experiments-panel">
    <div class="clx-experiments__actions workbench-toolbar">
      <div><span class="clx-section-kicker">REPRODUCIBLE RUNS</span><h2>实验运行与不可变配置</h2><p>草稿可克隆；启动后配置由 SHA-256 固化，外部 worker 按阶段写入进度事实。</p></div>
      <el-button type="primary" data-testid="create-run-button" @click="openCreate">+ 新建实验</el-button>
    </div>

    <el-alert v-if="error" type="error" :closable="true" @close="error = ''"><template #title>{{ error }}</template><el-button size="small" link @click="loadRuns">重试</el-button></el-alert>

    <div class="clx-experiments__layout">
      <section class="clx-card workbench-panel clx-runs">
        <div class="clx-card__header">
          <h3>实验清单</h3>
          <div class="clx-card__header-actions">
            <el-select v-model="statusFilter" clearable size="small" placeholder="全部状态" style="width: 135px" @change="loadRuns"><el-option v-for="option in statusOptions" :key="option.value" :label="option.label" :value="option.value" /></el-select>
            <el-button size="small" link :loading="loading" @click="loadRuns">刷新</el-button>
          </div>
        </div>
        <div v-loading="loading" class="clx-run-list-shell">
          <el-empty v-if="!runs.length && !loading" description="暂无实验，创建首个不可变研究配置。" />
          <div v-else class="clx-run-list">
            <article v-for="run in runs" :key="run.runId" class="clx-run" :class="{ 'clx-run--selected': selectedRunId === run.runId }" :data-testid="`run-${run.runId}`" @click="selectRun(run)">
              <div class="clx-run__top"><div class="clx-run__identity"><strong>{{ run.name }}</strong><code>{{ run.runId }}</code></div><RunStatusTag :status="run.status" /></div>
              <div class="clx-run__meta"><span>SHA {{ hashShort(run.configSha256) }}</span><span>{{ formatDateTime(run.updatedAt || run.createdAt) }}</span><span v-if="run.lineage?.clonedFromRunId || run.lineage?.parentRunId">克隆自 {{ hashShort(String(run.lineage.clonedFromRunId || run.lineage.parentRunId), 10) }}</span></div>
              <div class="clx-run__buttons" @click.stop>
                <el-button size="small" link @click="showConfig(run)">配置</el-button>
                <el-button size="small" link :loading="actionRunId === run.runId && actionName === 'clone'" @click="cloneRun(run)">克隆</el-button>
                <el-button v-if="run.status === 'DRAFT'" size="small" type="primary" :loading="actionRunId === run.runId && actionName === 'start'" @click="confirmStart(run)">启动</el-button>
                <el-button v-if="['QUEUED', 'RUNNING'].includes(run.status)" size="small" type="warning" plain :loading="actionRunId === run.runId && actionName === 'cancel'" @click="confirmCancel(run)">取消</el-button>
                <el-button v-if="run.status === 'COMPLETE'" size="small" type="success" plain @click="$emit('open-results', run.runId)">查看结果</el-button>
              </div>
            </article>
          </div>
        </div>
      </section>

      <section class="clx-card workbench-panel clx-progress" data-testid="run-progress">
        <div class="clx-card__header"><div><span class="clx-section-kicker">LIVE PROGRESS</span><h3>{{ selectedRun?.name ?? '运行进度' }}</h3></div><RunStatusTag v-if="selectedRun" :status="selectedRun.status" /></div>
        <el-empty v-if="!selectedRun" description="从左侧选择一个实验查看运行事实。" />
        <template v-else>
          <div class="clx-progress__hero">
            <el-progress :percentage="displayProgress" :status="progressStatus" :stroke-width="10" :text-inside="true" />
            <div class="clx-progress__stage"><strong>{{ progress?.stage || stageFallback }}</strong><span>{{ progress?.message || statusDescription }}</span></div>
            <div v-if="progress?.total" class="clx-progress__counts">{{ formatInteger(progress.completed) }} / {{ formatInteger(progress.total) }}</div>
          </div>
          <div class="clx-progress__stream-state"><span class="clx-live-dot" :class="{ 'clx-live-dot--off': !streamConnected }" />{{ streamConnected ? '实时事件已连接' : '轮询进度快照' }}<span v-if="progress?.updatedAt"> · {{ formatDateTime(progress.updatedAt) }}</span></div>
          <el-timeline class="clx-progress__timeline">
            <el-timeline-item v-for="(event, index) in orderedEvents" :key="event.eventId || `${event.at}-${index}`" :type="eventType(event.level)" :timestamp="formatDateTime(event.at)" placement="top">
              <strong class="clx-event-stage">{{ event.stage || '运行事件' }}</strong><div class="clx-event-message">{{ event.message }}</div><div v-if="event.percent !== undefined" class="clx-event-percent">{{ progressPercent(event.percent) }}%</div>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-if="!orderedEvents.length" :image-size="54" description="任务尚未写入进度事件" />
        </template>
      </section>
    </div>

    <el-dialog v-model="createVisible" title="新建 CLX 回测实验" width="min(760px, 94vw)" :close-on-click-modal="false">
      <el-alert type="info" :closable="false" title="创建的是可编辑草稿；点击启动后配置与数据 manifest 一并固化。" style="margin-bottom: 14px" />
      <el-form ref="formRef" :model="form" :rules="formRules" label-position="top" size="small">
        <div class="clx-form-grid">
          <el-form-item label="实验名称" prop="name" class="clx-form-wide"><el-input v-model="form.name" placeholder="例如：CLX 全模型验证集基线" /></el-form-item>
          <el-form-item label="数据快照 ID" prop="snapshotId" class="clx-form-wide"><el-input v-model="form.snapshotId" placeholder="不可变 snapshot_id" /></el-form-item>
          <el-form-item label="TRAIN 起始" prop="trainStart"><el-date-picker v-model="form.trainStart" value-format="YYYY-MM-DD" type="date" style="width: 100%" /></el-form-item>
          <el-form-item label="TRAIN 结束" prop="trainEnd"><el-date-picker v-model="form.trainEnd" value-format="YYYY-MM-DD" type="date" style="width: 100%" /></el-form-item>
          <el-form-item label="VALIDATION 起始" prop="validationStart"><el-date-picker v-model="form.validationStart" value-format="YYYY-MM-DD" type="date" style="width: 100%" /></el-form-item>
          <el-form-item label="VALIDATION 结束" prop="validationEnd"><el-date-picker v-model="form.validationEnd" value-format="YYYY-MM-DD" type="date" style="width: 100%" /></el-form-item>
          <el-form-item label="HOLDOUT 起始" prop="holdoutStart"><el-date-picker v-model="form.holdoutStart" value-format="YYYY-MM-DD" type="date" style="width: 100%" /></el-form-item>
          <el-form-item label="HOLDOUT 结束" prop="holdoutEnd"><el-date-picker v-model="form.holdoutEnd" value-format="YYYY-MM-DD" type="date" style="width: 100%" /></el-form-item>
          <el-form-item label="初始资金" prop="initialCash"><el-input-number v-model="form.initialCash" :min="10000" :step="100000" style="width: 100%" /></el-form-item>
          <el-form-item label="最大持仓数" prop="maxPositions"><el-input-number v-model="form.maxPositions" :min="1" :max="100" style="width: 100%" /></el-form-item>
          <el-form-item label="评估周期（日）" prop="horizons" class="clx-form-wide">
            <el-select v-model="form.horizons" multiple filterable allow-create default-first-option placeholder="输入周期后回车"><el-option v-for="horizon in ['1', '3', '5', '10', '20']" :key="horizon" :label="`${horizon} 日`" :value="horizon" /></el-select>
          </el-form-item>
          <el-form-item label="组合 DSL（可留空，后续由排行生成）" class="clx-form-wide"><el-input v-model="form.combinationDsl" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" placeholder="示例仅描述结构，不预设收益：ALL_OF(MODEL(...), TRIGGER(...))" /></el-form-item>
        </div>
        <div class="clx-fixed-contract"><div><span>模型</span><b>S0000～S0017（18 个）</b></div><div><span>参数</span><b>WAVEOPT=1560 · STRETCH/EXT/TREND=0</b></div><div><span>撮合</span><b>T 收盘确认 → T+1 开盘</b></div></div>
      </el-form>
      <template #footer><div class="clx-modal-actions"><el-button @click="createVisible = false">取消</el-button><el-button type="primary" :loading="creating" data-testid="submit-create-run" @click="createRun">创建草稿</el-button></div></template>
    </el-dialog>

    <el-drawer v-model="configVisible" title="不可变配置与血缘" size="min(820px, 94vw)"><ImmutableConfigSummary v-if="configRun" :run="configRun" /></el-drawer>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { clxBacktestApi, describeApiError } from "@/api/clxBacktestApi";
import { formatDateTime, formatInteger, hashShort, runStatusMeta } from "@/utils/clxFormat";
import RunStatusTag from "./RunStatusTag.vue";
import ImmutableConfigSummary from "./ImmutableConfigSummary.vue";
defineEmits(["open-results"]);
const message = ElMessage;
const runs = ref([]);
const loading = ref(false);
const error = ref("");
const statusFilter = ref(null);
const selectedRunId = ref(null);
const progress = ref(null);
const streamConnected = ref(false);
const actionRunId = ref("");
const actionName = ref("");
const createVisible = ref(false);
const creating = ref(false);
const configVisible = ref(false);
const configRun = ref(null);
const formRef = ref(null);
let pollTimer = null;
let eventSource = null;
const statusOptions = Object.entries(runStatusMeta).map(([value, meta]) => ({ label: meta.label, value }));
const selectedRun = computed(() => runs.value.find((run) => run.runId === selectedRunId.value) ?? null);
const orderedEvents = computed(() => [...progress.value?.events ?? []].reverse());
const displayProgress = computed(() => progressPercent(progress.value?.percent ?? (selectedRun.value?.status === "COMPLETE" ? 100 : 0)));
const progressStatus = computed(() => selectedRun.value?.status === "FAILED" ? "exception" : selectedRun.value?.status === "COMPLETE" ? "success" : void 0);
const stageFallback = computed(() => ({ DRAFT: "\u7B49\u5F85\u542F\u52A8", QUEUED: "\u7B49\u5F85 worker", RUNNING: "\u6267\u884C\u4E2D", CANCEL_REQUESTED: "\u6B63\u5728\u53D6\u6D88", CANCELLED: "\u5DF2\u53D6\u6D88", FAILED: "\u6267\u884C\u5931\u8D25", COMPLETE: "\u6267\u884C\u5B8C\u6210" })[selectedRun.value?.status ?? "DRAFT"]);
const statusDescription = computed(() => selectedRun.value ? runStatusMeta[selectedRun.value.status]?.label : "");
const emptyForm = () => ({
  name: "",
  snapshotId: "",
  trainStart: null,
  trainEnd: null,
  validationStart: null,
  validationEnd: null,
  holdoutStart: null,
  holdoutEnd: null,
  initialCash: 1e7,
  maxPositions: 10,
  horizons: ["1", "3", "5", "10", "20"],
  combinationDsl: ""
});
const form = reactive(emptyForm());
const formRules = {
  name: [{ required: true, message: "\u8BF7\u8F93\u5165\u5B9E\u9A8C\u540D\u79F0", trigger: ["blur", "input"] }],
  snapshotId: [{ required: true, message: "\u8BF7\u8F93\u5165\u4E0D\u53EF\u53D8\u6570\u636E\u5FEB\u7167 ID", trigger: ["blur", "input"] }],
  trainStart: [{ required: true, message: "\u8BF7\u9009\u62E9 TRAIN \u8D77\u59CB\u65E5", trigger: "change" }],
  trainEnd: [{ required: true, message: "\u8BF7\u9009\u62E9 TRAIN \u7ED3\u675F\u65E5", trigger: "change" }],
  validationStart: [{ required: true, message: "\u8BF7\u9009\u62E9 VALIDATION \u8D77\u59CB\u65E5", trigger: "change" }],
  validationEnd: [{ required: true, message: "\u8BF7\u9009\u62E9 VALIDATION \u7ED3\u675F\u65E5", trigger: "change" }],
  holdoutStart: [{ required: true, message: "\u8BF7\u9009\u62E9 HOLDOUT \u8D77\u59CB\u65E5", trigger: "change" }],
  holdoutEnd: [{ required: true, message: "\u8BF7\u9009\u62E9 HOLDOUT \u7ED3\u675F\u65E5", trigger: "change" }]
};
function progressPercent(value) {
  const numeric = Number(value) || 0;
  return Math.max(0, Math.min(100, Math.round(numeric <= 1 ? numeric * 100 : numeric)));
}
function eventType(level) {
  return String(level).toUpperCase() === "ERROR" ? "danger" : String(level).toUpperCase() === "WARNING" ? "warning" : "info";
}
async function loadRuns() {
  loading.value = true;
  error.value = "";
  try {
    const page = await clxBacktestApi.listRuns({ status: statusFilter.value || void 0, pageSize: 100 });
    runs.value = page.items;
    if (!runs.value.some((run) => run.runId === selectedRunId.value)) selectedRunId.value = runs.value[0]?.runId ?? null;
  } catch (reason) {
    error.value = describeApiError(reason);
  } finally {
    loading.value = false;
  }
}
function selectRun(run) {
  selectedRunId.value = run.runId;
}
function showConfig(run) {
  configRun.value = run;
  configVisible.value = true;
}
function openCreate() {
  Object.assign(form, emptyForm());
  createVisible.value = true;
}
async function createRun() {
  try {
    await formRef.value?.validate();
  } catch {
    return;
  }
  const dates = [form.trainStart, form.trainEnd, form.validationStart, form.validationEnd, form.holdoutStart, form.holdoutEnd];
  if (dates.some((value, index) => index && String(dates[index - 1]) >= String(value))) {
    message.error("TRAIN\u3001VALIDATION\u3001HOLDOUT \u65E5\u671F\u5FC5\u987B\u4E25\u683C\u9012\u589E\u4E14\u4E0D\u91CD\u53E0");
    return;
  }
  creating.value = true;
  try {
    const run = await clxBacktestApi.createRun({
      name: form.name,
      config: {
        snapshot_id: form.snapshotId,
        model_ids: Array.from({ length: 18 }, (_, index) => `S${String(index).padStart(4, "0")}`),
        wave_opt: 1560,
        stretch_opt: 0,
        ext_opt: 0,
        trend_opt: 0,
        train: { start: form.trainStart, end: form.trainEnd },
        validation: { start: form.validationStart, end: form.validationEnd },
        holdout: { start: form.holdoutStart, end: form.holdoutEnd },
        horizons: form.horizons.map(Number).filter((value) => Number.isFinite(value) && value > 0),
        initial_cash: form.initialCash,
        max_positions: form.maxPositions,
        combination_dsl: form.combinationDsl || void 0,
        signal_price_domain: "QFQ_OHLC_RAW_VOLUME",
        execution_price_domain: "RAW",
        execution_timing: "T1_OPEN"
      }
    });
    createVisible.value = false;
    message.success("\u5B9E\u9A8C\u8349\u7A3F\u5DF2\u521B\u5EFA");
    await loadRuns();
    selectedRunId.value = run.runId;
  } catch (reason) {
    error.value = describeApiError(reason);
  } finally {
    creating.value = false;
  }
}
async function withAction(run, action, fn) {
  actionRunId.value = run.runId;
  actionName.value = action;
  try {
    await fn();
    await loadRuns();
  } catch (reason) {
    error.value = describeApiError(reason);
  } finally {
    actionRunId.value = "";
    actionName.value = "";
  }
}
async function cloneRun(run) {
  await withAction(run, "clone", async () => {
    const cloned = await clxBacktestApi.cloneRun(run.runId, `${run.name} \xB7 \u514B\u9686`);
    message.success("\u5DF2\u514B\u9686\u4E3A\u72EC\u7ACB\u8349\u7A3F");
    selectedRunId.value = cloned.runId;
  });
}
function confirmStart(run) {
  ElMessageBox.confirm(
    `\u542F\u52A8\u201C${run.name}\u201D\u540E\uFF0C\u914D\u7F6E SHA \u4E0E\u6570\u636E manifest \u5C06\u6210\u4E3A\u53EA\u8BFB\u7814\u7A76\u4E8B\u5B9E\u3002`,
    "\u542F\u52A8\u5E76\u56FA\u5316\u914D\u7F6E\uFF1F",
    { confirmButtonText: "\u786E\u8BA4\u542F\u52A8", cancelButtonText: "\u8FD4\u56DE\u68C0\u67E5", type: "warning" }
  ).then(() => withAction(run, "start", async () => {
    await clxBacktestApi.startRun(run.runId);
    message.success("\u4EFB\u52A1\u5DF2\u8FDB\u5165 worker \u961F\u5217");
  })).catch(() => {
  });
}
function confirmCancel(run) {
  ElMessageBox.confirm(
    "\u5DF2\u843D\u76D8\u7684\u9636\u6BB5 artifact \u4E0E\u4E8B\u4EF6\u4F1A\u4FDD\u7559\uFF0Cworker \u5C06\u5728\u68C0\u67E5\u70B9\u5B89\u5168\u505C\u6B62\u3002",
    "\u8BF7\u6C42\u53D6\u6D88\u5B9E\u9A8C\uFF1F",
    { confirmButtonText: "\u786E\u8BA4\u53D6\u6D88", cancelButtonText: "\u7EE7\u7EED\u8FD0\u884C", type: "warning" }
  ).then(() => withAction(run, "cancel", async () => {
    await clxBacktestApi.cancelRun(run.runId);
    message.warning("\u5DF2\u63D0\u4EA4\u53D6\u6D88\u8BF7\u6C42");
  })).catch(() => {
  });
}
async function loadProgress() {
  const runId = selectedRunId.value;
  if (!runId) {
    progress.value = null;
    return;
  }
  const [progressResult, runResult] = await Promise.allSettled([
    clxBacktestApi.getProgress(runId),
    clxBacktestApi.getRun(runId)
  ]);
  if (selectedRunId.value !== runId) return;
  if (progressResult.status === "fulfilled") {
    progress.value = progressResult.value;
  } else {
    const reason = progressResult.reason;
    if (!["HTTP_404", "NOT_FOUND"].includes(reason?.code)) error.value = describeApiError(reason);
  }
  if (runResult.status === "fulfilled") {
    const index = runs.value.findIndex((run) => run.runId === runId);
    if (index >= 0) runs.value[index] = runResult.value;
  }
}
function stopProgressWatch() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
  eventSource?.close();
  eventSource = null;
  streamConnected.value = false;
}
function startProgressWatch() {
  stopProgressWatch();
  loadProgress();
  if (!selectedRun.value || !["QUEUED", "RUNNING", "CANCEL_REQUESTED"].includes(selectedRun.value.status)) return;
  pollTimer = setInterval(loadProgress, 5e3);
  if (typeof EventSource !== "undefined") {
    eventSource = new EventSource(clxBacktestApi.progressStreamUrl(selectedRun.value.runId));
    eventSource.onopen = () => {
      streamConnected.value = true;
    };
    eventSource.onmessage = () => loadProgress();
    eventSource.addEventListener("progress", () => loadProgress());
    eventSource.onerror = () => {
      streamConnected.value = false;
    };
  }
}
watch(selectedRunId, startProgressWatch);
watch(() => selectedRun.value?.status, startProgressWatch);
onMounted(loadRuns);
onBeforeUnmount(stopProgressWatch);
</script>

<style scoped>
.clx-experiments { display: flex; flex-direction: column; gap: 14px; }
.clx-experiments__actions { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.clx-experiments__actions h2 { margin: 3px 0; font-size: 17px; }
.clx-experiments__actions p { color: var(--fq-text-muted); font-size: 12px; margin: 0; }
.clx-section-kicker { color: var(--fq-text-muted); font-size: 10px; letter-spacing: .09em; }
.clx-experiments__layout { display: grid; grid-template-columns: minmax(420px, .85fr) minmax(460px, 1.15fr); gap: 14px; align-items: start; }
.clx-card { background: var(--fq-panel-bg); border: 1px solid var(--fq-border-soft); border-radius: 10px; padding: 16px; min-width: 0; }
.clx-card__header, .clx-card__header-actions { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.clx-card__header { margin-bottom: 12px; }.clx-card__header h3 { font-size: 14px; margin: 2px 0 0; }
.clx-run-list { display: flex; flex-direction: column; gap: 7px; max-height: calc(100vh - 300px); overflow: auto; padding-right: 3px; }
.clx-run { padding: 11px 12px; border: 1px solid var(--fq-border-soft); border-radius: 8px; background: var(--fq-panel-bg-muted); cursor: pointer; transition: border-color .15s, background .15s; }
.clx-run:hover { border-color: var(--fq-border-muted); }.clx-run--selected { border-color: var(--fq-status-primary); background: color-mix(in srgb, var(--fq-status-primary) 8%, var(--fq-panel-bg-muted)); }
.clx-run__top, .clx-run__buttons, .clx-run__meta { display: flex; align-items: center; gap: 8px; }.clx-run__top { justify-content: space-between; }
.clx-run__identity { display: flex; flex-direction: column; gap: 3px; min-width: 0; }.clx-run__identity strong { font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.clx-run__identity code { color: var(--fq-text-muted); font-size: 9px; }
.clx-run__meta { flex-wrap: wrap; color: var(--fq-text-muted); font-size: 9px; margin: 8px 0; }.clx-run__meta span + span::before { content: '·'; margin-right: 8px; }
.clx-run__buttons { justify-content: flex-end; flex-wrap: wrap; border-top: 1px solid var(--fq-border-soft); padding-top: 7px; }
.clx-progress__hero { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 9px 14px; padding: 14px; border-radius: 8px; background: var(--fq-panel-bg-muted); }
.clx-progress__hero :deep(.el-progress) { grid-column: span 2; }.clx-progress__stage { display: flex; flex-direction: column; gap: 3px; }.clx-progress__stage strong { font-size: 12px; }.clx-progress__stage span, .clx-progress__counts { color: var(--fq-text-muted); font-size: 10px; }
.clx-progress__stream-state { color: var(--fq-text-muted); font-size: 10px; margin: 12px 0; }.clx-live-dot { display: inline-block; width: 7px; height: 7px; background: var(--fq-status-success); border-radius: 50%; margin-right: 5px; box-shadow: 0 0 0 4px rgba(148,226,213,.08); }.clx-live-dot--off { background: var(--fq-status-warning); box-shadow: none; }
.clx-progress__timeline { max-height: calc(100vh - 455px); overflow: auto; padding: 6px 8px 0; }.clx-event-message { color: var(--fq-text-muted); font-size: 11px; }.clx-event-percent { color: var(--fq-status-primary); font-size: 10px; margin-top: 3px; }
.clx-form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 14px; }.clx-form-wide { grid-column: span 2; }
.clx-fixed-contract { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; overflow: hidden; border: 1px solid var(--fq-border-soft); border-radius: 8px; background: var(--fq-border-soft); }.clx-fixed-contract div { display: flex; flex-direction: column; gap: 4px; padding: 10px; background: var(--fq-panel-bg-muted); }.clx-fixed-contract span { color: var(--fq-text-muted); font-size: 10px; }.clx-fixed-contract b { font-size: 11px; }
.clx-modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
@media (max-width: 1100px) { .clx-experiments__layout { grid-template-columns: 1fr; } .clx-run-list, .clx-progress__timeline { max-height: none; } }
@media (max-width: 640px) { .clx-experiments__actions { flex-direction: column; }.clx-experiments__actions .el-button { width: 100%; }.clx-form-grid { grid-template-columns: 1fr; }.clx-form-wide { grid-column: span 1; }.clx-fixed-contract { grid-template-columns: 1fr; } }
</style>
