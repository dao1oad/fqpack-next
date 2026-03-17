<template>
  <div class="workbench-page daily-screening-page">
    <MyHeader />

    <div
      class="workbench-body daily-screening-body"
      v-loading="loadingSchema || loadingPrePools"
    >
      <section class="workbench-toolbar">
        <div class="workbench-toolbar__header">
          <div class="workbench-title-group">
            <div class="workbench-page-title">每日选股</div>
            <div class="workbench-page-meta">
              <span>统一发起 CLXS / chanlun 每日扫描，页面内直接看参数、SSE 进度、命中结果和落库结果。</span>
              <span>/</span>
              <span>当前模型 {{ currentModelLabel }}</span>
              <span>/</span>
              <span>来源 remark <span class="workbench-code">{{ currentRemarkSummary }}</span></span>
            </div>
          </div>

          <div class="workbench-toolbar__actions">
            <el-button @click="loadSchema">刷新 schema</el-button>
            <el-button @click="refreshPrePools">刷新预选池</el-button>
          </div>
        </div>

        <div class="workbench-summary-row">
          <span class="workbench-summary-chip" :class="statusChipClass">
            状态 <strong>{{ runSnapshot?.status || 'idle' }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--muted">
            运行 ID <strong>{{ activeRunId || '-' }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--muted">
            processed <strong>{{ runSnapshot?.progress?.processed ?? 0 }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--success">
            accepted <strong>{{ runSnapshot?.progress?.accepted ?? acceptedRows.length }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--warning">
            persisted <strong>{{ runSnapshot?.progress?.persisted ?? 0 }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--muted">
            SSE <strong>{{ streamState }}</strong>
          </span>
        </div>
      </section>

      <el-alert
        v-if="pageError"
        class="workbench-alert"
        type="error"
        :title="pageError"
        :closable="false"
        show-icon
      />

      <div class="daily-screening-grid">
        <section class="workbench-panel daily-config-panel">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">模型配置</div>
              <p class="workbench-panel__desc">参数来自后端 schema，前端只做动态渲染和联动显示。</p>
            </div>
          </div>

          <div class="daily-model-switch">
            <el-radio-group v-model="selectedModel" size="small">
              <el-radio-button
                v-for="model in models"
                :key="model.id"
                :label="model.id"
              >
                {{ model.label || model.id }}
              </el-radio-button>
            </el-radio-group>
          </div>

          <el-form label-position="top" size="small" class="daily-form-grid">
            <el-form-item
              v-for="field in visibleFields"
              :key="field.name"
              :label="resolveFieldLabel(field)"
            >
              <el-switch
                v-if="field.type === 'boolean'"
                v-model="currentForm[field.name]"
                inline-prompt
                active-text="开"
                inactive-text="关"
                :disabled="field.readonly"
              />
              <el-select
                v-else-if="field.type === 'select'"
                v-model="currentForm[field.name]"
                :disabled="field.readonly"
                filterable
                clearable
                :multiple="Boolean(field.multiple)"
                :collapse-tags="Boolean(field.multiple)"
                :collapse-tags-tooltip="Boolean(field.multiple)"
                class="daily-field-control"
              >
                <el-option
                  v-for="option in field.options || []"
                  :key="`${field.name}-${option.value}`"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
              <el-input-number
                v-else-if="field.type === 'number'"
                v-model="currentForm[field.name]"
                controls-position="right"
                :min="0"
                class="daily-field-control"
                :disabled="field.readonly"
              />
              <el-input
                v-else
                v-model="currentForm[field.name]"
                :readonly="field.readonly"
                :disabled="field.readonly"
                clearable
              />
            </el-form-item>
          </el-form>

          <article class="workbench-block workbench-block--muted daily-preview-block">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">等效 CLI 预览</div>
                <p class="workbench-panel__desc">主命令尽量贴近现有 CLI，页面扩展参数单独标注。</p>
              </div>
            </div>
            <pre class="daily-cli-command">{{ cliPreview.command }}</pre>
            <div v-if="cliPreview.extensions.length" class="daily-extension-list">
              <span
                v-for="item in cliPreview.extensions"
                :key="item"
                class="workbench-summary-chip workbench-summary-chip--muted"
              >
                {{ item }}
              </span>
            </div>
          </article>

          <article class="workbench-block daily-guide-block">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">规则说明</div>
                <p class="workbench-panel__desc">直接展示这两条选股链路在当前系统里的真实过滤与落库边界。</p>
              </div>
            </div>
            <ul class="daily-guide-list">
              <li v-for="line in guideLines" :key="line">{{ line }}</li>
            </ul>
          </article>

          <div class="daily-config-actions">
            <el-button
              type="primary"
              :loading="startingRun"
              @click="startRun"
            >
              开始扫描
            </el-button>
            <el-button @click="hydrateCurrentRun">刷新本次状态</el-button>
          </div>
        </section>

        <section class="workbench-panel daily-stream-panel">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">SSE 事件流</div>
              <p class="workbench-panel__desc">实时推送 started / progress / accepted / persisted / summary / completed。</p>
            </div>
            <div class="workbench-panel__meta">
              <span>{{ logEvents.length }} 条</span>
            </div>
          </div>

          <div class="daily-stream-list">
            <article
              v-for="event in orderedLogEvents"
              :key="`${event.seq}-${event.event}`"
              class="daily-stream-item"
              :class="`daily-stream-item--${event.tone}`"
            >
              <div class="daily-stream-item__head">
                <span class="daily-stream-item__event">{{ event.event }}</span>
                <span class="workbench-code">#{{ event.seq }}</span>
                <span>{{ event.tsLabel }}</span>
              </div>
              <div class="daily-stream-item__summary">{{ event.summary }}</div>
            </article>
            <div v-if="orderedLogEvents.length === 0" class="daily-empty">
              暂无事件，点击“开始扫描”后会实时显示。
            </div>
          </div>
        </section>

        <aside class="daily-side-stack">
          <section class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">本次结果</div>
                <p class="workbench-panel__desc">accepted 事件会直接出现在这里，帮助理解哪些结果真的进入最终集合。</p>
              </div>
              <div class="workbench-panel__meta">
                <span>{{ filteredAcceptedRows.length }} 条</span>
              </div>
            </div>

            <div class="daily-filter-bar">
              <el-radio-group v-model="resultBranchFilter" size="small">
                <el-radio-button label="all">全部分支</el-radio-button>
                <el-radio-button
                  v-for="item in filterOptions.branches"
                  :key="item.key"
                  :label="item.key"
                >
                  {{ item.label }} · {{ item.count }}
                </el-radio-button>
              </el-radio-group>
              <el-radio-group v-model="resultModelFilter" size="small">
                <el-radio-button label="all">全部模型</el-radio-button>
                <el-radio-button
                  v-for="item in filterOptions.models"
                  :key="item.key"
                  :label="item.key"
                >
                  {{ item.label }} · {{ item.count }}
                </el-radio-button>
              </el-radio-group>
            </div>

            <el-table
              :data="filteredAcceptedRows"
              size="small"
              border
              height="280"
            >
              <el-table-column prop="branch" label="分支" width="90" />
              <el-table-column prop="model_label" label="模型" min-width="140" show-overflow-tooltip />
              <el-table-column prop="code" label="代码" width="88" />
              <el-table-column prop="name" label="名称" min-width="100" show-overflow-tooltip />
              <el-table-column prop="signal_type" label="信号" min-width="140" show-overflow-tooltip />
              <el-table-column prop="period" label="周期" width="76" />
              <el-table-column label="触发时间" min-width="150">
                <template #default="{ row }">
                  {{ formatDateTime(row.fire_time) }}
                </template>
              </el-table-column>
              <el-table-column label="操作" width="88" fixed="right">
                <template #default="{ row }">
                  <el-button type="primary" text @click="openKline(row)">K 线</el-button>
                </template>
              </el-table-column>
            </el-table>
          </section>

          <section class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">已落库预选池</div>
                <p class="workbench-panel__desc">可以切换看本次 run 或当前来源 remark；stock_pre_pools 仍是共享集合。</p>
              </div>
              <div class="workbench-panel__meta">
                <el-radio-group v-model="prePoolScope" size="small" @change="refreshPrePools">
                  <el-radio-button label="run" :disabled="!activeRunId">本次 run</el-radio-button>
                  <el-radio-button label="source">当前来源</el-radio-button>
                </el-radio-group>
              </div>
            </div>

            <el-table
              :data="filteredPrePoolRows"
              size="small"
              border
              height="360"
            >
              <el-table-column prop="branch" label="分支" width="90" />
              <el-table-column prop="model_label" label="模型" min-width="140" show-overflow-tooltip />
              <el-table-column prop="code" label="代码" width="88" />
              <el-table-column prop="name" label="名称" min-width="100" show-overflow-tooltip />
              <el-table-column prop="category" label="分类" min-width="120" show-overflow-tooltip />
              <el-table-column prop="remark" label="来源" min-width="160" show-overflow-tooltip />
              <el-table-column prop="period" label="周期" width="76" />
              <el-table-column label="止损" width="86">
                <template #default="{ row }">
                  {{ formatNumber(row.stop_loss_price) }}
                </template>
              </el-table-column>
              <el-table-column label="日期" min-width="138">
                <template #default="{ row }">
                  {{ formatDateTime(row.datetime) }}
                </template>
              </el-table-column>
              <el-table-column label="操作" width="132" fixed="right">
                <template #default="{ row }">
                  <div class="daily-row-actions">
                    <el-button type="primary" text @click="openKline(row)">K 线</el-button>
                    <el-button type="success" text @click="addToStockPool(row)">股票池</el-button>
                    <el-button type="danger" text @click="deletePrePoolRow(row)">删除</el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </aside>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import MyHeader from './MyHeader.vue'
import { dailyScreeningApi, createDailyScreeningStream } from '@/api/dailyScreeningApi.js'
import {
  applyDailyScreeningRowFilters,
  buildDailyScreeningCliPreview,
  buildDailyScreeningForms,
  buildDailyScreeningModelFilters,
  buildDailyScreeningSourceQueries,
  getDailyScreeningGuide,
  mergeDailyScreeningRows,
  resolveDailyScreeningFields,
} from './dailyScreeningPage.mjs'

const loadingSchema = ref(false)
const loadingPrePools = ref(false)
const startingRun = ref(false)
const pageError = ref('')
const schema = ref({ models: [], options: {} })
const selectedModel = ref('all')
const forms = reactive({
  all: {},
  clxs: {},
  chanlun: {},
})
const streamState = ref('idle')
const activeRunId = ref('')
const runSnapshot = ref(null)
const acceptedRows = ref([])
const logEvents = ref([])
const prePoolRows = ref([])
const prePoolScope = ref('source')
const resultBranchFilter = ref('all')
const resultModelFilter = ref('all')
let eventSource = null

const models = computed(() => Array.isArray(schema.value?.models) ? schema.value.models : [])
const currentModel = computed(() => models.value.find((model) => model.id === selectedModel.value) || null)
const currentModelLabel = computed(() => currentModel.value?.label || selectedModel.value)
const currentForm = computed(() => forms[selectedModel.value] || {})
const visibleFields = computed(() => resolveDailyScreeningFields(schema.value, selectedModel.value, currentForm.value))
const cliPreview = computed(() => buildDailyScreeningCliPreview(selectedModel.value, currentForm.value))
const guideLines = computed(() => getDailyScreeningGuide(selectedModel.value))
const orderedLogEvents = computed(() => [...logEvents.value].reverse())
const filterOptions = computed(() => buildDailyScreeningModelFilters([
  ...acceptedRows.value,
  ...prePoolRows.value,
], resultBranchFilter.value))
const filteredAcceptedRows = computed(() => applyDailyScreeningRowFilters(
  acceptedRows.value,
  {
    branch: resultBranchFilter.value,
    modelKey: resultModelFilter.value,
  },
))
const filteredPrePoolRows = computed(() => applyDailyScreeningRowFilters(
  prePoolRows.value,
  {
    branch: resultBranchFilter.value,
    modelKey: resultModelFilter.value,
  },
))
const currentRemarkSummary = computed(() => {
  if (selectedModel.value === 'all') {
    return `${currentForm.value?.clxs_remark || 'daily-screening:clxs'} -> ${currentForm.value?.chanlun_remark || 'daily-screening:chanlun'}`
  }
  return currentForm.value?.remark || '-'
})

const statusChipClass = computed(() => {
  const status = String(runSnapshot.value?.status || '').toLowerCase()
  if (status === 'completed') return 'workbench-summary-chip--success'
  if (status === 'failed') return 'workbench-summary-chip--danger'
  if (status === 'running') return 'workbench-summary-chip--warning'
  return 'workbench-summary-chip--muted'
})

watch(filterOptions, (nextValue) => {
  if (resultModelFilter.value === 'all') return
  if (nextValue.models.some((item) => item.key === resultModelFilter.value)) return
  resultModelFilter.value = 'all'
})

const closeStream = () => {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
}

const applyForms = (nextForms = {}) => {
  for (const [modelId, payload] of Object.entries(nextForms)) {
    forms[modelId] = {
      ...(forms[modelId] || {}),
      ...payload,
    }
  }
}

const loadSchema = async () => {
  loadingSchema.value = true
  try {
    const { data } = await dailyScreeningApi.getSchema()
    schema.value = data || { models: [], options: {} }
    applyForms(buildDailyScreeningForms(schema.value))
    if (!models.value.find((model) => model.id === selectedModel.value)) {
      selectedModel.value = models.value[0]?.id || 'all'
    }
    pageError.value = ''
    await refreshPrePools()
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '加载 schema 失败'
  } finally {
    loadingSchema.value = false
  }
}

const hydrateCurrentRun = async () => {
  if (!activeRunId.value) return
  try {
    const { data } = await dailyScreeningApi.getRun(activeRunId.value)
    runSnapshot.value = data?.run || null
    acceptedRows.value = Array.isArray(runSnapshot.value?.results) ? runSnapshot.value.results : []
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '加载运行状态失败'
  }
}

const buildStartPayload = () => ({
  model: selectedModel.value,
  ...currentForm.value,
})

const refreshPrePools = async () => {
  loadingPrePools.value = true
  try {
    if (prePoolScope.value === 'run' && activeRunId.value) {
      const { data } = await dailyScreeningApi.getPrePools({
        limit: 200,
        run_id: activeRunId.value,
      })
      prePoolRows.value = Array.isArray(data?.rows) ? data.rows : []
      return
    }

    const queries = buildDailyScreeningSourceQueries(
      selectedModel.value,
      currentForm.value,
      200,
    )
    const responses = await Promise.all(
      queries.map((params) => dailyScreeningApi.getPrePools(params)),
    )
    prePoolRows.value = mergeDailyScreeningRows(
      ...responses.map((response) => response?.data?.rows),
    )
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '加载预选池失败'
  } finally {
    loadingPrePools.value = false
  }
}

const resolveFieldLabel = (field) => {
  const labels = {
    days: '扫描天数',
    code: '代码',
    wave_opt: 'wave_opt',
    stretch_opt: 'stretch_opt',
    trend_opt: 'trend_opt',
    model_opt: 'model_opt',
    model_opts: 'CLXS 模型',
    clxs_model_opts: 'CLXS 全模型',
    save_pre_pools: '写入 pre_pools',
    output_category: '输出分类',
    remark: '来源备注',
    clxs_remark: 'CLXS 来源',
    chanlun_remark: 'chanlun 来源',
    input_mode: '输入模式',
    period_mode: '周期模式',
    chanlun_period_mode: 'chanlun 周期',
    pre_pool_category: '预选池分类',
    pre_pool_remark: '预选池来源',
    max_concurrent: '最大并发',
    chanlun_max_concurrent: 'chanlun 并发',
    signal_types: '缠论信号',
    chanlun_signal_types: 'chanlun 全信号',
    save_signal: '写入信号',
    save_pools: '写入股票池',
    pool_expire_days: '股票池天数',
  }
  return labels[field.name] || field.name
}

const formatDateTime = (value) => {
  if (!value) return '-'
  const text = String(value)
  if (text.length >= 19) return text.slice(0, 19).replace('T', ' ')
  return text
}

const formatNumber = (value) => {
  if (value === null || value === undefined || value === '') return '-'
  const num = Number(value)
  return Number.isFinite(num) ? num.toFixed(2) : String(value)
}

const eventToneMap = {
  started: 'neutral',
  universe: 'muted',
  progress: 'warning',
  hit_raw: 'muted',
  accepted: 'success',
  persisted: 'success',
  phase_started: 'warning',
  phase_completed: 'neutral',
  summary: 'neutral',
  completed: 'success',
  error: 'danger',
  heartbeat: 'muted',
}

const eventSummary = (eventName, payload = {}) => {
  if (eventName === 'progress') {
    return `${payload.code || '-'} ${payload.processed || 0}/${payload.total || 0} result_count=${payload.result_count || 0}`
  }
  if (eventName === 'accepted') {
    return `${payload.code || '-'} ${payload.signal_type || '-'} ${payload.period || '-'}`
  }
  if (eventName === 'persisted') {
    return `${payload.code || '-'} -> ${payload.category || '-'} / ${payload.remark || '-'}`
  }
  if (eventName === 'phase_started' || eventName === 'phase_completed') {
    return `${payload.branch || '-'} ${payload.label || '-'} accepted=${payload.accepted_count || 0}`
  }
  if (eventName === 'summary') {
    return `accepted=${payload.accepted_count || 0}, persisted=${payload.persisted_count || 0}`
  }
  if (eventName === 'error') {
    return payload.message || payload.error || 'unknown error'
  }
  if (eventName === 'universe') {
    return `mode=${payload.mode || '-'} total=${payload.total || 0}`
  }
  return JSON.stringify(payload)
}

const pushLogEvent = (record = {}) => {
  const data = record.data || {}
  logEvents.value.push({
    seq: record.seq,
    event: record.event,
    tone: eventToneMap[record.event] || 'neutral',
    tsLabel: formatDateTime(record.ts),
    summary: eventSummary(record.event, data),
    data,
  })
}

const handleStreamEvent = async (eventName, rawEvent) => {
  let record
  try {
    record = JSON.parse(rawEvent.data || '{}')
  } catch (error) {
    record = { seq: logEvents.value.length + 1, event: eventName, ts: new Date().toISOString(), data: { error: 'invalid event payload' } }
  }
  pushLogEvent({
    ...record,
    event: eventName,
  })
  const payload = record.data || {}
  if (eventName === 'accepted') {
    acceptedRows.value = [...acceptedRows.value, payload]
  }
  if (eventName === 'error') {
    pageError.value = payload.message || payload.error || '扫描失败'
  }
  if (eventName === 'persisted') {
    await refreshPrePools()
  }
  if (eventName === 'summary' || eventName === 'completed') {
    await hydrateCurrentRun()
    await refreshPrePools()
    if (eventName === 'completed') {
      streamState.value = runSnapshot.value?.status || 'completed'
      closeStream()
    }
  }
}

const connectStream = (runId) => {
  closeStream()
  if (typeof EventSource !== 'function') {
    streamState.value = 'unsupported'
    return
  }
  streamState.value = 'connecting'
  eventSource = createDailyScreeningStream(runId)
  const eventNames = ['started', 'universe', 'progress', 'hit_raw', 'accepted', 'persisted', 'phase_started', 'phase_completed', 'summary', 'completed', 'error', 'heartbeat']
  for (const name of eventNames) {
    eventSource.addEventListener(name, (event) => {
      streamState.value = name === 'heartbeat' ? 'streaming' : 'connected'
      void handleStreamEvent(name, event)
    })
  }
  eventSource.onerror = () => {
    streamState.value = runSnapshot.value?.status === 'completed' ? 'completed' : 'error'
  }
}

const startRun = async () => {
  startingRun.value = true
  pageError.value = ''
  logEvents.value = []
  acceptedRows.value = []
  prePoolScope.value = 'run'
  resultBranchFilter.value = 'all'
  resultModelFilter.value = 'all'
  closeStream()
  try {
    const { data } = await dailyScreeningApi.startRun(buildStartPayload())
    runSnapshot.value = data?.run || null
    activeRunId.value = runSnapshot.value?.id || ''
    streamState.value = 'starting'
    if (activeRunId.value) {
      connectStream(activeRunId.value)
    }
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '启动扫描失败'
  } finally {
    startingRun.value = false
  }
}

const openKline = (row) => {
  const symbol = row?.symbol || row?.code
  if (!symbol) return
  const routeUrl = window?.location ? new URL('/kline-big', window.location.origin) : null
  if (!routeUrl) return
  routeUrl.searchParams.set('symbol', symbol)
  routeUrl.searchParams.set('period', row?.period || '1d')
  routeUrl.searchParams.set('tabTitle', `${symbol} K线`)
  window.open(routeUrl.toString(), '_blank', 'noopener')
}

const addToStockPool = async (row) => {
  try {
    await dailyScreeningApi.addPrePoolToStockPool({
      code: row.code,
      category: row.category,
      remark: row.remark,
    })
    ElMessage.success(`已加入股票池 ${row.code}`)
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '加入股票池失败'
  }
}

const deletePrePoolRow = async (row) => {
  try {
    await dailyScreeningApi.deletePrePool({
      code: row.code,
      category: row.category,
      remark: row.remark,
    })
    ElMessage.success(`已删除 ${row.code}`)
    await refreshPrePools()
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '删除预选池失败'
  }
}

onMounted(async () => {
  await loadSchema()
})

onBeforeUnmount(() => {
  closeStream()
})
</script>

<style scoped>
.daily-screening-body {
  gap: 16px;
}

.daily-screening-grid {
  display: grid;
  grid-template-columns: minmax(320px, 360px) minmax(360px, 1fr) minmax(360px, 520px);
  gap: 16px;
  min-height: 0;
}

.daily-config-panel,
.daily-stream-panel,
.daily-side-stack {
  min-height: 0;
}

.daily-side-stack {
  display: grid;
  gap: 16px;
}

.daily-model-switch {
  margin-bottom: 16px;
}

.daily-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 12px;
}

.daily-field-control {
  width: 100%;
}

.daily-preview-block,
.daily-guide-block {
  margin-top: 12px;
}

.daily-cli-command {
  margin: 0;
  padding: 12px;
  border-radius: 10px;
  background: #0f172a;
  color: #f8fafc;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.6;
}

.daily-extension-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.daily-guide-list {
  margin: 0;
  padding-left: 18px;
  color: #334155;
  line-height: 1.7;
}

.daily-config-actions {
  display: flex;
  gap: 10px;
  margin-top: 16px;
}

.daily-filter-bar {
  display: grid;
  gap: 10px;
  margin-bottom: 12px;
}

.daily-stream-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 780px;
  overflow: auto;
  padding-right: 4px;
}

.daily-stream-item {
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 12px 14px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
}

.daily-stream-item--success {
  border-color: #bbf7d0;
  background: linear-gradient(180deg, #f0fdf4 0%, #ffffff 100%);
}

.daily-stream-item--warning {
  border-color: #fde68a;
  background: linear-gradient(180deg, #fffbeb 0%, #ffffff 100%);
}

.daily-stream-item--danger {
  border-color: #fecaca;
  background: linear-gradient(180deg, #fef2f2 0%, #ffffff 100%);
}

.daily-stream-item--muted {
  border-color: #cbd5e1;
  background: linear-gradient(180deg, #f8fafc 0%, #ffffff 100%);
}

.daily-stream-item__head {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-bottom: 6px;
  font-size: 12px;
  color: #64748b;
}

.daily-stream-item__event {
  font-weight: 700;
  color: #0f172a;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.daily-stream-item__summary {
  color: #1e293b;
  line-height: 1.6;
  word-break: break-word;
}

.daily-empty {
  border: 1px dashed #cbd5e1;
  border-radius: 14px;
  padding: 18px;
  color: #64748b;
  text-align: center;
}

.daily-row-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

@media (max-width: 1480px) {
  .daily-screening-grid {
    grid-template-columns: minmax(300px, 340px) minmax(320px, 1fr);
  }

  .daily-side-stack {
    grid-column: 1 / -1;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 980px) {
  .daily-screening-grid,
  .daily-side-stack,
  .daily-form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
