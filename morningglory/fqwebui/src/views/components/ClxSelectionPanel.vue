<template>
  <section
    class="clx-selection-panel"
    aria-label="每日选股结果筛选"
    :aria-busy="loading.bootstrap || loading.results || loading.selectAll || loading.importToTdx"
  >
    <header class="clx-selection-panel__header">
      <div>
        <strong>每日选股 · 结果筛选</strong>
        <span>改变标的集合；选中后在右侧查看 K 线</span>
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
        aria-label="每日选股结果批次"
        popper-class="clx-market-dark-popper"
        placeholder="请选择结果批次"
        :disabled="loading.bootstrap || loading.selectAll || loading.importToTdx || !scopes.length"
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
          <el-checkbox-group
            v-model="filters.modelKeys"
            class="clx-selection-panel__checks"
            aria-label="结果筛选模型"
          >
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
          <el-checkbox-group
            v-model="filters.conditionKeys"
            class="clx-selection-panel__checks"
            aria-label="结果筛选条件"
          >
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
          <el-checkbox-group v-model="filters.directions" aria-label="结果筛选方向">
            <el-checkbox value="buy">买入</el-checkbox>
            <el-checkbox value="sell">卖出</el-checkbox>
          </el-checkbox-group>
        </fieldset>

        <fieldset class="clx-selection-panel__line-filters">
          <legend>线关系</legend>
          <label v-for="line in lineFilterOptions" :key="line.key">
            <span>{{ line.label }}</span>
            <el-select
              v-model="filters.lineFlags[line.key]"
              size="small"
              :aria-label="`${line.label}关系`"
              popper-class="clx-market-dark-popper"
              placeholder="全部"
            >
              <el-option label="全部" value="" />
              <el-option label="站上" value="yes" />
              <el-option label="下方" value="no" />
              <el-option label="未知" value="unknown" />
            </el-select>
          </label>
        </fieldset>
      </div>
    </div>

    <div class="clx-selection-panel__tdx-action">
      <div class="clx-selection-panel__tdx-tools">
        <el-button
          size="small"
          :loading="loading.selectAll"
          :disabled="!canSelectAllToBasket"
          @click="selectAllCurrentFilters"
        >
          全选当前筛选结果
        </el-button>
        <el-button
          size="small"
          :disabled="!canClearBasket"
          @click="clearBasket"
        >
          清空已选
        </el-button>
      </div>
      <span class="clx-selection-panel__basket-status" role="status" aria-live="polite">
        待导入 {{ basketCount }} 只
      </span>
      <el-button
        class="clx-selection-panel__import-button"
        type="primary"
        :loading="loading.importToTdx"
        :disabled="!canImportToTdx"
        @click="importToTdx"
      >
        导入通达信（{{ basketCount }}）
      </el-button>
    </div>

    <div class="clx-selection-panel__results-head">
      <strong>标的列表</strong>
      <span v-if="(loading.bootstrap || loading.results) && rows.length" role="status" aria-live="polite">
        更新中 · 旧结果保留
      </span>
      <span v-else aria-live="polite">已加载 {{ rows.length }} / {{ total }}</span>
    </div>

    <div v-if="pageError" class="clx-selection-panel__alert" role="alert">
      <span>{{ pageError }}</span>
      <el-button size="small" link type="primary" @click="retryResults">重试</el-button>
    </div>
    <div v-if="activeSymbolHint" class="clx-selection-panel__hint" role="status">
      {{ activeSymbolHint }}
    </div>

    <div class="clx-selection-panel__result-body" :aria-busy="loading.results || loading.more">
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
      <ul v-else class="clx-selection-panel__list" aria-label="CLX 标的列表">
        <li
          v-for="row in rows"
          :key="`${row.assetType}:${row.symbol}`"
          class="clx-selection-panel__row-item"
        >
          <button
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
          <el-button
            class="clx-selection-panel__basket-toggle"
            size="small"
            :type="isRowInBasket(row) ? 'success' : 'primary'"
            :plain="!isRowInBasket(row)"
            :aria-pressed="isRowInBasket(row)"
            :aria-label="`${isRowInBasket(row) ? '取消加入通达信' : '加入通达信'} ${row.name || row.code || row.symbol}`"
            :disabled="!canEditBasket"
            @click.stop="toggleBasketRow(row)"
          >
            {{ isRowInBasket(row) ? '已加入' : '加入通达信' }}
          </el-button>
        </li>
      </ul>
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
import { ElMessage } from 'element-plus'
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
  assertClxTdxSelectionProgress,
  buildClxPanelRequestKey,
  buildClxTdxBasketKey,
  buildClxTdxSelectionPagePayload,
  buildClxTdxSelectedPayload,
  freezeClxTdxSelectionPayload,
  formatClxTdxImportErrorMessage,
  formatClxTdxImportSuccessMessage,
  isClxTdxBasketEligible,
  isClxTdxImportEnabled,
  isClxTdxSelectAllEnabled,
  isSameClxPanelSymbol,
  mergeClxTdxBasketItems,
  readClxTdxBasket,
  resolveClxPanelAutoSelection,
  resolveClxPanelRouteEntry,
  toggleClxTdxBasketItem,
  writeClxTdxBasket,
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
const selectAllRequests = createClxRequestChannel()
let selectAllLoadingOwner = null
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
const basketItems = ref([])
const loading = reactive({
  bootstrap: false,
  results: false,
  more: false,
  selectAll: false,
  importToTdx: false,
})
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
const basketCount = computed(() => basketItems.value.length)
const basketKeys = computed(() => new Set(
  basketItems.value.map((item) => buildClxTdxBasketKey(item)).filter(Boolean),
))
const basketEligible = computed(() => isClxTdxBasketEligible(activeScope.value))
const canEditBasket = computed(() => Boolean(
  basketEligible.value &&
  !loading.bootstrap &&
  !loading.selectAll &&
  !loading.importToTdx
))
const canClearBasket = computed(() => Boolean(
  basketCount.value > 0 && !loading.selectAll && !loading.importToTdx
))
const canSelectAllToBasket = computed(() => isClxTdxSelectAllEnabled({
  scope: activeScope.value,
  hasLoaded: hasLoaded.value,
  total: total.value,
  loading,
  pageError: pageError.value,
}))
const canImportToTdx = computed(() => isClxTdxImportEnabled({
  scope: activeScope.value,
  basketCount: basketCount.value,
  loading,
}))

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

const clearResults = ({ preserveExisting = false } = {}) => {
  resultRequests.abort()
  if (!preserveExisting) {
    rows.value = []
    total.value = 0
    nextCursor.value = ''
    hasLoaded.value = false
  }
  currentResultRequestKey.value = ''
  loading.results = false
  loading.more = false
}

const loadResults = async ({ append = false, preserveExisting = false } = {}) => {
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

  const retainStableRows = !append && preserveExisting && hasLoaded.value
  if (!append && !retainStableRows) {
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
    if (!append && !retainStableRows) {
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

const loadBootstrap = async ({ preserveExisting = false } = {}) => {
  window.clearTimeout(queryTimer)
  const previousScopeId = selectedScopeId.value
  const retainStableRows = preserveExisting && hasLoaded.value
  clearResults({ preserveExisting: retainStableRows })
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
    const preserveScopeResults = retainStableRows && selectedScopeId.value === previousScopeId
    if (retainStableRows && !preserveScopeResults) clearResults()
    if (selectedScopeId.value) await loadResults({ preserveExisting: preserveScopeResults })
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
  const preserveExisting = hasLoaded.value
  clearResults({ preserveExisting })
  pageError.value = ''
  loading.results = true
  queryTimer = window.setTimeout(async () => {
    await syncRoute()
    await loadResults({ preserveExisting })
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
  cancelSelectAll()
  await syncRoute()
  await loadBootstrap({ preserveExisting: true })
}

const retryResults = async () => {
  window.clearTimeout(queryTimer)
  pageError.value = ''
  await loadResults({ preserveExisting: hasLoaded.value })
}

const replaceBasket = (items) => {
  basketItems.value = mergeClxTdxBasketItems([], items)
  writeClxTdxBasket(window.sessionStorage, selectedScopeId.value, basketItems.value)
}

const isRowInBasket = (row) => basketKeys.value.has(buildClxTdxBasketKey(row))

const toggleBasketRow = (row) => {
  if (!canEditBasket.value) return
  replaceBasket(toggleClxTdxBasketItem(basketItems.value, row))
}

const clearBasket = () => {
  if (!canClearBasket.value) return
  replaceBasket([])
}

const cancelSelectAll = () => {
  selectAllRequests.abort()
  selectAllLoadingOwner = null
  loading.selectAll = false
}

const selectAllCurrentFilters = async () => {
  if (!canSelectAllToBasket.value) return
  const scopeId = selectedScopeId.value
  const expectedTotal = Number(total.value)
  const frozenPayload = freezeClxTdxSelectionPayload(buildResultPayload())
  const requestKey = buildClxPanelRequestKey({
    phase: 'tdx-select-all',
    scopeId,
    payload: frozenPayload,
  })
  const token = selectAllRequests.begin(requestKey)
  selectAllLoadingOwner = token.id
  const isCurrent = () => (
    selectAllRequests.isCurrent(token, requestKey) && selectedScopeId.value === scopeId
  )
  const seenCursors = new Set()
  let cursor = ''
  let selectedItems = []
  loading.selectAll = true

  try {
    while (true) {
      const payload = buildClxTdxSelectionPagePayload(frozenPayload, cursor)
      const response = await clxDailySelectionApi.queryBatchResults(
        scopeId,
        payload,
        { signal: token.signal },
      )
      if (!isCurrent()) return
      const result = normalizeClxSelectionQuery(response)
      selectedItems = mergeClxTdxBasketItems(selectedItems, result.rows)
      const next = result.nextCursor
      assertClxTdxSelectionProgress({
        expectedTotal,
        responseTotal: result.total,
        selectedCount: selectedItems.length,
        nextCursor: next,
      })
      if (!next) break
      if (seenCursors.has(next)) throw new Error('全选结果游标重复，已停止收集')
      seenCursors.add(next)
      cursor = next
    }

    replaceBasket(mergeClxTdxBasketItems(basketItems.value, selectedItems))
    ElMessage.success(`已加入当前筛选结果 ${selectedItems.length} 只`)
  } catch (error) {
    if (!isCurrent()) return
    ElMessage.error(error?.response?.data?.message || error?.message || '全选当前筛选结果失败')
  } finally {
    if (selectAllLoadingOwner === token.id) {
      selectAllLoadingOwner = null
      loading.selectAll = false
    }
  }
}

const importToTdx = async () => {
  if (!canImportToTdx.value) return
  const payload = buildClxTdxSelectedPayload(basketItems.value)
  if (!payload.items.length) return
  loading.importToTdx = true
  try {
    const response = await clxDailySelectionApi.syncSelectedBatchResultsToTdx(
      selectedScopeId.value,
      payload,
    )
    const writtenCount = Number(response?.written_count)
    if (!Number.isInteger(writtenCount) || writtenCount <= 0) {
      throw new Error('导入响应缺少有效 written_count')
    }
    ElMessage.success(formatClxTdxImportSuccessMessage(writtenCount))
  } catch (error) {
    ElMessage.error(formatClxTdxImportErrorMessage(
      error?.response?.data?.message || error?.message,
    ))
  } finally {
    loading.importToTdx = false
  }
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

watch(
  selectedScopeId,
  (scopeId, previousScopeId) => {
    if (scopeId !== previousScopeId) cancelSelectAll()
    basketItems.value = readClxTdxBasket(window.sessionStorage, scopeId)
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
  const previousScopeId = selectedScopeId.value
  const preserveExisting = routeState.scopeId === previousScopeId && hasLoaded.value
  applyScreeningState(routeState)
  if (routeState.scopeId && !scopes.value.some((scope) => scope.scopeId === routeState.scopeId)) {
    await loadBootstrap()
    return
  }
  clearResults({ preserveExisting })
  await loadResults({ preserveExisting })
})

onMounted(loadBootstrap)
onBeforeUnmount(() => {
  window.clearTimeout(queryTimer)
  bootstrapRequests.abort()
  resultRequests.abort()
  cancelSelectAll()
})
</script>

<style scoped>
.clx-selection-panel {
  --clx-surface-panel: #12161c;
  --clx-surface-raised: rgba(30, 41, 59, 0.72);
  --clx-surface-hover: rgba(51, 65, 85, 0.68);
  --clx-border: rgba(148, 163, 184, 0.2);
  --clx-border-subtle: rgba(148, 163, 184, 0.12);
  --clx-text-primary: #f8fafc;
  --clx-text-secondary: #cbd5e1;
  --clx-text-muted: #94a3b8;
  --clx-accent: #60a5fa;
  --clx-accent-strong: #93c5fd;
  --clx-selected: rgba(30, 64, 175, 0.28);
  --clx-focus: #93c5fd;
  --el-color-primary: var(--clx-accent, #60a5fa);
  --el-bg-color: var(--clx-surface-raised, rgba(30, 41, 59, 0.72));
  --el-bg-color-overlay: var(--clx-surface-raised, rgba(30, 41, 59, 0.72));
  --el-fill-color-blank: var(--clx-surface-raised, rgba(30, 41, 59, 0.72));
  --el-fill-color-light: var(--clx-surface-hover, rgba(51, 65, 85, 0.68));
  --el-border-color: var(--clx-border, rgba(148, 163, 184, 0.2));
  --el-border-color-light: var(--clx-border, rgba(148, 163, 184, 0.2));
  --el-text-color-primary: var(--clx-text-primary, #f8fafc);
  --el-text-color-regular: var(--clx-text-secondary, #cbd5e1);
  --el-text-color-placeholder: var(--clx-text-muted, #94a3b8);
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: 100%;
  overflow: hidden;
  border-right: 1px solid var(--clx-border, rgba(148, 163, 184, 0.2));
  background: var(--clx-surface-panel, #12161c);
  color: var(--clx-text-primary, #f8fafc);
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
  border-bottom: 1px solid var(--clx-border, rgba(148, 163, 184, 0.2));
  background: var(--clx-surface-raised, rgba(30, 41, 59, 0.72));
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
  color: var(--clx-text-muted, #94a3b8);
  font-size: 11px;
}

.clx-selection-panel__controls {
  flex: 0 1 auto;
  max-height: 58%;
  overflow-y: auto;
  padding: 9px 10px;
}

.clx-selection-panel__tdx-action {
  display: grid;
  gap: 7px;
  flex: 0 0 auto;
  padding: 0 10px 9px;
}

.clx-selection-panel__tdx-tools {
  display: flex;
  gap: 6px;
}

.clx-selection-panel__tdx-tools :deep(.el-button) {
  flex: 1;
  min-width: 0;
  margin-left: 0;
}

.clx-selection-panel__basket-status {
  color: var(--clx-text-muted, #94a3b8);
  font-size: 11px;
  text-align: center;
}

.clx-selection-panel__import-button {
  width: 100%;
}

.clx-selection-panel__label {
  display: block;
  margin-bottom: 4px;
  color: var(--clx-text-secondary, #cbd5e1);
  font-size: 11px;
  font-weight: 700;
}

.clx-selection-panel__controls > :deep(.el-select),
.clx-selection-panel__controls > :deep(.el-input) {
  width: 100%;
  margin-bottom: 8px;
}

.clx-selection-panel :deep(.el-input__wrapper),
.clx-selection-panel :deep(.el-select__wrapper) {
  background: var(--clx-surface-raised, rgba(30, 41, 59, 0.72));
  box-shadow: 0 0 0 1px var(--clx-border, rgba(148, 163, 184, 0.2)) inset;
}

.clx-selection-panel :deep(.el-input__wrapper:hover),
.clx-selection-panel :deep(.el-select__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--clx-accent, #60a5fa) inset;
}

.clx-selection-panel :deep(.el-input__wrapper:focus-within),
.clx-selection-panel :deep(.el-input__wrapper.is-focus),
.clx-selection-panel :deep(.el-select__wrapper.is-focused) {
  box-shadow: 0 0 0 2px var(--clx-focus, #93c5fd) inset;
}

.clx-selection-panel :deep(.el-input__inner),
.clx-selection-panel :deep(.el-select__selected-item),
.clx-selection-panel :deep(.el-checkbox__label) {
  color: var(--clx-text-secondary, #cbd5e1);
}

.clx-selection-panel :deep(.el-input-number__decrease),
.clx-selection-panel :deep(.el-input-number__increase) {
  border-color: var(--clx-border, rgba(148, 163, 184, 0.2));
  background: var(--clx-surface-hover, rgba(51, 65, 85, 0.68));
  color: var(--clx-text-secondary, #cbd5e1);
}

.clx-selection-panel :deep(.el-radio-button__inner) {
  border-color: var(--clx-border, rgba(148, 163, 184, 0.2));
  background: var(--clx-surface-raised, rgba(30, 41, 59, 0.72));
  color: var(--clx-text-secondary, #cbd5e1);
}

.clx-selection-panel :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  border-color: var(--clx-accent, #60a5fa);
  background: var(--clx-selected, rgba(30, 64, 175, 0.28));
  color: var(--clx-accent-strong, #93c5fd);
  box-shadow: -1px 0 0 0 var(--clx-accent, #60a5fa);
}

.clx-selection-panel :deep(.el-button:not(.el-button--primary)) {
  border-color: var(--clx-border, rgba(148, 163, 184, 0.2));
  background: var(--clx-surface-raised, rgba(30, 41, 59, 0.72));
  color: var(--clx-text-secondary, #cbd5e1);
}

.clx-selection-panel :deep(.el-button:not(.el-button--primary):not(.is-disabled):hover) {
  border-color: var(--clx-accent, #60a5fa);
  background: var(--clx-surface-hover, rgba(51, 65, 85, 0.68));
  color: var(--clx-text-primary, #f8fafc);
}

.clx-selection-panel :deep(.el-button:not(.is-disabled):focus-visible),
.clx-selection-panel :deep(.el-checkbox__input.is-focus .el-checkbox__inner),
.clx-selection-panel :deep(.el-radio-button__original-radio:focus-visible + .el-radio-button__inner) {
  outline: 2px solid var(--clx-focus, #93c5fd);
  outline-offset: 2px;
}

.clx-selection-panel :deep(.el-button.is-disabled) {
  border-color: var(--clx-border, rgba(148, 163, 184, 0.2));
  background: color-mix(in srgb, var(--clx-surface-raised, rgba(30, 41, 59, 0.72)) 70%, transparent);
  color: var(--clx-text-muted, #94a3b8);
}

.clx-selection-panel :deep(.workbench-summary-chip) {
  border-color: var(--clx-border, rgba(148, 163, 184, 0.2));
  background: var(--clx-surface-hover, rgba(51, 65, 85, 0.68));
  color: var(--clx-text-secondary, #cbd5e1);
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
  color: var(--clx-text-secondary, #cbd5e1);
  font-size: 11px;
  white-space: nowrap;
}

.clx-selection-panel__min-model :deep(.el-input-number) {
  width: 76px;
}

.clx-selection-panel__filter-actions {
  justify-content: space-between;
  margin-top: 7px;
  border-top: 1px solid var(--clx-border-subtle, rgba(148, 163, 184, 0.12));
}

.clx-selection-panel__more-toggle {
  padding: 7px 0;
  border: 0;
  background: transparent;
  color: var(--clx-accent-strong, #93c5fd);
  font-size: 12px;
  cursor: pointer;
}

.clx-selection-panel__more fieldset {
  min-width: 0;
  margin: 6px 0 0;
  padding: 7px 8px 8px;
  border: 1px solid var(--clx-border, rgba(148, 163, 184, 0.2));
  background: var(--clx-surface-raised, rgba(30, 41, 59, 0.72));
}

.clx-selection-panel__more legend {
  padding: 0 4px;
  color: var(--clx-text-secondary, #cbd5e1);
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
  color: var(--clx-text-secondary, #cbd5e1);
  font-size: 11px;
}

.clx-selection-panel__results-head {
  flex: 0 0 auto;
  justify-content: space-between;
  min-height: 36px;
  padding: 0 10px;
  border-top: 1px solid var(--clx-border, rgba(148, 163, 184, 0.2));
  border-bottom: 1px solid var(--clx-border, rgba(148, 163, 184, 0.2));
  font-size: 12px;
}

.clx-selection-panel__results-head span {
  color: var(--clx-text-muted, #94a3b8);
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
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  border-left: 3px solid #dc2626;
  background: rgba(127, 29, 29, 0.24);
  color: #fecaca;
}

.clx-selection-panel__hint {
  border-left: 3px solid #d97706;
  background: rgba(146, 64, 14, 0.22);
  color: #fed7aa;
}

.clx-selection-panel__result-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.clx-selection-panel__empty {
  padding: 24px 14px;
  color: var(--clx-text-muted, #94a3b8);
  font-size: 12px;
  line-height: 1.6;
  text-align: center;
}

.clx-selection-panel__list {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}

.clx-selection-panel__row-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  border-bottom: 1px solid var(--clx-border-subtle, rgba(148, 163, 184, 0.12));
  background: var(--clx-surface-panel, #12161c);
}

.clx-selection-panel__row {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.clx-selection-panel__row:hover {
  background: var(--clx-surface-hover, rgba(51, 65, 85, 0.68));
}

.clx-selection-panel__row:focus-visible {
  background: var(--clx-surface-hover, rgba(51, 65, 85, 0.68));
  outline: 2px solid var(--clx-focus, #93c5fd);
  outline-offset: -2px;
}

.clx-selection-panel__row.is-active {
  box-shadow: inset 3px 0 var(--clx-accent, #60a5fa);
  background: var(--clx-selected, rgba(30, 64, 175, 0.28));
}

.clx-selection-panel__basket-toggle {
  min-width: 74px;
  margin: 0 8px 0 4px;
}

.clx-selection-panel :deep(.clx-selection-panel__basket-toggle[aria-pressed='true']) {
  border-color: rgba(74, 222, 128, 0.55);
  background: rgba(22, 101, 52, 0.72);
  color: #dcfce7;
}

.clx-selection-panel :deep(.clx-selection-panel__basket-toggle.el-button--success:hover) {
  border-color: rgba(134, 239, 172, 0.72);
  background: rgba(21, 128, 61, 0.78);
  color: #f0fdf4;
}

.clx-selection-panel__basket-toggle:focus-visible {
  outline: 2px solid var(--clx-focus, #93c5fd);
  outline-offset: 2px;
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
  color: var(--clx-text-muted, #94a3b8);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 10px;
}

.clx-selection-panel__row-counts {
  gap: 5px;
}

.clx-selection-panel__row-counts span {
  padding: 1px 5px;
  background: var(--clx-surface-raised, rgba(30, 41, 59, 0.72));
  color: var(--clx-text-secondary, #cbd5e1);
  font-size: 10px;
}

.clx-selection-panel__models {
  overflow: hidden;
  color: var(--clx-accent-strong, #93c5fd);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.clx-selection-panel__footer {
  flex: 0 0 auto;
  padding: 8px 10px;
  border-top: 1px solid var(--clx-border, rgba(148, 163, 184, 0.2));
  text-align: center;
}

.clx-selection-panel__footer :deep(.el-button) {
  width: 100%;
}

:global(.clx-market-dark-popper.el-popper) {
  --el-bg-color-overlay: #1e293b;
  --el-fill-color-light: #334155;
  --el-text-color-regular: #cbd5e1;
  --el-text-color-primary: #f8fafc;
  --el-border-color-light: rgba(148, 163, 184, 0.24);
  border-color: rgba(148, 163, 184, 0.24);
  background: #1e293b;
  color: #cbd5e1;
}

:global(.clx-market-dark-popper .el-select-dropdown) {
  background: #1e293b;
}

:global(.clx-market-dark-popper .el-select-dropdown__item) {
  color: #cbd5e1;
}

:global(.clx-market-dark-popper .el-select-dropdown__item.is-hovering),
:global(.clx-market-dark-popper .el-select-dropdown__item:hover) {
  background: #334155;
  color: #f8fafc;
}

:global(.clx-market-dark-popper .el-select-dropdown__item.is-selected) {
  color: #93c5fd;
}

:global(.clx-market-dark-popper .el-popper__arrow::before) {
  border-color: rgba(148, 163, 184, 0.24);
  background: #1e293b;
}
</style>
