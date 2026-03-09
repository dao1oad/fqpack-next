<template>
  <div class="shouban30-page">
    <MyHeader />
    <div class="shouban30-page-body">
      <div class="shouban30-toolbar">
        <div class="toolbar-title">
          <div class="page-title">30天首板</div>
          <div class="page-meta">
            <span>as_of_date {{ resolvedAsOfDate || '-' }}</span>
            <span>/</span>
            <span>标的窗口 {{ stockWindowDays }} 日</span>
            <span v-if="windowRangeLabel">/ {{ windowRangeLabel }}</span>
          </div>
        </div>
      </div>

      <div class="shouban30-grid">
        <section class="panel-card">
          <div class="panel-card-header">
            <span>首板板块</span>
            <span class="muted">{{ currentStats.plate_count }}</span>
          </div>

          <div class="panel-controls">
            <el-tabs
              :model-value="activeViewProvider"
              class="provider-tabs"
              @tab-change="handleProviderChange"
            >
              <el-tab-pane
                v-for="option in VIEW_PROVIDER_OPTIONS"
                :key="option.name"
                :name="option.name"
              >
                <template #label>
                  <div class="provider-tab-label">
                    <span>{{ option.label }}</span>
                    <span class="tab-meta">{{ formatTabStats(statsByView[option.name]) }}</span>
                  </div>
                </template>
              </el-tab-pane>
            </el-tabs>

            <el-button-group class="window-buttons">
              <el-button
                v-for="option in SHOUBAN30_STOCK_WINDOW_OPTIONS"
                :key="option"
                size="small"
                :type="stockWindowDays === option ? 'primary' : ''"
                @click="handleStockWindowChange(option)"
              >
                {{ option }}日
              </el-button>
            </el-button-group>

            <div class="panel-summary">
              <span>{{ activeViewLabel }}</span>
              <span>{{ currentStats.plate_count }} 个热门板块</span>
              <span>/</span>
              <span>{{ currentStats.stock_count }} 个热门个股</span>
            </div>
            <div class="panel-summary panel-summary-chanlun">
              <span>原始候选 {{ currentChanlunStats.candidate_total }}</span>
              <span>/</span>
              <span>缠论通过 {{ currentChanlunStats.passed_total }}</span>
              <span>/</span>
              <span>未通过/不可用 {{ currentChanlunStats.failed_total }}</span>
            </div>
          </div>

          <el-alert
            v-if="platesError"
            class="panel-alert"
            type="error"
            :closable="false"
            :title="platesError"
          />

          <div class="panel-table">
            <el-table
              v-loading="platesLoading"
              :data="currentPlates"
              size="small"
              border
              height="100%"
              empty-text="暂无首板板块"
              :row-class-name="plateRowClassName"
              @row-click="handlePlateRowClick"
            >
              <el-table-column prop="plate_name" label="板块" min-width="120" show-overflow-tooltip />
              <el-table-column prop="appear_days_30" label="30天" width="70" />
              <el-table-column prop="last_up_date" label="最后上板" width="110">
                <template #default="{ row }">
                  <span class="mono">{{ row.last_up_date || row.seg_to || '-' }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="reason_text" label="板块理由" min-width="220" show-overflow-tooltip />
              <el-table-column :label="plateCountLabel" prop="stocks_count" width="92" />
            </el-table>
          </div>
        </section>

        <section class="panel-card">
          <div class="panel-card-header">
            <span>热点标的</span>
            <span class="muted">{{ currentStocks.length }}</span>
          </div>
          <el-alert
            v-if="stocksError"
            class="panel-alert"
            type="error"
            :closable="false"
            :title="stocksError"
          />
          <div class="panel-table">
            <el-table
              v-loading="stocksLoading"
              :data="currentStocks"
              size="small"
              border
              height="100%"
              empty-text="请先选择左侧板块"
              :row-class-name="stockRowClassName"
              @row-click="handleStockRowClick"
            >
              <el-table-column prop="code6" label="代码" width="90">
                <template #default="{ row }">
                  <span class="mono">{{ row.code6 }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="name" label="名称" min-width="110" show-overflow-tooltip />
              <el-table-column :label="stockHitCountLabel" prop="hit_count_window" width="88" />
              <el-table-column prop="latest_trade_date" label="最近上榜" width="108">
                <template #default="{ row }">
                  <span class="mono">{{ row.latest_trade_date || '-' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="高级段倍数" min-width="102">
                <template #default="{ row }">
                  <span class="mono">{{ formatChanlunMetric(row.chanlun_higher_multiple) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="段倍数" min-width="92">
                <template #default="{ row }">
                  <span class="mono">{{ formatChanlunMetric(row.chanlun_segment_multiple) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="笔涨幅%" min-width="92">
                <template #default="{ row }">
                  <span class="mono">{{ formatChanlunMetric(row.chanlun_bi_gain_percent) }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="latest_reason" label="最近理由" min-width="180" show-overflow-tooltip />
            </el-table>
          </div>
        </section>

        <section class="panel-card">
          <div class="panel-card-header">
            <span>标的详情</span>
            <span class="muted" v-if="selectedStock">
              <span class="mono">{{ selectedStock.code6 }}</span>
              <span> {{ selectedStock.name }}</span>
            </span>
          </div>
          <div class="detail-meta">
            <span>历史全量热门理由</span>
            <span v-if="stockReasons.length">/ {{ stockReasons.length }} 条</span>
          </div>
          <el-alert
            v-if="stockReasonsError"
            class="panel-alert"
            type="error"
            :closable="false"
            :title="stockReasonsError"
          />
          <div class="panel-table">
            <el-table
              v-loading="stockReasonsLoading"
              :data="stockReasons"
              size="small"
              border
              height="100%"
              empty-text="请先选择中间标的"
            >
              <el-table-column prop="date" label="日期" width="108">
                <template #default="{ row }">
                  <span class="mono">{{ row.date || '-' }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="time" label="时间" width="70">
                <template #default="{ row }">
                  <span class="mono">{{ row.time || '-' }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="provider" label="来源" width="76">
                <template #default="{ row }">
                  {{ formatProvider(row.provider) }}
                </template>
              </el-table-column>
              <el-table-column prop="plate_name" label="板块" width="140" show-overflow-tooltip />
              <el-table-column label="理由" min-width="240" show-overflow-tooltip>
                <template #default="{ row }">
                  <div>{{ row.stock_reason || '-' }}</div>
                  <div class="muted reason-sub">{{ row.plate_reason || '-' }}</div>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { getGanttStockReasons } from '@/api/ganttApi'
import {
  SHOUBAN30_STOCK_WINDOW_OPTIONS,
  getShouban30Plates,
  getShouban30Stocks,
  normalizeShouban30StockWindowDays,
} from '@/api/ganttShouban30'

import MyHeader from './MyHeader.vue'
import {
  aggregatePlateRows,
  aggregateStockRows,
  buildChanlunFilterStats,
  buildViewStats,
  filterLoadedPlateRows,
  formatProviderLabel,
  loadProvidersIndependently,
  normalizeSourcePlateRefs,
  sortStockRows,
} from './shouban30Aggregation.mjs'

const VIEW_PROVIDER_OPTIONS = [
  { name: 'xgb', label: 'XGB' },
  { name: 'jygs', label: 'JYGS' },
  { name: 'agg', label: '聚合' },
]
const SOURCE_PROVIDERS = ['xgb', 'jygs']
const EMPTY_STATS = Object.freeze({ plate_count: 0, stock_count: 0 })
const EMPTY_CHANLUN_STATS = Object.freeze({
  candidate_total: 0,
  passed_total: 0,
  failed_total: 0,
})
const SHOUBAN30_CHANLUN_SNAPSHOT_PENDING_MESSAGE = '首板缠论快照未构建完成'
const SHOUBAN30_CHANLUN_SNAPSHOT_NOT_READY_ERROR = 'shouban30 chanlun snapshot not ready'

const route = useRoute()
const router = useRouter()

const sourcePlatesByProvider = ref({ xgb: [], jygs: [] })
const sourceMetaByProvider = ref({ xgb: {}, jygs: {} })
const sourceStocksByProvider = ref({ xgb: {}, jygs: {} })
const stockLoadErrorProviders = ref([])

const stockReasons = ref([])

const platesLoading = ref(false)
const stocksLoading = ref(false)
const stockReasonsLoading = ref(false)

const platesError = ref('')
const stocksError = ref('')
const stockReasonsError = ref('')

const selectedPlateViewKey = ref('')
const selectedStockCode6 = ref('')

let viewRequestId = 0
let reasonRequestId = 0

const toText = (value) => String(value || '').trim()

const normalizeList = (value) => {
  return Array.isArray(value) ? value : []
}

const flattenStockRowsByPlate = (stockRowsByPlate) => {
  return Object.values(stockRowsByPlate || {}).flatMap((rows) => normalizeList(rows))
}

const normalizeViewProvider = (provider) => {
  const value = toText(provider).toLowerCase()
  return VIEW_PROVIDER_OPTIONS.some((item) => item.name === value) ? value : 'xgb'
}

const unwrapApiData = (response) => {
  const payload = response?.data
  return payload && typeof payload === 'object' ? payload : {}
}

const normalizeShouban30ErrorMessage = (message, fallback) => {
  const text = toText(message || fallback)
  if (!text) return fallback
  if (text === SHOUBAN30_CHANLUN_SNAPSHOT_NOT_READY_ERROR) {
    return SHOUBAN30_CHANLUN_SNAPSHOT_PENDING_MESSAGE
  }
  return text
}

const getErrorMessage = (error, fallback) => {
  return normalizeShouban30ErrorMessage(
    error?.response?.data?.message || error?.message,
    fallback,
  )
}

const formatLoadErrors = ({ errors = [], targetLabel = '数据' } = {}) => {
  const messages = normalizeList(errors)
    .map(({ provider, error }) => {
      const providerLabel = formatProviderLabel(provider)
      const reason = getErrorMessage(error, '未知错误')
      return `${providerLabel}${targetLabel}加载失败: ${reason}`
    })
    .filter(Boolean)
  return messages.join('；')
}

const formatChanlunMetric = (value) => {
  if (value == null || value === '') return '-'
  const number = Number(value)
  if (!Number.isFinite(number)) return '-'
  return number.toFixed(2)
}

const activeViewProvider = computed(() => normalizeViewProvider(route.query.p))
const stockWindowDays = computed(() => {
  return normalizeShouban30StockWindowDays(route.query.stock_window_days)
})
const requestedAsOfDate = computed(() => toText(route.query.as_of_date))

const updateQuery = (patch = {}) => {
  const nextQuery = {
    ...(route.query || {}),
    ...patch,
  }
  Object.keys(nextQuery).forEach((key) => {
    const value = nextQuery[key]
    if (value === undefined || value === null || value === '') {
      delete nextQuery[key]
    }
  })
  router.replace({
    name: 'gantt-shouban30',
    query: nextQuery,
  }).catch(() => {})
}

const xgbPlates = computed(() => filterLoadedPlateRows({
  plates: sourcePlatesByProvider.value.xgb,
  hasLoadError: stockLoadErrorProviders.value.includes('xgb'),
}))
const jygsPlates = computed(() => filterLoadedPlateRows({
  plates: sourcePlatesByProvider.value.jygs,
  hasLoadError: stockLoadErrorProviders.value.includes('jygs'),
}))
const aggPlates = computed(() => {
  return aggregatePlateRows({
    xgbPlates: xgbPlates.value,
    jygsPlates: jygsPlates.value,
    stockRowsByProvider: sourceStocksByProvider.value,
  })
})

const platesByView = computed(() => {
  return {
    xgb: xgbPlates.value,
    jygs: jygsPlates.value,
    agg: aggPlates.value,
  }
})

const getSourceStockRows = (provider, plateKey) => {
  return normalizeList(sourceStocksByProvider.value?.[provider]?.[plateKey])
}

const getViewStocksForPlate = (plate) => {
  if (!plate) return []
  if (toText(plate.provider) === 'agg') {
    const sourceRows = normalizeSourcePlateRefs(
      plate.source_plate_refs || plate.source_plate_keys,
    ).flatMap(({ provider, plate_key: plateKey }) => {
      return getSourceStockRows(provider, plateKey)
    })
    return aggregateStockRows(sourceRows)
  }
  return sortStockRows(getSourceStockRows(plate.provider, plate.plate_key))
}

const aggregateStockRowsByPlate = computed(() => {
  return Object.fromEntries(
    aggPlates.value.map((plate) => [plate.view_key, getViewStocksForPlate(plate)]),
  )
})

const statsByView = computed(() => {
  return {
    xgb: buildViewStats({
      plates: xgbPlates.value,
      stockRowsByPlate: sourceStocksByProvider.value.xgb,
    }),
    jygs: buildViewStats({
      plates: jygsPlates.value,
      stockRowsByPlate: sourceStocksByProvider.value.jygs,
    }),
    agg: buildViewStats({
      plates: aggPlates.value,
      stockRowsByPlate: aggregateStockRowsByPlate.value,
    }),
  }
})

const chanlunStatsByView = computed(() => {
  const xgbRows = flattenStockRowsByPlate(sourceStocksByProvider.value.xgb)
  const jygsRows = flattenStockRowsByPlate(sourceStocksByProvider.value.jygs)
  return {
    xgb: buildChanlunFilterStats(xgbRows),
    jygs: buildChanlunFilterStats(jygsRows),
    agg: buildChanlunFilterStats([...xgbRows, ...jygsRows]),
  }
})

const currentPlates = computed(() => platesByView.value[activeViewProvider.value] || [])
const currentStats = computed(() => statsByView.value[activeViewProvider.value] || EMPTY_STATS)
const currentChanlunStats = computed(() => {
  return chanlunStatsByView.value[activeViewProvider.value] || EMPTY_CHANLUN_STATS
})

const selectedPlate = computed(() => {
  return currentPlates.value.find((item) => item.view_key === selectedPlateViewKey.value) || null
})

const currentStocks = computed(() => getViewStocksForPlate(selectedPlate.value))

const selectedStock = computed(() => {
  return currentStocks.value.find((item) => item.code6 === selectedStockCode6.value) || null
})

const resolvedAsOfDate = computed(() => {
  if (activeViewProvider.value === 'agg') {
    return SOURCE_PROVIDERS
      .map((provider) => toText(sourceMetaByProvider.value?.[provider]?.as_of_date))
      .filter(Boolean)
      .sort()
      .at(-1) || ''
  }
  return toText(sourceMetaByProvider.value?.[activeViewProvider.value]?.as_of_date)
})

const windowRangeLabel = computed(() => {
  const samplePlate = currentPlates.value[0]
    || xgbPlates.value[0]
    || jygsPlates.value[0]
  const start = toText(samplePlate?.stock_window_from)
  const end = toText(samplePlate?.stock_window_to || resolvedAsOfDate.value)
  if (!start || !end) return ''
  return `${start} ~ ${end}`
})

const activeViewLabel = computed(() => {
  return VIEW_PROVIDER_OPTIONS.find((item) => item.name === activeViewProvider.value)?.label || 'XGB'
})

const plateCountLabel = computed(() => '通过数')
const stockHitCountLabel = computed(() => `${stockWindowDays.value}次`)

const formatTabStats = (stats) => {
  const target = stats || EMPTY_STATS
  return `${target.plate_count}板 / ${target.stock_count}股`
}

const formatProvider = (value) => formatProviderLabel(value)

const clearDetailState = () => {
  reasonRequestId += 1
  selectedStockCode6.value = ''
  stockReasons.value = []
  stockReasonsError.value = ''
  stockReasonsLoading.value = false
}

const loadStockReasons = async (code6) => {
  const targetCode6 = toText(code6)
  stockReasons.value = []
  stockReasonsError.value = ''
  if (!targetCode6) return

  const requestId = ++reasonRequestId
  stockReasonsLoading.value = true
  try {
    const response = await getGanttStockReasons({
      code6: targetCode6,
      provider: 'all',
      limit: 0,
    })
    if (requestId !== reasonRequestId) return
    const payload = unwrapApiData(response)
    stockReasons.value = normalizeList(payload.items)
  } catch (error) {
    if (requestId !== reasonRequestId) return
    stockReasonsError.value = getErrorMessage(error, '加载标的详情失败')
  } finally {
    if (requestId === reasonRequestId) {
      stockReasonsLoading.value = false
    }
  }
}

const fetchProviderPlates = async (provider) => {
  const response = await getShouban30Plates({
    provider,
    stockWindowDays: stockWindowDays.value,
    asOfDate: requestedAsOfDate.value || undefined,
  })
  const payload = unwrapApiData(response)
  return {
    items: normalizeList(payload.items),
    meta: payload.meta || {},
  }
}

const fetchProviderStocksByPlate = async (provider, plates, asOfDate) => {
  const entries = await Promise.all(
    normalizeList(plates).map(async (plate) => {
      const plateKey = toText(plate?.plate_key)
      if (!plateKey) return [plateKey, []]
      const response = await getShouban30Stocks({
        provider,
        plateKey,
        stockWindowDays: stockWindowDays.value,
        asOfDate: asOfDate || requestedAsOfDate.value || undefined,
      })
      const payload = unwrapApiData(response)
      return [plateKey, normalizeList(payload.items)]
    }),
  )
  return Object.fromEntries(entries.filter(([plateKey]) => plateKey))
}

const loadViewData = async () => {
  const requestId = ++viewRequestId
  platesLoading.value = true
  stocksLoading.value = true
  platesError.value = ''
  stocksError.value = ''
  clearDetailState()
  selectedPlateViewKey.value = ''
  sourcePlatesByProvider.value = { xgb: [], jygs: [] }
  sourceMetaByProvider.value = { xgb: {}, jygs: {} }
  sourceStocksByProvider.value = { xgb: {}, jygs: {} }
  stockLoadErrorProviders.value = []

  try {
    const plateLoad = await loadProvidersIndependently({
      providers: SOURCE_PROVIDERS,
      fetcher: fetchProviderPlates,
      emptyValueFactory: () => ({ items: [], meta: {} }),
    })
    if (requestId !== viewRequestId) return

    const nextPlates = Object.fromEntries(
      SOURCE_PROVIDERS.map((provider) => [
        provider,
        normalizeList(plateLoad.valuesByProvider?.[provider]?.items),
      ]),
    )
    const nextMeta = Object.fromEntries(
      SOURCE_PROVIDERS.map((provider) => [
        provider,
        plateLoad.valuesByProvider?.[provider]?.meta || {},
      ]),
    )

    const stockLoad = await loadProvidersIndependently({
      providers: SOURCE_PROVIDERS,
      fetcher: (provider) => {
        return fetchProviderStocksByPlate(
          provider,
          nextPlates[provider],
          toText(nextMeta[provider]?.as_of_date),
        )
      },
      emptyValueFactory: () => ({}),
    })
    if (requestId !== viewRequestId) return

    sourcePlatesByProvider.value = nextPlates
    sourceMetaByProvider.value = nextMeta
    sourceStocksByProvider.value = Object.fromEntries(
      SOURCE_PROVIDERS.map((provider) => [
        provider,
        stockLoad.valuesByProvider?.[provider] || {},
      ]),
    )
    stockLoadErrorProviders.value = normalizeList(stockLoad.errors).map(({ provider }) => toText(provider))
    platesError.value = formatLoadErrors({
      errors: plateLoad.errors,
      targetLabel: '首板板块',
    })
    stocksError.value = formatLoadErrors({
      errors: stockLoad.errors,
      targetLabel: '热点标的',
    })
  } catch (error) {
    if (requestId !== viewRequestId) return
    const message = getErrorMessage(error, '加载首板数据失败')
    platesError.value = message
    stocksError.value = message
  } finally {
    if (requestId === viewRequestId) {
      platesLoading.value = false
      stocksLoading.value = false
    }
  }
}

const handleProviderChange = (value) => {
  updateQuery({
    p: normalizeViewProvider(value),
    stock_window_days: String(stockWindowDays.value),
    as_of_date: requestedAsOfDate.value || undefined,
  })
}

const handleStockWindowChange = (value) => {
  updateQuery({
    p: activeViewProvider.value,
    stock_window_days: String(normalizeShouban30StockWindowDays(value)),
    as_of_date: requestedAsOfDate.value || undefined,
  })
}

const handlePlateRowClick = (row) => {
  selectedPlateViewKey.value = toText(row?.view_key)
}

const handleStockRowClick = (row) => {
  selectedStockCode6.value = toText(row?.code6)
}

const plateRowClassName = ({ row }) => {
  return selectedPlateViewKey.value && toText(row?.view_key) === selectedPlateViewKey.value
    ? 'is-selected-row'
    : ''
}

const stockRowClassName = ({ row }) => {
  return selectedStockCode6.value && toText(row?.code6) === selectedStockCode6.value
    ? 'is-selected-row'
    : ''
}

watch(
  () => [activeViewProvider.value, stockWindowDays.value, requestedAsOfDate.value],
  () => {
    loadViewData()
  },
  { immediate: true },
)

watch(
  currentPlates,
  (rows) => {
    if (!rows.length) {
      selectedPlateViewKey.value = ''
      clearDetailState()
      return
    }
    if (!rows.some((item) => item.view_key === selectedPlateViewKey.value)) {
      selectedPlateViewKey.value = toText(rows[0]?.view_key)
    }
  },
  { immediate: true },
)

watch(
  currentStocks,
  (rows) => {
    if (!rows.length) {
      clearDetailState()
      return
    }
    if (!rows.some((item) => item.code6 === selectedStockCode6.value)) {
      selectedStockCode6.value = toText(rows[0]?.code6)
    }
  },
  { immediate: true },
)

watch(
  () => selectedStockCode6.value,
  (code6) => {
    const normalized = toText(code6)
    if (!normalized) {
      stockReasons.value = []
      stockReasonsError.value = ''
      return
    }
    loadStockReasons(normalized)
  },
)
</script>

<style scoped>
.shouban30-page {
  min-height: 100vh;
  background: #f5f7fa;
}

.shouban30-page-body {
  min-height: calc(100vh - 64px);
  padding: 12px 16px 16px;
}

.shouban30-toolbar {
  margin-bottom: 12px;
  padding: 12px 16px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
}

.toolbar-title {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.page-title {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.page-meta,
.detail-meta,
.muted,
.reason-sub,
.tab-meta {
  color: #909399;
}

.page-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.shouban30-grid {
  display: grid;
  grid-template-columns: minmax(320px, 1.15fr) minmax(280px, 1fr) minmax(320px, 1.25fr);
  gap: 12px;
  min-height: calc(100vh - 180px);
}

.panel-card {
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 12px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
}

.panel-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

.panel-controls {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 10px;
}

.provider-tabs {
  min-width: 0;
}

.provider-tab-label {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  line-height: 1.15;
}

.tab-meta {
  font-size: 11px;
  font-weight: 400;
}

.window-buttons {
  align-self: flex-start;
}

.panel-summary {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 12px;
  color: #606266;
}

.panel-summary-chanlun {
  padding-top: 2px;
  border-top: 1px dashed #ebeef5;
}

.panel-alert {
  margin-bottom: 8px;
}

.panel-table {
  flex: 1 1 auto;
  min-height: 0;
}

.mono {
  font-family: Consolas, Monaco, 'Courier New', monospace;
}

:deep(.is-selected-row > td) {
  background: #ecf5ff !important;
}

@media (max-width: 1440px) {
  .shouban30-grid {
    grid-template-columns: minmax(260px, 1fr) minmax(260px, 1fr);
  }

  .shouban30-grid > :last-child {
    grid-column: 1 / -1;
  }
}

@media (max-width: 960px) {
  .shouban30-grid {
    grid-template-columns: 1fr;
    min-height: auto;
  }

  .panel-table {
    min-height: 320px;
  }
}
</style>
