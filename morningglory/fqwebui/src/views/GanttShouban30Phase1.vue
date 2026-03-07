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

        <div class="toolbar-controls">
          <el-tabs
            :model-value="activeProvider"
            class="provider-tabs"
            @tab-change="handleProviderChange"
          >
            <el-tab-pane label="XGB" name="xgb" />
            <el-tab-pane label="JYGS" name="jygs" />
          </el-tabs>

          <el-button-group>
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
        </div>
      </div>

      <div class="shouban30-grid">
        <section class="panel-card">
          <div class="panel-card-header">
            <span>首板板块</span>
            <span class="muted">{{ plates.length }}</span>
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
              :data="plates"
              size="small"
              border
              height="100%"
              empty-text="暂无 30 天首板板块"
              :row-class-name="plateRowClassName"
              @row-click="handlePlateRowClick"
            >
              <el-table-column prop="plate_name" label="板块" min-width="120" show-overflow-tooltip />
              <el-table-column prop="appear_days_30" label="30天" width="70" />
              <el-table-column label="连续段" min-width="150">
                <template #default="{ row }">
                  <span class="mono">{{ row.seg_from || '-' }}</span>
                  <span> ~ </span>
                  <span class="mono">{{ row.seg_to || '-' }}</span>
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
            <span class="muted">{{ stocks.length }}</span>
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
              :data="stocks"
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
  normalizeShouban30Provider,
  normalizeShouban30StockWindowDays
} from '@/api/ganttShouban30'
import MyHeader from './MyHeader.vue'

const route = useRoute()
const router = useRouter()

const plates = ref([])
const stocks = ref([])
const stockReasons = ref([])

const platesLoading = ref(false)
const stocksLoading = ref(false)
const stockReasonsLoading = ref(false)

const platesError = ref('')
const stocksError = ref('')
const stockReasonsError = ref('')

const selectedPlateKey = ref('')
const selectedStockCode6 = ref('')
const resolvedAsOfDate = ref('')

let plateRequestId = 0
let stockRequestId = 0
let reasonRequestId = 0

const activeProvider = computed(() => normalizeShouban30Provider(route.query.p))
const stockWindowDays = computed(() => {
  return normalizeShouban30StockWindowDays(route.query.stock_window_days)
})
const requestedAsOfDate = computed(() => String(route.query.as_of_date || '').trim())

const selectedStock = computed(() => {
  return stocks.value.find((item) => item.code6 === selectedStockCode6.value) || null
})

const plateCountLabel = computed(() => `${stockWindowDays.value}标的`)
const stockHitCountLabel = computed(() => `${stockWindowDays.value}次`)
const windowRangeLabel = computed(() => {
  const item = plates.value[0]
  const start = String(item?.stock_window_from || '').trim()
  const end = String(item?.stock_window_to || resolvedAsOfDate.value || '').trim()
  if (!start || !end) return ''
  return `${start} ~ ${end}`
})

const normalizeList = (value) => {
  return Array.isArray(value) ? value : []
}

const getErrorMessage = (error, fallback) => {
  return String(error?.response?.data?.message || error?.message || fallback)
}

const updateQuery = (patch = {}) => {
  const nextQuery = {
    ...(route.query || {}),
    ...patch
  }
  Object.keys(nextQuery).forEach((key) => {
    const value = nextQuery[key]
    if (value === undefined || value === null || value === '') {
      delete nextQuery[key]
    }
  })
  router.replace({
    name: 'gantt-shouban30',
    query: nextQuery
  }).catch(() => {})
}

const clearDetailState = () => {
  selectedStockCode6.value = ''
  stockReasons.value = []
  stockReasonsError.value = ''
}

const clearStockState = () => {
  selectedPlateKey.value = ''
  stocks.value = []
  stocksError.value = ''
  clearDetailState()
}

const loadStockReasons = async (code6) => {
  const targetCode6 = String(code6 || '').trim()
  selectedStockCode6.value = targetCode6
  stockReasons.value = []
  stockReasonsError.value = ''
  if (!targetCode6) return

  const requestId = ++reasonRequestId
  stockReasonsLoading.value = true
  try {
    const response = await getGanttStockReasons({
      code6: targetCode6,
      provider: 'all',
      limit: 0
    })
    if (requestId !== reasonRequestId) return
    stockReasons.value = normalizeList(response?.data?.data?.items)
  } catch (error) {
    if (requestId !== reasonRequestId) return
    stockReasonsError.value = getErrorMessage(error, '加载标的详情失败')
  } finally {
    if (requestId === reasonRequestId) stockReasonsLoading.value = false
  }
}

const loadStocks = async (plateKey) => {
  const targetPlateKey = String(plateKey || '').trim()
  selectedPlateKey.value = targetPlateKey
  stocks.value = []
  stocksError.value = ''
  clearDetailState()
  if (!targetPlateKey) return

  const requestId = ++stockRequestId
  stocksLoading.value = true
  try {
    const response = await getShouban30Stocks({
      provider: activeProvider.value,
      plateKey: targetPlateKey,
      stockWindowDays: stockWindowDays.value,
      asOfDate: resolvedAsOfDate.value || requestedAsOfDate.value || undefined
    })
    if (requestId !== stockRequestId) return
    const payload = response?.data?.data || {}
    stocks.value = normalizeList(payload.items)
    const nextStockCode6 = stocks.value[0]?.code6 || ''
    if (!nextStockCode6) return
    await loadStockReasons(nextStockCode6)
  } catch (error) {
    if (requestId !== stockRequestId) return
    stocksError.value = getErrorMessage(error, '加载热点标的失败')
  } finally {
    if (requestId === stockRequestId) stocksLoading.value = false
  }
}

const loadPlates = async () => {
  const requestId = ++plateRequestId
  platesLoading.value = true
  platesError.value = ''
  plates.value = []
  clearStockState()
  resolvedAsOfDate.value = requestedAsOfDate.value
  try {
    const response = await getShouban30Plates({
      provider: activeProvider.value,
      stockWindowDays: stockWindowDays.value,
      asOfDate: requestedAsOfDate.value || undefined
    })
    if (requestId !== plateRequestId) return
    const payload = response?.data?.data || {}
    const meta = payload.meta || {}
    plates.value = normalizeList(payload.items)
    resolvedAsOfDate.value = String(meta.as_of_date || requestedAsOfDate.value || '').trim()
    const nextPlateKey = plates.value[0]?.plate_key || ''
    if (!nextPlateKey) return
    await loadStocks(nextPlateKey)
  } catch (error) {
    if (requestId !== plateRequestId) return
    platesError.value = getErrorMessage(error, '加载首板板块失败')
  } finally {
    if (requestId === plateRequestId) platesLoading.value = false
  }
}

const handleProviderChange = (value) => {
  updateQuery({
    p: normalizeShouban30Provider(value),
    stock_window_days: String(stockWindowDays.value),
    as_of_date: requestedAsOfDate.value || undefined
  })
}

const handleStockWindowChange = (value) => {
  updateQuery({
    p: activeProvider.value,
    stock_window_days: String(normalizeShouban30StockWindowDays(value)),
    as_of_date: requestedAsOfDate.value || undefined
  })
}

const handlePlateRowClick = (row) => {
  loadStocks(row?.plate_key)
}

const handleStockRowClick = (row) => {
  loadStockReasons(row?.code6)
}

const plateRowClassName = ({ row }) => {
  return selectedPlateKey.value && row?.plate_key === selectedPlateKey.value
    ? 'is-selected-row'
    : ''
}

const stockRowClassName = ({ row }) => {
  return selectedStockCode6.value && row?.code6 === selectedStockCode6.value
    ? 'is-selected-row'
    : ''
}

const formatProvider = (value) => {
  return String(value || '').trim().toUpperCase() || '-'
}

watch(
  () => [activeProvider.value, stockWindowDays.value, requestedAsOfDate.value],
  () => {
    loadPlates()
  },
  { immediate: true }
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
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-end;
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
.reason-sub {
  color: #909399;
}

.page-meta,
.toolbar-controls {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.provider-tabs {
  min-width: 180px;
}

.shouban30-grid {
  display: grid;
  grid-template-columns: minmax(280px, 1.15fr) minmax(280px, 1fr) minmax(320px, 1.25fr);
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
  .shouban30-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .shouban30-grid {
    grid-template-columns: 1fr;
    min-height: auto;
  }

  .panel-table {
    min-height: 320px;
  }
}
</style>
