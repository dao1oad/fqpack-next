<template>
  <div class="workbench-page daily-screening-page">
    <MyHeader />

    <div
      class="workbench-body daily-screening-body"
      v-loading="loadingSchema || loadingScopes"
    >
      <section class="workbench-toolbar">
        <div class="workbench-toolbar__header">
          <div class="workbench-title-group">
            <div class="workbench-page-title">每日选股</div>
            <div class="workbench-page-meta">
              <span>统一工作台</span>
              <span>/</span>
              <span>执行全链路</span>
              <span>/</span>
              <span>CLXS -> chanlun -> 90天聚合 -> 全市场属性</span>
            </div>
          </div>
          <div class="workbench-toolbar__actions">
            <el-button @click="loadSchema">刷新 schema</el-button>
            <el-button @click="loadScopes">刷新 scopes</el-button>
            <el-button @click="refreshCurrentScope">刷新结果</el-button>
          </div>
        </div>

        <div class="workbench-summary-row">
          <span class="workbench-summary-chip" :class="statusChipClass">
            状态 <strong>{{ runSnapshot?.status || 'idle' }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--muted">
            当前运行 <strong>{{ activeRunId || '-' }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--muted">
            当前 scope <strong>{{ selectedScopeLabel }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--success">
            stock_count <strong>{{ scopeSummary?.stock_count ?? resultRows.length }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--warning">
            membership <strong>{{ scopeSummary?.membership_count ?? 0 }}</strong>
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
        <section class="workbench-panel daily-control-panel">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">执行区</div>
              <p class="workbench-panel__desc">默认执行全链路，也保留 CLXS / chanlun 单独调试入口。</p>
            </div>
          </div>

          <div class="daily-model-switch">
            <el-radio-group v-model="selectedModel" size="small">
              <el-radio-button
                v-for="model in models"
                :key="model.id"
                :value="model.id"
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

          <div class="daily-config-actions">
            <el-button type="primary" :loading="startingRun" @click="startRun">
              开始扫描
            </el-button>
            <el-button @click="hydrateCurrentRun">刷新运行</el-button>
          </div>

          <article class="workbench-block daily-scope-block">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">Scope</div>
                <p class="workbench-panel__desc">可以切换查看最新正式交易日结果，或任意历史 run scope。</p>
              </div>
            </div>
            <el-select
              v-model="selectedRunId"
              placeholder="请选择 scope"
              filterable
              clearable
              class="daily-field-control"
            >
              <el-option
                v-for="item in scopeItems"
                :key="item.runId"
                :label="item.isLatest ? `${item.label}（latest）` : item.label"
                :value="item.runId"
              />
            </el-select>
          </article>

          <article class="workbench-block">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">SSE 事件流</div>
                <p class="workbench-panel__desc">保留实时运行过程，便于确认每个阶段已经完成到哪里。</p>
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
                暂无事件。
              </div>
            </div>
          </article>
        </section>

        <section class="workbench-panel daily-results-panel" v-loading="queryLoading">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">交集筛选</div>
              <p class="workbench-panel__desc">来源之间做交集，来源内维度做并集。点击结果行查看统一详情。</p>
            </div>
            <div class="workbench-panel__meta">
              <span>{{ resultRows.length }} 条</span>
            </div>
          </div>

          <div class="daily-set-grid">
            <el-button
              v-for="item in setOptions"
              :key="item.key"
              size="small"
              :type="selectedSets.includes(item.key) ? 'primary' : 'default'"
              :plain="!selectedSets.includes(item.key)"
              @click="toggleSet(item.key)"
            >
              {{ item.label }} · {{ item.count }}
            </el-button>
          </div>

          <div class="daily-filter-groups">
            <article class="workbench-block">
              <div class="workbench-panel__title">CLXS 命中模型</div>
              <div class="daily-chip-grid">
                <el-button
                  v-for="option in clxsModelOptions"
                  :key="option.value"
                  size="small"
                  :type="clxsModels.includes(option.value) ? 'primary' : 'default'"
                  :plain="!clxsModels.includes(option.value)"
                  @click="toggleSelection('clxsModels', option.value)"
                >
                  {{ option.label }}
                </el-button>
              </div>
            </article>

            <article class="workbench-block">
              <div class="workbench-panel__title">chanlun 命中信号</div>
              <div class="daily-chip-grid">
                <el-button
                  v-for="option in chanlunSignalOptions"
                  :key="option.value"
                  size="small"
                  :type="chanlunSignalTypes.includes(option.value) ? 'primary' : 'default'"
                  :plain="!chanlunSignalTypes.includes(option.value)"
                  @click="toggleSelection('chanlunSignalTypes', option.value)"
                >
                  {{ option.label }}
                </el-button>
              </div>
            </article>

            <article class="workbench-block">
              <div class="workbench-panel__title">chanlun 周期</div>
              <div class="daily-chip-grid">
                <el-button
                  v-for="period in chanlunPeriodOptions"
                  :key="period"
                  size="small"
                  :type="chanlunPeriods.includes(period) ? 'primary' : 'default'"
                  :plain="!chanlunPeriods.includes(period)"
                  @click="toggleSelection('chanlunPeriods', period)"
                >
                  {{ period }}
                </el-button>
              </div>
            </article>

            <article class="workbench-block">
              <div class="workbench-panel__title">90天聚合来源</div>
              <div class="daily-chip-grid">
                <el-button
                  v-for="provider in shouban30ProviderOptions"
                  :key="provider.value"
                  size="small"
                  :type="shouban30Providers.includes(provider.value) ? 'primary' : 'default'"
                  :plain="!shouban30Providers.includes(provider.value)"
                  @click="toggleSelection('shouban30Providers', provider.value)"
                >
                  {{ provider.label }}
                </el-button>
              </div>
            </article>
          </div>

          <div class="daily-filter-actions">
            <span class="daily-expression">当前交集：{{ intersectionExpression }}</span>
            <div class="daily-action-buttons">
              <el-button type="primary" @click="queryRows">查询结果</el-button>
              <el-button @click="resetFilters">重置筛选</el-button>
              <el-button
                type="success"
                :disabled="!selectedRunId || resultRows.length === 0"
                @click="addBatchToPrePool"
              >
                当前交集加入 pre_pools
              </el-button>
            </div>
          </div>

          <el-table
            :data="resultRows"
            size="small"
            border
            height="560"
            @row-click="handleRowClick"
          >
            <el-table-column prop="code" label="代码" width="88" />
            <el-table-column prop="name" label="名称" min-width="100" show-overflow-tooltip />
            <el-table-column label="CLXS" width="72">
              <template #default="{ row }">
                {{ row.clxsCount }}
              </template>
            </el-table-column>
            <el-table-column label="chanlun" width="88">
              <template #default="{ row }">
                {{ row.chanlunCount }}
              </template>
            </el-table-column>
            <el-table-column label="90天聚合" min-width="120" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.shouban30Providers.join(' / ') || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="融资" width="70">
              <template #default="{ row }">
                {{ row.selectedBy.credit_subject ? '是' : '-' }}
              </template>
            </el-table-column>
            <el-table-column label="均线附近" width="86">
              <template #default="{ row }">
                {{ row.selectedBy.near_long_term_ma ? '是' : '-' }}
              </template>
            </el-table-column>
            <el-table-column label="优质" width="70">
              <template #default="{ row }">
                {{ row.selectedBy.quality_subject ? '是' : '-' }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <div class="daily-row-actions">
                  <el-button type="primary" text @click.stop="openKline(row)">K线</el-button>
                  <el-button type="success" text @click.stop="addRowToPrePool(row)">加入 pre_pools</el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </section>

        <aside class="daily-detail-stack" v-loading="detailLoading">
          <section class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">标的详情</div>
                <p class="workbench-panel__desc">复用 Shouban30 的热门理由展示方式，并补充 CLXS / chanlun 命中明细。</p>
              </div>
            </div>

            <div v-if="detailSnapshot" class="daily-detail-summary">
              <div class="daily-detail-summary__head">
                <div>
                  <div class="daily-detail-title">{{ detailSnapshot.name || detailSnapshot.code }}</div>
                  <div class="daily-detail-meta">
                    <span class="workbench-code">{{ detailSnapshot.code }}</span>
                    <span>/</span>
                    <span>{{ detailSnapshot.shouban30Providers.join(' / ') || '无 90 天聚合来源' }}</span>
                  </div>
                </div>
                <div class="daily-detail-actions">
                  <el-button type="primary" text @click="openKline(detailSnapshot)">K线</el-button>
                  <el-button type="success" text @click="addRowToPrePool(detailSnapshot)">加入 pre_pools</el-button>
                </div>
              </div>

              <div class="daily-flag-grid">
                <span class="workbench-summary-chip" :class="detailSnapshot.selectedBy.clxs ? 'workbench-summary-chip--success' : 'workbench-summary-chip--muted'">CLXS {{ detailSnapshot.clxsCount }}</span>
                <span class="workbench-summary-chip" :class="detailSnapshot.selectedBy.chanlun ? 'workbench-summary-chip--success' : 'workbench-summary-chip--muted'">chanlun {{ detailSnapshot.chanlunCount }}</span>
                <span class="workbench-summary-chip" :class="detailSnapshot.selectedBy.shouban30_agg90 ? 'workbench-summary-chip--success' : 'workbench-summary-chip--muted'">90天聚合</span>
                <span class="workbench-summary-chip" :class="detailSnapshot.selectedBy.credit_subject ? 'workbench-summary-chip--success' : 'workbench-summary-chip--muted'">融资标的</span>
                <span class="workbench-summary-chip" :class="detailSnapshot.selectedBy.near_long_term_ma ? 'workbench-summary-chip--success' : 'workbench-summary-chip--muted'">均线附近</span>
                <span class="workbench-summary-chip" :class="detailSnapshot.selectedBy.quality_subject ? 'workbench-summary-chip--success' : 'workbench-summary-chip--muted'">优质标的</span>
              </div>
            </div>
            <div v-else class="daily-empty">
              请先选择一只股票。
            </div>
          </section>

          <section class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">CLXS 命中模型</div>
              </div>
            </div>
            <el-table
              :data="detail.clxs_memberships"
              size="small"
              border
              height="180"
              empty-text="暂无 CLXS 命中"
            >
              <el-table-column prop="model_label" label="模型" width="88" />
              <el-table-column prop="signal_type" label="信号" min-width="120" show-overflow-tooltip />
              <el-table-column label="触发时间" min-width="150">
                <template #default="{ row }">
                  {{ formatDateTime(row.fire_time) }}
                </template>
              </el-table-column>
              <el-table-column label="止损" width="80">
                <template #default="{ row }">
                  {{ formatNumber(row.stop_loss_price) }}
                </template>
              </el-table-column>
            </el-table>
          </section>

          <section class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">chanlun 命中信号</div>
              </div>
            </div>
            <el-table
              :data="detail.chanlun_memberships"
              size="small"
              border
              height="200"
              empty-text="暂无 chanlun 命中"
            >
              <el-table-column prop="signal_type" label="信号" min-width="120" show-overflow-tooltip />
              <el-table-column prop="period" label="周期" width="76" />
              <el-table-column label="触发时间" min-width="150">
                <template #default="{ row }">
                  {{ formatDateTime(row.fire_time) }}
                </template>
              </el-table-column>
              <el-table-column label="止损" width="80">
                <template #default="{ row }">
                  {{ formatNumber(row.stop_loss_price) }}
                </template>
              </el-table-column>
            </el-table>
          </section>

          <section class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">90天聚合 / 属性</div>
              </div>
            </div>
            <div class="daily-chip-grid daily-chip-grid--compact">
              <span
                v-for="provider in detailSnapshot?.shouban30Providers || []"
                :key="provider"
                class="workbench-summary-chip workbench-summary-chip--muted"
              >
                {{ provider }}
              </span>
              <span
                v-for="item in detail.market_flag_memberships"
                :key="`${item.signal_type}-${item.code}`"
                class="workbench-summary-chip workbench-summary-chip--warning"
              >
                {{ item.signal_type }}
              </span>
            </div>
          </section>

          <section class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">历史热门理由</div>
                <p class="workbench-panel__desc">直接复用 Shouban30 的热门理由展示方式。</p>
              </div>
            </div>
            <el-table
              :data="detail.hot_reasons"
              size="small"
              border
              height="260"
              empty-text="暂无热门理由"
            >
              <el-table-column prop="date" label="日期" width="104" />
              <el-table-column prop="time" label="时间" width="70" />
              <el-table-column prop="provider" label="来源" width="76">
                <template #default="{ row }">
                  {{ formatProvider(row.provider) }}
                </template>
              </el-table-column>
              <el-table-column prop="plate_name" label="板块" width="120" show-overflow-tooltip />
              <el-table-column label="理由" min-width="220">
                <template #default="{ row }">
                  <Shouban30ReasonPopover
                    :reference-text="row.stock_reason || row.plate_reason"
                    :title="detailSnapshot ? `${detailSnapshot.name || detailSnapshot.code} ${detailSnapshot.code || ''}`.trim() : '标的理由'"
                    :subtitle="buildReasonDetailSubtitle(row)"
                    placement="left-start"
                    :width="620"
                  >
                    <div class="shouban30-reason-grid">
                      <div class="shouban30-reason-grid__label">板块</div>
                      <div class="shouban30-reason-grid__value">{{ row.plate_name || '-' }}</div>
                      <div class="shouban30-reason-grid__label">来源</div>
                      <div class="shouban30-reason-grid__value">{{ formatProvider(row.provider) }}</div>
                    </div>
                    <div class="shouban30-reason-section">
                      <div class="shouban30-reason-section__label">标的理由</div>
                      <div class="shouban30-reason-section__body">{{ row.stock_reason || '-' }}</div>
                    </div>
                    <div class="shouban30-reason-section">
                      <div class="shouban30-reason-section__label">板块理由</div>
                      <div class="shouban30-reason-section__body">{{ row.plate_reason || '-' }}</div>
                    </div>
                  </Shouban30ReasonPopover>
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
import Shouban30ReasonPopover from './components/Shouban30ReasonPopover.vue'
import { dailyScreeningApi, createDailyScreeningStream } from '@/api/dailyScreeningApi.js'
import {
  buildDailyScreeningForms,
  buildDailyScreeningQueryPayload,
  buildDailyScreeningSetOptions,
  buildDailyScreeningWorkbenchState,
  formatDailyScreeningSetLabel,
  normalizeDailyScreeningDetail,
  normalizeDailyScreeningResultRows,
  normalizeDailyScreeningScopeItems,
  readDailyScreeningPayload,
  resolveDailyScreeningFields,
  toggleDailyScreeningSelection,
} from './dailyScreeningPage.mjs'

const loadingSchema = ref(false)
const loadingScopes = ref(false)
const queryLoading = ref(false)
const detailLoading = ref(false)
const startingRun = ref(false)
const pageError = ref('')

const schema = ref({ models: [], options: {} })
const forms = reactive({
  all: {},
  clxs: {},
  chanlun: {},
})
const selectedModel = ref('all')

const activeRunId = ref('')
const selectedRunId = ref('')
const scopeItems = ref([])
const scopeSummary = ref({})
const runSnapshot = ref(null)
const streamState = ref('idle')
const logEvents = ref([])
const resultRows = ref([])
const selectedResultCode = ref('')
const detail = ref({
  snapshot: null,
  clxs_memberships: [],
  chanlun_memberships: [],
  agg90_memberships: [],
  market_flag_memberships: [],
  hot_reasons: [],
})

const selectedSets = ref([])
const clxsModels = ref([])
const chanlunSignalTypes = ref([])
const chanlunPeriods = ref([])
const shouban30Providers = ref([])

let eventSource = null

const models = computed(() => Array.isArray(schema.value?.models) ? schema.value.models : [])
const currentForm = computed(() => forms[selectedModel.value] || {})
const visibleFields = computed(() => resolveDailyScreeningFields(schema.value, selectedModel.value, currentForm.value))
const setOptions = computed(() => buildDailyScreeningSetOptions(scopeSummary.value))
const orderedLogEvents = computed(() => [...logEvents.value].reverse())
const detailSnapshot = computed(() => detail.value?.snapshot || null)
const selectedScopeLabel = computed(() => {
  const matched = scopeItems.value.find((item) => item.runId === selectedRunId.value)
  return matched?.label || selectedRunId.value || '-'
})
const clxsModelOptions = computed(() => {
  const allModel = models.value.find((item) => item.id === 'all')
  const field = allModel?.fields?.find((item) => item.name === 'clxs_model_opts')
  return field?.options || []
})
const chanlunSignalOptions = computed(() => {
  const allModel = models.value.find((item) => item.id === 'all')
  const field = allModel?.fields?.find((item) => item.name === 'chanlun_signal_types')
  return field?.options || []
})
const chanlunPeriodOptions = computed(() => ['30m', '60m', '1d'])
const shouban30ProviderOptions = computed(() => ([
  { value: 'xgb', label: '选股通' },
  { value: 'jygs', label: '韭研公社' },
]))
const intersectionExpression = computed(() => {
  if (!selectedSets.value.length) return '全部来源'
  return selectedSets.value.map((item) => formatDailyScreeningSetLabel(item)).join(' / ')
})

const statusChipClass = computed(() => {
  const status = String(runSnapshot.value?.status || '').toLowerCase()
  if (status === 'completed') return 'workbench-summary-chip--success'
  if (status === 'failed') return 'workbench-summary-chip--danger'
  if (status === 'running') return 'workbench-summary-chip--warning'
  return 'workbench-summary-chip--muted'
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

const buildStateDefaults = (latestScope = null) => {
  const state = buildDailyScreeningWorkbenchState(schema.value, latestScope)
  selectedModel.value = state.selectedModel
  if (!selectedRunId.value) {
    selectedRunId.value = state.selectedRunId
  }
  selectedSets.value = [...state.selectedSets]
  clxsModels.value = [...state.clxsModels]
  chanlunSignalTypes.value = [...state.chanlunSignalTypes]
  chanlunPeriods.value = [...state.chanlunPeriods]
  shouban30Providers.value = [...state.shouban30Providers]
}

const loadSchema = async () => {
  loadingSchema.value = true
  try {
    const payload = readDailyScreeningPayload(await dailyScreeningApi.getSchema())
    schema.value = payload || { models: [], options: {} }
    applyForms(buildDailyScreeningForms(schema.value))
    buildStateDefaults()
    pageError.value = ''
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '加载 schema 失败'
  } finally {
    loadingSchema.value = false
  }
}

const loadScopes = async () => {
  loadingScopes.value = true
  try {
    const [scopesPayload, latestPayload] = await Promise.all([
      dailyScreeningApi.getScopes(),
      dailyScreeningApi.getLatestScope(),
    ])
    scopeItems.value = normalizeDailyScreeningScopeItems(readDailyScreeningPayload(scopesPayload))
    const latestScope = readDailyScreeningPayload(latestPayload)
    if (!selectedRunId.value && latestScope?.run_id) {
      selectedRunId.value = latestScope.run_id
    }
    if (!selectedSets.value.length) {
      buildStateDefaults(latestScope)
    }
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '加载 scopes 失败'
  } finally {
    loadingScopes.value = false
  }
}

const hydrateCurrentRun = async () => {
  if (!activeRunId.value) return
  try {
    const payload = readDailyScreeningPayload(await dailyScreeningApi.getRun(activeRunId.value))
    runSnapshot.value = payload?.run || null
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '加载运行状态失败'
  }
}

const queryRows = async () => {
  if (!selectedRunId.value) {
    resultRows.value = []
    return
  }
  queryLoading.value = true
  try {
    const payload = readDailyScreeningPayload(await dailyScreeningApi.queryStocks(
      buildDailyScreeningQueryPayload({
        runId: selectedRunId.value,
        selectedSets: selectedSets.value,
        clxsModels: clxsModels.value,
        chanlunSignalTypes: chanlunSignalTypes.value,
        chanlunPeriods: chanlunPeriods.value,
        shouban30Providers: shouban30Providers.value,
      }),
    ))
    resultRows.value = normalizeDailyScreeningResultRows(payload?.rows)
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '查询交集结果失败'
  } finally {
    queryLoading.value = false
  }
}

const loadDetail = async (code) => {
  if (!selectedRunId.value || !code) {
    detail.value = normalizeDailyScreeningDetail({})
    return
  }
  detailLoading.value = true
  try {
    const payload = readDailyScreeningPayload(await dailyScreeningApi.getStockDetail(selectedRunId.value, code))
    detail.value = normalizeDailyScreeningDetail(payload)
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '加载标的详情失败'
  } finally {
    detailLoading.value = false
  }
}

const refreshCurrentScope = async () => {
  if (!selectedRunId.value) return
  try {
    const payload = readDailyScreeningPayload(await dailyScreeningApi.getScopeSummary(selectedRunId.value))
    scopeSummary.value = payload || {}
    await queryRows()
    if (selectedResultCode.value) {
      await loadDetail(selectedResultCode.value)
    }
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '刷新 scope 失败'
  }
}

const buildStartPayload = () => ({
  model: selectedModel.value,
  ...currentForm.value,
})

const startRun = async () => {
  startingRun.value = true
  pageError.value = ''
  logEvents.value = []
  try {
    const payload = readDailyScreeningPayload(await dailyScreeningApi.startRun(buildStartPayload()))
    runSnapshot.value = payload?.run || null
    activeRunId.value = runSnapshot.value?.id || ''
    if (activeRunId.value) {
      selectedRunId.value = activeRunId.value
      await loadScopes()
      connectStream(activeRunId.value)
      await refreshCurrentScope()
    }
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '启动扫描失败'
  } finally {
    startingRun.value = false
  }
}

const toggleSet = (key) => {
  selectedSets.value = toggleDailyScreeningSelection(selectedSets.value, key)
}

const toggleSelection = (field, value) => {
  if (field === 'clxsModels') {
    clxsModels.value = toggleDailyScreeningSelection(clxsModels.value, value)
    return
  }
  if (field === 'chanlunSignalTypes') {
    chanlunSignalTypes.value = toggleDailyScreeningSelection(chanlunSignalTypes.value, value)
    return
  }
  if (field === 'chanlunPeriods') {
    chanlunPeriods.value = toggleDailyScreeningSelection(chanlunPeriods.value, value)
    return
  }
  if (field === 'shouban30Providers') {
    shouban30Providers.value = toggleDailyScreeningSelection(shouban30Providers.value, value)
  }
}

const resetFilters = () => {
  selectedSets.value = ['clxs', 'chanlun']
  clxsModels.value = []
  chanlunSignalTypes.value = []
  chanlunPeriods.value = []
  shouban30Providers.value = []
}

const handleRowClick = (row) => {
  selectedResultCode.value = row.code
}

const addRowToPrePool = async (row) => {
  if (!selectedRunId.value || !row?.code) return
  try {
    await dailyScreeningApi.addToPrePool({
      run_id: selectedRunId.value,
      code: row.code,
    })
    ElMessage.success(`已加入 pre_pools ${row.code}`)
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '加入 pre_pools 失败'
  }
}

const addBatchToPrePool = async () => {
  if (!selectedRunId.value) return
  try {
    const payload = readDailyScreeningPayload(await dailyScreeningApi.addBatchToPrePool(
      buildDailyScreeningQueryPayload({
        runId: selectedRunId.value,
        selectedSets: selectedSets.value,
        clxsModels: clxsModels.value,
        chanlunSignalTypes: chanlunSignalTypes.value,
        chanlunPeriods: chanlunPeriods.value,
        shouban30Providers: shouban30Providers.value,
      }),
    ))
    ElMessage.success(`已加入 pre_pools ${payload?.created_count ?? 0} 条`)
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '批量加入 pre_pools 失败'
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

const eventToneMap = {
  run_started: 'neutral',
  started: 'neutral',
  stage_started: 'warning',
  phase_started: 'warning',
  stage_progress: 'warning',
  progress: 'warning',
  accepted: 'success',
  persisted: 'success',
  stage_completed: 'neutral',
  phase_completed: 'neutral',
  summary: 'neutral',
  run_completed: 'success',
  completed: 'success',
  run_failed: 'danger',
  error: 'danger',
  heartbeat: 'muted',
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

const eventSummary = (eventName, payload = {}) => {
  if (eventName === 'stage_started' || eventName === 'phase_started') {
    return `${payload.stage || payload.branch || '-'} ${payload.label || '-'}`
  }
  if (eventName === 'stage_progress' || eventName === 'progress') {
    return `${payload.stage || '-'} ${payload.kind || '-'} ${payload.code || '-'}`
  }
  if (eventName === 'accepted') {
    return `${payload.code || '-'} ${payload.signal_type || '-'} ${payload.period || '-'}`
  }
  if (eventName === 'stage_completed' || eventName === 'phase_completed') {
    return `${payload.stage || payload.branch || '-'} accepted=${payload.accepted_count || 0}`
  }
  if (eventName === 'summary' || eventName === 'run_completed' || eventName === 'completed') {
    return `accepted=${payload.accepted_count || payload.accepted || 0}, persisted=${payload.persisted_count || payload.persisted || 0}`
  }
  if (eventName === 'run_failed' || eventName === 'error') {
    return payload.message || payload.error || 'unknown error'
  }
  return JSON.stringify(payload)
}

const pushLogEvent = (record = {}) => {
  const data = record.data || {}
  logEvents.value.push({
    seq: record.seq || logEvents.value.length + 1,
    event: record.event,
    tone: eventToneMap[record.event] || 'neutral',
    tsLabel: formatDateTime(record.ts),
    summary: eventSummary(record.event, data),
  })
}

const handleStreamEvent = async (eventName, rawEvent) => {
  let record
  try {
    record = JSON.parse(rawEvent.data || '{}')
  } catch (_error) {
    record = { seq: logEvents.value.length + 1, event: eventName, ts: new Date().toISOString(), data: {} }
  }
  pushLogEvent({
    ...record,
    event: eventName,
  })
  if (eventName === 'error' || eventName === 'run_failed') {
    pageError.value = record.data?.message || record.data?.error || '扫描失败'
  }
  if (['summary', 'completed', 'run_completed', 'run_failed', 'stage_completed'].includes(eventName)) {
    await hydrateCurrentRun()
    await loadScopes()
    await refreshCurrentScope()
    if (['completed', 'run_completed', 'run_failed'].includes(eventName)) {
      closeStream()
      streamState.value = runSnapshot.value?.status || eventName
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
  const eventNames = [
    'run_started',
    'started',
    'stage_started',
    'phase_started',
    'stage_progress',
    'progress',
    'accepted',
    'persisted',
    'stage_completed',
    'phase_completed',
    'summary',
    'run_completed',
    'completed',
    'run_failed',
    'error',
    'heartbeat',
  ]
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
    remark: '来源备注',
    input_mode: '输入模式',
    period_mode: '周期模式',
    chanlun_period_mode: 'chanlun 周期',
    pre_pool_category: '预选池分类',
    pre_pool_remark: '预选池来源',
    pool_expire_days: '股票池天数',
  }
  return labels[field.name] || field.name
}

const formatProvider = (value) => {
  const provider = String(value || '').trim().toLowerCase()
  if (provider === 'xgb') return '选股通'
  if (provider === 'jygs') return '韭研公社'
  return provider || '-'
}

const buildReasonDetailSubtitle = (row) => {
  const date = String(row?.date || '').trim() || '-'
  const time = String(row?.time || '').trim()
  return `${formatProvider(row?.provider)} / ${time ? `${date} ${time}` : date}`
}

watch(selectedRunId, async (runId) => {
  if (!runId) return
  await refreshCurrentScope()
})

watch(resultRows, async (rows) => {
  if (!rows.length) {
    selectedResultCode.value = ''
    detail.value = normalizeDailyScreeningDetail({})
    return
  }
  const currentExists = rows.some((item) => item.code === selectedResultCode.value)
  if (!currentExists) {
    selectedResultCode.value = rows[0].code
  }
})

watch(selectedResultCode, async (code) => {
  if (!code) return
  await loadDetail(code)
})

onMounted(async () => {
  await loadSchema()
  await loadScopes()
  if (selectedRunId.value) {
    await refreshCurrentScope()
  }
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
  grid-template-columns: minmax(320px, 380px) minmax(420px, 1fr) minmax(360px, 460px);
  gap: 16px;
  min-height: 0;
}

.daily-control-panel,
.daily-results-panel,
.daily-detail-stack {
  min-height: 0;
}

.daily-detail-stack {
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

.daily-config-actions {
  display: flex;
  gap: 10px;
  margin-top: 8px;
}

.daily-scope-block {
  margin-top: 14px;
}

.daily-set-grid,
.daily-chip-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.daily-chip-grid--compact {
  min-height: 28px;
}

.daily-filter-groups {
  display: grid;
  gap: 12px;
  margin: 14px 0;
}

.daily-filter-actions {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  margin-bottom: 12px;
}

.daily-action-buttons {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.daily-expression {
  color: #475569;
  font-size: 12px;
}

.daily-stream-list {
  display: grid;
  gap: 10px;
  max-height: 320px;
  overflow: auto;
}

.daily-stream-item {
  border: 1px solid #dbe4ef;
  border-radius: 12px;
  padding: 10px 12px;
  background: #fff;
}

.daily-stream-item--success {
  border-color: #bfdbca;
  background: #f0fdf4;
}

.daily-stream-item--warning {
  border-color: #f5d59d;
  background: #fff7e6;
}

.daily-stream-item--danger {
  border-color: #f0b6b6;
  background: #fff1f2;
}

.daily-stream-item--muted {
  border-color: #d7dde7;
  background: #f8fafc;
}

.daily-stream-item__head {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
  font-size: 12px;
  color: #475569;
}

.daily-stream-item__event {
  font-weight: 700;
  color: #0f172a;
}

.daily-stream-item__summary {
  margin-top: 6px;
  color: #1e293b;
  font-size: 13px;
  line-height: 1.5;
  word-break: break-word;
}

.daily-row-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.daily-detail-summary {
  display: grid;
  gap: 12px;
}

.daily-detail-summary__head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.daily-detail-title {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}

.daily-detail-meta {
  margin-top: 6px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  color: #64748b;
}

.daily-detail-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.daily-flag-grid {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.daily-empty {
  padding: 20px 0;
  text-align: center;
  color: #64748b;
  font-size: 13px;
}

@media (max-width: 1600px) {
  .daily-screening-grid {
    grid-template-columns: minmax(300px, 360px) minmax(380px, 1fr);
  }

  .daily-detail-stack {
    grid-column: 1 / -1;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1200px) {
  .daily-screening-grid {
    grid-template-columns: 1fr;
  }

  .daily-detail-stack {
    grid-column: auto;
    grid-template-columns: 1fr;
  }

  .daily-filter-actions,
  .daily-detail-summary__head {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
