<template>
  <section
    class="clx-selection-panel"
    aria-label="CLX 筛选结果"
    :aria-busy="loading.bootstrap || loading.results"
  >
    <header class="clx-selection-panel__header">
      <div>
        <strong>CLX 筛选</strong>
        <span>选中标的后在右侧看 K 线与信号</span>
      </div>
      <el-button
        size="small"
        :loading="loading.bootstrap"
        aria-label="刷新 CLX 筛选批次和结果"
        @click="refreshAll"
      >
        刷新
      </el-button>
    </header>

    <div class="clx-selection-panel__controls">
      <label class="clx-selection-panel__label" for="clx-panel-scope">结果批次</label>
      <el-select
        id="clx-panel-scope"
        v-model="selectedScopeId"
        size="small"
        placeholder="请选择结果批次"
        :disabled="loading.bootstrap || !scopes.length"
        @change="handleScopeChange"
      >
        <el-option
          v-for="scope in scopes"
          :key="scope.scopeId"
          :label="formatScopeOption(scope)"
          :value="scope.scopeId"
        />
      </el-select>

      <div v-if="activeScope" class="clx-selection-panel__status" aria-live="polite">
        <StatusChip :variant="scopeStatus.variant" :title="scopeStatus.detail">
          {{ scopeStatus.label }}
        </StatusChip>
        <StatusChip :variant="stockStatus.variant">
          {{ stockStatus.label }} · {{ activeScope.partitions.stock.hitCount }}
        </StatusChip>
        <StatusChip :variant="etfStatus.variant">
          {{ etfStatus.label }} · {{ activeScope.partitions.etf.hitCount }}
        </StatusChip>
      </div>

      <el-input
        v-model="filters.q"
        size="small"
        clearable
        aria-label="搜索代码或名称"
        placeholder="搜索代码或名称"
      />

      <div class="clx-selection-panel__quick-row">
        <el-radio-group v-model="assetMode" size="small" aria-label="资产类型">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="stock">股票</el-radio-button>
          <el-radio-button value="etf">ETF</el-radio-button>
        </el-radio-group>
        <label class="clx-selection-panel__min-model">
          <span>最少模型</span>
          <el-input-number
            v-model="filters.minModelCount"
            size="small"
            :min="1"
            :max="18"
            controls-position="right"
            aria-label="最少模型数"
          />
        </label>
      </div>

      <div class="clx-selection-panel__filter-actions">
        <button
          type="button"
          class="clx-selection-panel__more-toggle"
          :aria-expanded="showMoreFilters"
          aria-controls="clx-panel-more-filters"
          @click="showMoreFilters = !showMoreFilters"
        >
          {{ showMoreFilters ? '收起筛选' : '更多筛选' }}
          <span v-if="advancedFilterCount">({{ advancedFilterCount }})</span>
        </button>
        <el-button text size="small" @click="resetFilters">重置</el-button>
      </div>

      <div
        v-show="showMoreFilters"
        id="clx-panel-more-filters"
        class="clx-selection-panel__more"
      >
        <fieldset>
          <legend>模型</legend>
          <el-input
            v-model="modelSearch"
            size="small"
            clearable
            aria-label="搜索 CLX 模型"
            placeholder="搜索 S0000-S0017"
          />
          <el-checkbox-group v-model="filters.modelKeys" class="clx-selection-panel__checks">
            <el-checkbox
              v-for="model in visibleModels"
              :key="model.key"
              :value="model.key"
            >
              {{ model.key }} {{ model.label && model.label !== model.key ? model.label : '' }}
            </el-checkbox>
          </el-checkbox-group>
        </fieldset>

        <fieldset>
          <legend>条件</legend>
          <el-checkbox-group v-model="filters.conditionKeys" class="clx-selection-panel__checks">
            <el-checkbox
              v-for="condition in catalog.conditions"
              :key="condition.key"
              :value="condition.key"
            >
              {{ condition.label || condition.key }}
            </el-checkbox>
          </el-checkbox-group>
          <span v-if="!catalog.conditions.length" class="clx-selection-panel__muted">暂无条件目录</span>
        </fieldset>

        <fieldset>
          <legend>方向</legend>
          <el-checkbox-group v-model="filters.directions">
            <el-checkbox value="buy">买入</el-checkbox>
            <el-checkbox value="sell">卖出</el-checkbox>
          </el-checkbox-group>
        </fieldset>

        <fieldset class="clx-selection-panel__line-filters">
          <legend>线关系</legend>
          <label v-for="line in lineFilterOptions" :key="line.key">
            <span>{{ line.label }}</span>
            <el-select v-model="filters.lineFlags[line.key]" size="small" placeholder="全部">
              <el-option label="全部" value="" />
              <el-option label="站上" value="yes" />
              <el-option label="下方" value="no" />
              <el-option label="未知" value="unknown" />
            </el-select>
          </label>
        </fieldset>
      </div>
    </div>

    <div class="clx-selection-panel__results-head">
      <strong>标的列表</strong>
      <span aria-live="polite">已加载 {{ rows.length }} / {{ total }}</span>
    </div>

    <div v-if="pageError" class="clx-selection-panel__alert" role="alert">
      {{ pageError }}
    </div>
    <div v-if="activeSymbolHint" class="clx-selection-panel__hint" role="status">
      {{ activeSymbolHint }}
    </div>

    <div class="clx-selection-panel__result-body">
      <div
        v-if="(loading.bootstrap || loading.results) && !rows.length"
        class="clx-selection-panel__empty"
        role="status"
      >
        正在加载 CLX 筛选结果…
      </div>
      <div
        v-else-if="!selectedScopeId"
        class="clx-selection-panel__empty"
        role="status"
      >
        暂无正式完整结果；可在上方显式选择部分批次。
      </div>
      <div
        v-else-if="hasLoaded && !rows.length && !pageError"
        class="clx-selection-panel__empty"
        role="status"
      >
        当前筛选条件下没有标的。
      </div>
      <div v-else class="clx-selection-panel__list" role="list" aria-label="CLX 标的列表">
        <button
          v-for="row in rows"
          :key="`${row.assetType}:${row.symbol}`"
          type="button"
          class="clx-selection-panel__row"
          :class="{ 'is-active': isActiveRow(row) }"
          :aria-current="isActiveRow(row) ? 'true' : undefined"
          @click="selectRow(row)"
        >
          <span class="clx-selection-panel__row-main">
            <strong>{{ row.name || row.code || row.symbol }}</strong>
            <span>{{ row.symbol }}</span>
          </span>
          <span class="clx-selection-panel__row-counts">
            <span>{{ row.assetType === 'etf' ? 'ETF' : '股票' }}</span>
            <span>{{ row.distinctModelCount }} 模型</span>
            <span>{{ row.distinctConditionCount }} 条件</span>
          </span>
          <span v-if="row.modelKeys.length" class="clx-selection-panel__models">
            {{ row.modelKeys.slice(0, 5).join(' · ') }}<template v-if="row.modelKeys.length > 5"> · +{{ row.modelKeys.length - 5 }}</template>
          </span>
        </button>
      </div>
    </div>

    <footer v-if="nextCursor" class="clx-selection-panel__footer">
      <el-button
        size="small"
        :loading="loading.more"
        :disabled="loading.results"
        @click="loadMore"
      >
        加载更多（每批 100）
      </el-button>
    </footer>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { clxDailySelectionApi } from '@/api/clxDailySelectionApi.js'
import StatusChip from '@/components/workbench/StatusChip.vue'
import {
  buildClxSelectionQueryPayload,
  createClxRequestChannel,
  getClxPartitionStatusMeta,
  getClxScopeStatusMeta,
  mergeClxScopes,
  normalizeClxCatalog,
  normalizeClxScopes,
  normalizeClxSelectionQuery,
  pickDefaultClxScope,
} from '@/views/clxDailySelection.mjs'
import {
  buildKlineClxScreeningQuery,
  parseKlineClxScreeningQuery,
} from '@/views/js/kline-slim-clx.mjs'
import {
  applyClxPanelScopeDate,
  appendClxPanelRows,
  buildClxPanelRequestKey,
  isSameClxPanelSymbol,
  resolveClxPanelAutoSelection,
  resolveClxPanelRouteEntry,
} from './clxSelectionPanel.mjs'

const props = defineProps({
  activeSymbol: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['select'])
const route = useRoute()
const router = useRouter()

const bootstrapRequests = createClxRequestChannel()
const resultRequests = createClxRequestChannel()
const scopes = ref([])
const selectedScopeId = ref('')
const catalog = ref({ models: [], conditions: [], version: '', raw: {} })
const rows = ref([])
const total = ref(0)
const nextCursor = ref('')
const hasLoaded = ref(false)
const pageError = ref('')
const modelSearch = ref('')
const showMoreFilters = ref(false)
const currentResultRequestKey = ref('')
const autoSelectedRequestKey = ref('')
const loading = reactive({ bootstrap: false, results: false, more: false })
const filters = reactive({
  q: '',
  assetTypes: [],
  modelKeys: [],
  conditionKeys: [],
  directions: [],
  minModelCount: 1,
  lineFlags: {
    above_chanlun_line: '',
    above_ma250: '',
    above_reference_line: '',
  },
})

const lineFilterOptions = [
  { key: 'above_chanlun_line', label: '缠论连线' },
  { key: 'above_ma250', label: 'MA250' },
  { key: 'above_reference_line', label: '模型参考线' },
]

let applyingRouteState = false
let queryTimer = null
let pendingResultReload = false

const activeScope = computed(() => (
  scopes.value.find((scope) => scope.scopeId === selectedScopeId.value) || null
))
const scopeStatus = computed(() => getClxScopeStatusMeta(activeScope.value || {}))
const stockStatus = computed(() => getClxPartitionStatusMeta(activeScope.value?.partitions?.stock, 'stock'))
const etfStatus = computed(() => getClxPartitionStatusMeta(activeScope.value?.partitions?.etf, 'etf'))
const assetMode = computed({
  get: () => filters.assetTypes.length === 1 ? filters.assetTypes[0] : 'all',
  set: (value) => { filters.assetTypes = value === 'all' ? [] : [value] },
})
const visibleModels = computed(() => {
  const q = modelSearch.value.trim().toLowerCase()
  if (!q) return catalog.value.models
  return catalog.value.models.filter((model) => (
    `${model.key} ${model.label}`.toLowerCase().includes(q)
  ))
})
const advancedFilterCount = computed(() => (
  filters.modelKeys.length +
  filters.conditionKeys.length +
  filters.directions.length +
  Object.values(filters.lineFlags).filter(Boolean).length
))
const activeRow = computed(() => rows.value.find((row) => (
  isSameClxPanelSymbol(row.symbol, props.activeSymbol)
)) || null)
const activeSymbolHint = computed(() => {
  if (!props.activeSymbol || !hasLoaded.value || activeRow.value) return ''
  if (nextCursor.value) return '当前标的不在已加载结果中；可继续加载更多或调整筛选。'
  return '当前标的不在这组筛选结果中；K 线仍保持当前标的。'
})

const currentScreeningState = () => ({
  screeningOpen: true,
  scopeId: selectedScopeId.value,
  q: filters.q,
  assetTypes: filters.assetTypes,
  modelKeys: filters.modelKeys,
  conditionKeys: filters.conditionKeys,
  directions: filters.directions,
  minModelCount: filters.minModelCount,
  lineFlags: { ...filters.lineFlags },
})

const screeningStateKey = (state) => buildClxPanelRequestKey({
  phase: 'route',
  scopeId: state.scopeId,
  payload: {
    q: state.q,
    assetTypes: state.assetTypes,
    modelKeys: state.modelKeys,
    conditionKeys: state.conditionKeys,
    directions: state.directions,
    minModelCount: state.minModelCount,
    lineFlags: state.lineFlags,
  },
})

const applyScreeningState = (state) => {
  applyingRouteState = true
  try {
    selectedScopeId.value = state.scopeId || ''
    filters.q = state.q || ''
    filters.assetTypes = Array.isArray(state.assetTypes) ? [...state.assetTypes] : []
    filters.modelKeys = Array.isArray(state.modelKeys) ? [...state.modelKeys] : []
    filters.conditionKeys = Array.isArray(state.conditionKeys) ? [...state.conditionKeys] : []
    filters.directions = Array.isArray(state.directions) ? [...state.directions] : []
    filters.minModelCount = Math.max(1, Number(state.minModelCount) || 1)
    Object.keys(filters.lineFlags).forEach((key) => {
      filters.lineFlags[key] = state.lineFlags?.[key] || ''
    })
    showMoreFilters.value = advancedFilterCount.value > 0
  } finally {
    applyingRouteState = false
  }
}

const syncRoute = async ({ forceScopeDate = false } = {}) => {
  const query = applyClxPanelScopeDate(
    buildKlineClxScreeningQuery(route.query, currentScreeningState()),
    {
      tradeDate: activeScope.value?.tradeDate,
      force: forceScopeDate,
    },
  )
  const currentKey = buildClxPanelRequestKey({ phase: 'url', payload: route.query })
  const nextKey = buildClxPanelRequestKey({ phase: 'url', payload: query })
  if (currentKey === nextKey) return
  await router.replace({ path: route.path, query })
}

const buildResultPayload = (cursor = '') => buildClxSelectionQueryPayload({
  scopeId: selectedScopeId.value,
  q: filters.q,
  assetTypes: filters.assetTypes,
  modelKeys: filters.modelKeys,
  conditionKeys: filters.conditionKeys,
  directions: filters.directions,
  minModelCount: filters.minModelCount,
  lineFlags: Object.fromEntries(Object.entries(filters.lineFlags).filter(([, value]) => value)),
  cursor,
  limit: 100,
})

const resultRequestKey = (scopeId, payload) => buildClxPanelRequestKey({
  phase: 'results',
  scopeId,
  payload,
})

const clearResults = () => {
  resultRequests.abort()
  rows.value = []
  total.value = 0
  nextCursor.value = ''
  hasLoaded.value = false
  currentResultRequestKey.value = ''
  loading.results = false
  loading.more = false
}

const loadResults = async ({ append = false } = {}) => {
  const scopeId = selectedScopeId.value
  if (!scopeId) return
  const cursor = append ? nextCursor.value : ''
  if (append && !cursor) return
  const payload = buildResultPayload(cursor)
  const requestKey = resultRequestKey(scopeId, payload)
  const token = resultRequests.begin(requestKey)
  currentResultRequestKey.value = requestKey
  const isCurrent = () => (
    resultRequests.isCurrent(token, requestKey) &&
    selectedScopeId.value === scopeId &&
    resultRequestKey(scopeId, buildResultPayload(cursor)) === requestKey
  )

  if (!append) {
    rows.value = []
    total.value = 0
    nextCursor.value = ''
    hasLoaded.value = false
  }
  pageError.value = ''
  loading.results = true
  loading.more = append

  try {
    const response = await clxDailySelectionApi.queryBatchResults(
      scopeId,
      payload,
      { signal: token.signal },
    )
    if (!isCurrent()) return
    const result = normalizeClxSelectionQuery(response)
    rows.value = append
      ? appendClxPanelRows(rows.value, result.rows)
      : result.rows
    total.value = Math.max(result.total, rows.value.length)
    nextCursor.value = result.nextCursor
    hasLoaded.value = true

    const autoRow = resolveClxPanelAutoSelection({
      rows: result.rows,
      append,
      activeSymbol: props.activeSymbol,
      requestKey,
      currentRequestKey: currentResultRequestKey.value,
      selectedRequestKey: autoSelectedRequestKey.value,
    })
    if (autoRow) {
      autoSelectedRequestKey.value = requestKey
      selectRow(autoRow)
    }
  } catch (error) {
    if (!isCurrent()) return
    if (!append) {
      rows.value = []
      total.value = 0
      nextCursor.value = ''
      hasLoaded.value = false
    }
    pageError.value = error?.response?.data?.message || error?.message || 'CLX 筛选结果加载失败'
  } finally {
    if (isCurrent()) {
      loading.results = false
      loading.more = false
    }
  }
}

const loadBootstrap = async () => {
  window.clearTimeout(queryTimer)
  clearResults()
  const requestedState = parseKlineClxScreeningQuery(route.query)
  applyScreeningState(requestedState)
  const requestKey = buildClxPanelRequestKey({
    phase: 'bootstrap',
    scopeId: requestedState.scopeId,
    payload: { routeState: requestedState },
  })
  const token = bootstrapRequests.begin(requestKey)
  const isCurrent = () => bootstrapRequests.isCurrent(token, requestKey)
  loading.bootstrap = true
  pageError.value = ''

  try {
    const [catalogPayload, batchesPayload, latestFinalPayload] = await Promise.all([
      clxDailySelectionApi.getModelCatalog({ signal: token.signal }),
      clxDailySelectionApi.getBatches(
        { limit: 30, includePartial: true },
        { signal: token.signal },
      ),
      clxDailySelectionApi.getLatestBatch(
        { includePartial: false },
        { signal: token.signal },
      ).catch(() => null),
    ])
    if (!isCurrent()) return

    catalog.value = normalizeClxCatalog(catalogPayload)
    let mergedScopes = mergeClxScopes(batchesPayload, latestFinalPayload)
    if (
      requestedState.scopeId &&
      !mergedScopes.some((scope) => scope.scopeId === requestedState.scopeId)
    ) {
      const requestedSummary = await clxDailySelectionApi.getBatchSummary(
        requestedState.scopeId,
        { signal: token.signal },
      )
      if (!isCurrent()) return
      mergedScopes = mergeClxScopes(batchesPayload, requestedSummary, latestFinalPayload)
    }
    if (!isCurrent()) return

    scopes.value = mergedScopes
    const explicitScope = scopes.value.find((scope) => scope.scopeId === requestedState.scopeId)
    const defaultFinalScope = latestFinalPayload ? pickDefaultClxScope(latestFinalPayload) : null
    selectedScopeId.value = explicitScope?.scopeId ||
      defaultFinalScope?.scopeId ||
      normalizeClxScopes(batchesPayload).find((scope) => scope.isFinal)?.scopeId ||
      ''

    await syncRoute()
    if (selectedScopeId.value) await loadResults()
  } catch (error) {
    if (!isCurrent()) return
    pageError.value = error?.response?.data?.message || error?.message || 'CLX 筛选工作台初始化失败'
  } finally {
    if (isCurrent()) {
      loading.bootstrap = false
      if (pendingResultReload && selectedScopeId.value) {
        pendingResultReload = false
        scheduleResultReload()
      }
    }
  }
}

const scheduleResultReload = () => {
  window.clearTimeout(queryTimer)
  clearResults()
  queryTimer = window.setTimeout(async () => {
    await syncRoute()
    await loadResults()
  }, 220)
}

const handleScopeChange = async () => {
  window.clearTimeout(queryTimer)
  clearResults()
  await syncRoute({ forceScopeDate: true })
  await loadResults()
}

const refreshAll = async () => {
  window.clearTimeout(queryTimer)
  await syncRoute()
  await loadBootstrap()
}

const loadMore = () => loadResults({ append: true })
const selectRow = (row) => emit('select', { row, scope: activeScope.value })
const isActiveRow = (row) => isSameClxPanelSymbol(row.symbol, props.activeSymbol)
const formatScopeOption = (scope) => [
  scope.tradeDate || scope.scopeId,
  scope.isFinal ? '完整' : '部分',
  scope.profileId || '',
].filter(Boolean).join(' · ')

const resetFilters = () => {
  filters.q = ''
  filters.assetTypes = []
  filters.modelKeys = []
  filters.conditionKeys = []
  filters.directions = []
  filters.minModelCount = 1
  Object.keys(filters.lineFlags).forEach((key) => { filters.lineFlags[key] = '' })
}

watch(
  () => [
    filters.q,
    filters.assetTypes.join(','),
    filters.modelKeys.join(','),
    filters.conditionKeys.join(','),
    filters.directions.join(','),
    filters.minModelCount,
    ...Object.values(filters.lineFlags),
  ],
  () => {
    if (applyingRouteState || !selectedScopeId.value) return
    if (loading.bootstrap) {
      pendingResultReload = true
      return
    }
    scheduleResultReload()
  },
  { flush: 'sync' },
)

watch(() => route.fullPath, async () => {
  const routeState = parseKlineClxScreeningQuery(route.query)
  const routeEntry = resolveClxPanelRouteEntry(routeState, route.query)
  if (routeEntry.shouldBootstrap) {
    if (routeEntry.resetAutoSelection) autoSelectedRequestKey.value = ''
    await loadBootstrap()
    return
  }
  if (screeningStateKey(routeState) === screeningStateKey(currentScreeningState())) return
  if (loading.bootstrap) {
    await loadBootstrap()
    return
  }
  applyScreeningState(routeState)
  if (routeState.scopeId && !scopes.value.some((scope) => scope.scopeId === routeState.scopeId)) {
    await loadBootstrap()
    return
  }
  clearResults()
  await loadResults()
})

onMounted(loadBootstrap)
onBeforeUnmount(() => {
  window.clearTimeout(queryTimer)
  bootstrapRequests.abort()
  resultRequests.abort()
})
</script>

<style scoped>
.clx-selection-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: 100%;
  overflow: hidden;
  border-right: 1px solid #d7dde6;
  background: #fff;
  color: #172033;
}

.clx-selection-panel__header,
.clx-selection-panel__results-head,
.clx-selection-panel__quick-row,
.clx-selection-panel__filter-actions,
.clx-selection-panel__status,
.clx-selection-panel__row-counts {
  display: flex;
  align-items: center;
}

.clx-selection-panel__header {
  justify-content: space-between;
  gap: 8px;
  padding: 10px 10px 8px;
  border-bottom: 1px solid #d7dde6;
}

.clx-selection-panel__header > div {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.clx-selection-panel__header strong {
  font-size: 14px;
}

.clx-selection-panel__header span,
.clx-selection-panel__muted {
  color: #6b7280;
  font-size: 11px;
}

.clx-selection-panel__controls {
  flex: 0 1 auto;
  max-height: 58%;
  overflow-y: auto;
  padding: 9px 10px;
}

.clx-selection-panel__label {
  display: block;
  margin-bottom: 4px;
  color: #4b5563;
  font-size: 11px;
  font-weight: 700;
}

.clx-selection-panel__controls > :deep(.el-select),
.clx-selection-panel__controls > :deep(.el-input) {
  width: 100%;
  margin-bottom: 8px;
}

.clx-selection-panel__status {
  flex-wrap: wrap;
  gap: 4px;
  margin: 7px 0 8px;
}

.clx-selection-panel__quick-row {
  justify-content: space-between;
  gap: 8px;
}

.clx-selection-panel__quick-row :deep(.el-radio-button__inner) {
  padding-right: 9px;
  padding-left: 9px;
}

.clx-selection-panel__min-model {
  display: flex;
  align-items: center;
  gap: 5px;
  color: #4b5563;
  font-size: 11px;
  white-space: nowrap;
}

.clx-selection-panel__min-model :deep(.el-input-number) {
  width: 76px;
}

.clx-selection-panel__filter-actions {
  justify-content: space-between;
  margin-top: 7px;
  border-top: 1px solid #eef0f3;
}

.clx-selection-panel__more-toggle {
  padding: 7px 0;
  border: 0;
  background: transparent;
  color: #1d4ed8;
  font-size: 12px;
  cursor: pointer;
}

.clx-selection-panel__more fieldset {
  min-width: 0;
  margin: 6px 0 0;
  padding: 7px 8px 8px;
  border: 1px solid #e5e7eb;
}

.clx-selection-panel__more legend {
  padding: 0 4px;
  color: #374151;
  font-size: 11px;
  font-weight: 700;
}

.clx-selection-panel__checks {
  display: flex;
  flex-direction: column;
  max-height: 112px;
  margin-top: 5px;
  overflow-y: auto;
}

.clx-selection-panel__checks :deep(.el-checkbox) {
  height: 25px;
  margin-right: 0;
}

.clx-selection-panel__line-filters label {
  display: grid;
  grid-template-columns: 78px minmax(0, 1fr);
  align-items: center;
  gap: 6px;
  margin-top: 5px;
  color: #4b5563;
  font-size: 11px;
}

.clx-selection-panel__results-head {
  flex: 0 0 auto;
  justify-content: space-between;
  min-height: 36px;
  padding: 0 10px;
  border-top: 1px solid #d7dde6;
  border-bottom: 1px solid #e5e7eb;
  font-size: 12px;
}

.clx-selection-panel__results-head span {
  color: #6b7280;
  font-size: 11px;
}

.clx-selection-panel__alert,
.clx-selection-panel__hint {
  flex: 0 0 auto;
  margin: 7px 8px 0;
  padding: 6px 8px;
  font-size: 11px;
  line-height: 1.45;
}

.clx-selection-panel__alert {
  border-left: 3px solid #dc2626;
  background: #fef2f2;
  color: #991b1b;
}

.clx-selection-panel__hint {
  border-left: 3px solid #d97706;
  background: #fff7ed;
  color: #92400e;
}

.clx-selection-panel__result-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.clx-selection-panel__empty {
  padding: 24px 14px;
  color: #6b7280;
  font-size: 12px;
  line-height: 1.6;
  text-align: center;
}

.clx-selection-panel__list {
  display: flex;
  flex-direction: column;
}

.clx-selection-panel__row {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  border-bottom: 1px solid #edf0f3;
  background: #fff;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.clx-selection-panel__row:hover {
  background: #eff6ff;
}

.clx-selection-panel__row:focus-visible {
  background: #eff6ff;
  outline: 2px solid #2563eb;
  outline-offset: -2px;
}

.clx-selection-panel__row.is-active {
  box-shadow: inset 3px 0 #2563eb;
  background: #dbeafe;
}

.clx-selection-panel__row-main {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.clx-selection-panel__row-main strong {
  overflow: hidden;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.clx-selection-panel__row-main > span,
.clx-selection-panel__models {
  color: #6b7280;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 10px;
}

.clx-selection-panel__row-counts {
  gap: 5px;
}

.clx-selection-panel__row-counts span {
  padding: 1px 5px;
  background: #eef2f7;
  color: #4b5563;
  font-size: 10px;
}

.clx-selection-panel__models {
  overflow: hidden;
  color: #1d4ed8;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.clx-selection-panel__footer {
  flex: 0 0 auto;
  padding: 8px 10px;
  border-top: 1px solid #d7dde6;
  text-align: center;
}

.clx-selection-panel__footer :deep(.el-button) {
  width: 100%;
}
</style>
