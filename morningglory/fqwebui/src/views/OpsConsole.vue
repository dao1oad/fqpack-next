<template>
  <WorkbenchPage class="ops-page">
    <MyHeader />
    <div class="workbench-body workbench-body--scroll ops-shell">
      <!-- ① 全局状态条 -->
      <WorkbenchToolbar class="ops-section ops-statusbar">
        <div class="ops-statusbar-row">
          <StatusChip :variant="overallVariant" class="ops-badge ops-badge--overall">
            <strong>{{ overallHealth.label }}</strong>
            <span v-if="overallHealth.tone === 'error' && issues.last_issue_ts" class="ops-badge-since">
              自 {{ formatTimestamp(issues.last_issue_ts) }}
            </span>
          </StatusChip>
          <StatusChip :variant="sessionVariant">
            交易时段 <strong>{{ sessionLabel }}</strong>
          </StatusChip>
          <StatusChip variant="warning">
            关键告警 <strong>{{ alertCount }}</strong>
          </StatusChip>
          <StatusChip variant="muted">
            最后刷新 <strong>{{ lastRefreshLabel }}</strong>
          </StatusChip>
          <span class="ops-statusbar-spacer" />
          <el-radio-group v-model="refreshMode" size="small">
            <el-radio-button value="60">60s</el-radio-button>
            <el-radio-button value="15">15s</el-radio-button>
            <el-radio-button value="manual">手动</el-radio-button>
          </el-radio-group>
          <el-switch
            v-model="autoRefresh"
            inline-prompt
            active-text="自动"
            inactive-text="手动"
          />
          <el-button :loading="loading" @click="refresh">刷新</el-button>
        </div>
        <el-alert
          v-if="pageError"
          class="ops-alert"
          type="error"
          :title="pageError"
          show-icon
          :closable="false"
        />
        <div v-if="degradedCount > 0" class="ops-banner">
          <strong>{{ degradedCount }}/{{ kpiCards.length }} 数据源异常</strong>
          <span>异常卡片已独立降级，不阻塞其他卡片实时刷新。</span>
        </div>
      </WorkbenchToolbar>

      <!-- ② KPI 卡片行（8 张，4×2，可折叠） -->
      <WorkbenchPanel class="ops-section ops-kpi-section" tag="section">
        <div class="ops-section-head">
          <div class="ops-section-title">
            <h2>运行 KPI</h2>
            <p>8 张只读卡片；数据源故障时卡片显式降级并说明原因。</p>
          </div>
          <el-button text @click="kpiCollapsed = !kpiCollapsed">
            {{ kpiCollapsed ? '展开' : '折叠' }}
          </el-button>
        </div>
        <el-collapse-transition>
          <div v-show="!kpiCollapsed" class="ops-kpi-grid">
            <div
              v-for="card in kpiCards"
              :key="card.key"
              class="ops-kpi-card"
              :class="`ops-tone--${card.tone}`"
            >
              <div class="ops-kpi-card__head">
                <span class="ops-kpi-card__label" :title="card.label">{{ card.label }}</span>
                <StatusChip :variant="deriveToneVariant(card.tone)">{{ card.status }}</StatusChip>
              </div>
              <div
                class="ops-kpi-card__summary"
                :class="{ 'ops-kpi-card__summary--number': card.tone === 'error' }"
                :title="card.summary"
              >
                {{ card.summary }}
              </div>
              <div class="ops-kpi-card__detail" :title="card.detail">
                {{ card.detail || '—' }}
              </div>
            </div>
          </div>
        </el-collapse-transition>
      </WorkbenchPanel>

      <!-- ③ 分层运行状态区（3 栏；宿主机桥为 S3 占位） -->
      <WorkbenchPanel class="ops-section" tag="section">
        <div class="ops-section-head">
          <div class="ops-section-title">
            <h2>分层运行状态</h2>
            <p>宿主机进程与 Docker 容器表待宿主机只读桥（S3）接入；依赖服务本轮已实现容器内探针。</p>
          </div>
        </div>
        <div class="ops-layer-grid">
          <div class="ops-layer-card">
            <div class="ops-layer-card__head">
              <strong>宿主机进程</strong>
              <StatusChip variant="skipped">S3 占位</StatusChip>
            </div>
            <p class="ops-placeholder-note">未接入宿主机桥</p>
          </div>
          <div class="ops-layer-card">
            <div class="ops-layer-card__head">
              <strong>Docker 容器</strong>
              <StatusChip variant="skipped">S3 占位</StatusChip>
            </div>
            <p class="ops-placeholder-note">未接入宿主机桥</p>
          </div>
          <div class="ops-layer-card">
            <div class="ops-layer-card__head">
              <strong>依赖服务</strong>
            </div>
            <div class="ops-dep-list">
              <div v-for="dep in dependencyRows" :key="dep.key" class="ops-dep-row">
                <span class="ops-dep-name">{{ dep.label }}</span>
                <StatusChip :variant="dep.ok ? 'success' : 'danger'">
                  {{ dep.ok ? '正常' : '异常' }}
                </StatusChip>
                <span class="ops-dep-latency" :title="dep.error || ''">{{ dep.latencyLabel }}</span>
              </div>
            </div>
          </div>
        </div>
      </WorkbenchPanel>

      <!-- ④ 数据链健康区（S2） -->
      <WorkbenchPanel class="ops-section" tag="section">
        <div class="ops-section-head">
          <div class="ops-section-title">
            <h2>数据链健康</h2>
            <p>producer → consumer → K 线 API；任一段异常标红并带日志入口。</p>
          </div>
          <el-button :loading="klineLoading" size="small" @click="loadKline">
            刷新探针
          </el-button>
        </div>
        <el-alert
          v-if="klineError"
          class="ops-alert"
          type="error"
          :title="klineError"
          show-icon
          :closable="false"
        />
        <div v-else class="ops-pipeline">
          <template v-for="(segment, index) in segmentRows" :key="segment.key">
            <div
              class="ops-pipeline-node"
              :class="`ops-tone--${segment.tone}`"
            >
              <div class="ops-pipeline-node__head">
                <strong>{{ segment.label }}</strong>
                <StatusChip :variant="deriveToneVariant(segment.tone)">
                  {{ segment.summary }}
                </StatusChip>
              </div>
              <div class="ops-pipeline-node__detail" :title="segment.detail">
                {{ segment.detail || '—' }}
              </div>
              <div class="ops-pipeline-node__meta">
                <el-button
                  v-if="segment.log_component"
                  size="small"
                  text
                  @click="openRuntimeLog(segment.log_component)"
                >
                  日志
                </el-button>
                <span
                  v-if="segment.last_issue_ts"
                  class="ops-pipeline-node__issue"
                  :title="segment.last_issue_ts"
                >
                  最近异常 {{ formatTimestamp(segment.last_issue_ts) }}
                </span>
              </div>
            </div>
            <div v-if="index < segmentRows.length - 1" class="ops-pipeline-arrow">→</div>
          </template>
        </div>
      </WorkbenchPanel>

      <!-- ⑤ 最近异常（S4 盘后管线占位；异常列表来自 health/summary 聚合） -->
      <WorkbenchPanel class="ops-section" tag="section">
        <div class="ops-section-head">
          <div class="ops-section-title">
            <h2>最近异常</h2>
            <p>异常组件聚合（health/summary），点击跳运行观测带组件过滤；盘后管线联动为 S4。</p>
          </div>
          <el-date-picker
            v-model="issueRange"
            type="datetimerange"
            size="small"
            value-format="YYYY-MM-DDTHH:mm:ssZ"
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            :clearable="true"
          />
        </div>
        <div class="ops-issue-list">
          <button
            v-for="row in issueRows"
            :key="row.component"
            type="button"
            class="ops-issue-row"
            @click="openRuntimeLog(row.component)"
          >
            <strong :title="row.component">{{ row.component }}</strong>
            <StatusChip :variant="row.status === 'error' || row.status === 'failed' ? 'danger' : 'warning'">
              {{ row.status }}
            </StatusChip>
            <span>异常链路 <strong>{{ row.issue_trace_count }}</strong></span>
            <span>异常节点 <strong>{{ row.issue_step_count }}</strong></span>
            <span class="ops-issue-row__time">{{ formatTimestamp(row.last_issue_ts) }}</span>
          </button>
          <div v-if="!issueRows.length" class="ops-empty-panel">
            <strong>暂无异常组件</strong>
          </div>
        </div>
      </WorkbenchPanel>
    </div>
  </WorkbenchPage>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { opsApi } from '../api/opsApi'
import StatusChip from '../components/workbench/StatusChip.vue'
import WorkbenchPage from '../components/workbench/WorkbenchPage.vue'
import WorkbenchPanel from '../components/workbench/WorkbenchPanel.vue'
import WorkbenchToolbar from '../components/workbench/WorkbenchToolbar.vue'
import MyHeader from './MyHeader.vue'
import {
  buildIssueRows,
  buildKpiCards,
  buildRuntimeLogLink,
  buildSegments,
  countDegradedKpis,
  countIssueEvents,
  deriveOverallHealth,
  deriveSessionLabel,
  deriveToneVariant,
  formatTimestamp
} from './opsConsole.mjs'

const router = useRouter()

const overview = ref(null)
const kline = ref(null)
const loading = ref(false)
const klineLoading = ref(false)
const pageError = ref('')
const klineError = ref('')
const kpiCollapsed = ref(false)
const autoRefresh = ref(true)
const refreshMode = ref('60')
const lastRefreshAt = ref(null)
const issueRange = ref(null)

let timer = null

const overallHealth = computed(() => deriveOverallHealth(overview.value?.kpis))
const overallVariant = computed(() => deriveToneVariant(overallHealth.value.tone))
const kpiCards = computed(() => buildKpiCards(overview.value?.kpis))
const degradedCount = computed(() => countDegradedKpis(overview.value?.kpis))
const issues = computed(() => overview.value?.issues || {})
const alertCount = computed(() => (
  (issues.value.component_issue_count || 0) + countIssueEvents(issues.value)
))
const sessionLabel = computed(() => deriveSessionLabel(overview.value?.trade_session))
const sessionVariant = computed(() => {
  const session = overview.value?.trade_session?.session
  if (session === 'unknown' || overview.value?.trade_session?.calendar_status === 'unavailable') {
    return 'muted'
  }
  if (session === 'non_trade_day' || session === 'post_close') {
    return 'info'
  }
  return 'success'
})
const lastRefreshLabel = computed(() => (
  lastRefreshAt.value ? formatTimestamp(lastRefreshAt.value) : '-'
))

const formatLatency = (dep) => {
  if (!dep) return '-'
  if (!dep.ok) return dep.error || '不可用'
  if (dep.latency_ms === null || dep.latency_ms === undefined) return '-'
  return `${dep.latency_ms}ms`
}

const dependencyRows = computed(() => {
  const deps = overview.value?.dependencies || {}
  return [
    { key: 'mongo', label: 'Mongo', ok: deps.mongo?.ok, latencyLabel: formatLatency(deps.mongo), error: deps.mongo?.error },
    { key: 'redis', label: 'Redis', ok: deps.redis?.ok, latencyLabel: formatLatency(deps.redis), error: deps.redis?.error },
    { key: 'clickhouse', label: 'ClickHouse', ok: deps.clickhouse?.ok, latencyLabel: formatLatency(deps.clickhouse), error: deps.clickhouse?.error },
    { key: 'tdxhq', label: 'TDXHQ', ok: deps.tdxhq?.ok, latencyLabel: formatLatency(deps.tdxhq), error: deps.tdxhq?.error }
  ]
})

const segmentRows = computed(() => buildSegments(kline.value?.segments))

const normalizeIssueRange = (value) => {
  if (!Array.isArray(value) || value.length !== 2) return null
  return { start: value[0], end: value[1] }
}

const issueRows = computed(() => (
  buildIssueRows(issues.value, normalizeIssueRange(issueRange.value))
))

const loadOverview = async () => {
  loading.value = true
  pageError.value = ''
  try {
    overview.value = await opsApi.fetchOpsOverview()
    lastRefreshAt.value = new Date()
  } catch (error) {
    pageError.value = `运维总览数据源不可用（${error?.message || error}）`
  } finally {
    loading.value = false
  }
}

const loadKline = async () => {
  klineLoading.value = true
  klineError.value = ''
  try {
    kline.value = await opsApi.fetchKlineHealth()
  } catch (error) {
    kline.value = null
    klineError.value = `数据链健康数据源不可用（${error?.message || error}）`
  } finally {
    klineLoading.value = false
  }
}

const refresh = () => {
  loadOverview()
  loadKline()
}

const startPolling = () => {
  stopPolling()
  if (!autoRefresh.value || refreshMode.value === 'manual') return
  const intervalMs = refreshMode.value === '15' ? 15000 : 60000
  timer = window.setInterval(() => {
    refresh()
  }, intervalMs)
}

const stopPolling = () => {
  if (timer) {
    window.clearInterval(timer)
    timer = null
  }
}

const openRuntimeLog = (component) => {
  router.push(buildRuntimeLogLink(component))
}

watch([autoRefresh, refreshMode], startPolling)

onMounted(() => {
  refresh()
  startPolling()
})

onBeforeUnmount(stopPolling)
</script>

<style scoped>
.ops-shell {
  gap: var(--fq-space-3);
}

.ops-section {
  flex: none;
}

.ops-statusbar-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--fq-space-2) var(--fq-space-3);
}

.ops-statusbar-spacer {
  flex: 1 1 auto;
}

.ops-badge--overall strong {
  margin-right: var(--fq-space-1);
}

.ops-badge-since {
  opacity: 0.85;
  font-size: var(--fq-font-dense);
}

.ops-alert {
  width: 100%;
}

.ops-banner {
  display: flex;
  align-items: center;
  gap: var(--fq-space-2);
  width: 100%;
  padding: var(--fq-space-2) var(--fq-space-3);
  border: 1px solid var(--fq-chip-border-warning);
  border-radius: var(--fq-radius-sm);
  background: var(--fq-chip-bg-warning);
  color: var(--fq-status-warning);
  font-size: var(--fq-font-meta);
}

.ops-section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--fq-space-3);
  margin-bottom: var(--fq-space-3);
}

.ops-section-title h2 {
  margin: 0;
  font-size: var(--fq-font-panel-title);
  color: var(--fq-text-primary);
}

.ops-section-title p {
  margin: var(--fq-space-1) 0 0;
  font-size: var(--fq-font-meta);
  color: var(--fq-text-muted);
}

.ops-kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--fq-space-3);
}

.ops-kpi-card {
  display: flex;
  flex-direction: column;
  gap: var(--fq-space-1);
  padding: var(--fq-space-3);
  border: 1px solid var(--fq-border-soft);
  border-radius: var(--fq-radius-md);
  background: var(--fq-panel-bg-muted);
}

.ops-kpi-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--fq-space-2);
}

.ops-kpi-card__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fq-font-meta);
  color: var(--fq-text-secondary);
}

.ops-kpi-card__summary {
  font-size: 18px;
  font-weight: 600;
  color: var(--fq-text-primary);
}

.ops-kpi-card__summary--number {
  color: var(--fq-status-danger);
}

.ops-kpi-card__detail {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fq-font-dense);
  color: var(--fq-text-muted);
}

.ops-tone--error {
  border-color: var(--fq-chip-border-danger);
  background: var(--fq-chip-bg-danger);
}

.ops-tone--warn,
.ops-tone--degraded {
  border-color: var(--fq-chip-border-warning);
  background: var(--fq-chip-bg-warning);
}

.ops-layer-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--fq-space-3);
}

.ops-layer-card {
  padding: var(--fq-space-3);
  border: 1px solid var(--fq-border-soft);
  border-radius: var(--fq-radius-md);
  background: var(--fq-panel-bg-muted);
}

.ops-layer-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--fq-space-2);
  margin-bottom: var(--fq-space-2);
}

.ops-placeholder-note {
  margin: 0;
  font-size: var(--fq-font-meta);
  color: var(--fq-text-muted);
}

.ops-dep-list {
  display: flex;
  flex-direction: column;
  gap: var(--fq-space-2);
}

.ops-dep-row {
  display: flex;
  align-items: center;
  gap: var(--fq-space-2);
}

.ops-dep-name {
  flex: 1 1 auto;
  font-size: var(--fq-font-meta);
  color: var(--fq-text-secondary);
}

.ops-dep-latency {
  font-size: var(--fq-font-dense);
  color: var(--fq-text-muted);
}

.ops-pipeline {
  display: flex;
  align-items: stretch;
  gap: var(--fq-space-3);
  overflow-x: auto;
}

.ops-pipeline-node {
  flex: 1 1 0;
  min-width: 220px;
  display: flex;
  flex-direction: column;
  gap: var(--fq-space-2);
  padding: var(--fq-space-3);
  border: 1px solid var(--fq-border-soft);
  border-radius: var(--fq-radius-md);
  background: var(--fq-panel-bg-muted);
}

.ops-pipeline-node__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--fq-space-2);
}

.ops-pipeline-node__detail {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fq-font-dense);
  color: var(--fq-text-secondary);
}

.ops-pipeline-node__meta {
  display: flex;
  align-items: center;
  gap: var(--fq-space-2);
  min-height: 24px;
}

.ops-pipeline-node__issue {
  font-size: var(--fq-font-dense);
  color: var(--fq-status-danger);
}

.ops-pipeline-arrow {
  align-self: center;
  color: var(--fq-text-muted);
  font-size: 20px;
  flex: none;
}

.ops-issue-list {
  display: flex;
  flex-direction: column;
  gap: var(--fq-space-2);
}

.ops-issue-row {
  display: flex;
  align-items: center;
  gap: var(--fq-space-3);
  width: 100%;
  padding: var(--fq-space-2) var(--fq-space-3);
  border: 1px solid var(--fq-border-soft);
  border-radius: var(--fq-radius-sm);
  background: var(--fq-panel-bg);
  color: var(--fq-text-primary);
  cursor: pointer;
  text-align: left;
}

.ops-issue-row:hover {
  border-color: var(--fq-border-primary);
  background: var(--fq-chip-bg-primary);
}

.ops-issue-row strong {
  min-width: 140px;
}

.ops-issue-row__time {
  margin-left: auto;
  font-size: var(--fq-font-dense);
  color: var(--fq-text-muted);
}

.ops-empty-panel {
  padding: var(--fq-space-4);
  text-align: center;
  color: var(--fq-text-muted);
  border: 1px dashed var(--fq-border-muted);
  border-radius: var(--fq-radius-md);
}

@media (max-width: 1280px) {
  .ops-kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .ops-layer-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .ops-kpi-grid {
    grid-template-columns: 1fr;
  }

  .ops-pipeline {
    flex-direction: column;
  }

  .ops-pipeline-arrow {
    transform: rotate(90deg);
  }
}
</style>
