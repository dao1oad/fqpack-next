<template>
  <div class="shouban30-page">
    <MyHeader />
    <div class="shouban30-page-body">
      <div class="shouban30-toolbar">
        <div class="toolbar-title">
          <div class="page-title">首板筛选</div>
          <div class="page-meta">
            <span>end_date {{ resolvedEndDate || '-' }}</span>
            <span>/</span>
            <span>自然日窗口 {{ stockWindowDays }} 日</span>
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

            <div class="extra-filter-buttons">
              <span class="extra-filter-buttons__label">条件筛选</span>
              <el-button
                v-for="option in EXTRA_FILTER_OPTIONS"
                :key="option.key"
                size="small"
                :type="selectedExtraFilterKeys.includes(option.key) ? 'primary' : ''"
                :plain="!selectedExtraFilterKeys.includes(option.key)"
                @click="toggleExtraFilterSelection(option.key)"
              >
                {{ option.label }}
              </el-button>
              <el-button
                size="small"
                type="success"
                :disabled="!currentFilterReplacePayload.items.length || platesLoading || stocksLoading"
                :loading="isWorkspaceActionRunning('workspace:save-current-filter')"
                @click="handleSaveCurrentFilter"
              >
                筛选
              </el-button>
            </div>

            <div class="panel-summary">
              <span>{{ activeViewLabel }}</span>
              <span>{{ currentStats.plate_count }} 个热门板块</span>
              <span>/</span>
              <span>{{ currentStats.stock_count }} 个热门个股</span>
            </div>
            <div v-if="activeExtraFilterLabels.length" class="panel-summary panel-summary-filters">
              <span>交集筛选</span>
              <span>/</span>
              <span>{{ activeExtraFilterLabels.join(' / ') }}</span>
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
              :empty-text="platesEmptyText"
              :row-class-name="plateRowClassName"
              @row-click="handlePlateRowClick"
            >
              <el-table-column prop="plate_name" label="板块" min-width="120" show-overflow-tooltip />
              <el-table-column prop="appear_days_30" :label="windowDaysLabel" width="70" />
              <el-table-column prop="last_up_date" label="最后上板" width="110">
                <template #default="{ row }">
                  <span class="mono">{{ row.last_up_date || row.seg_to || '-' }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="reason_text" label="板块理由" min-width="220">
                <template #default="{ row }">
                  <Shouban30ReasonPopover
                    :reference-text="row.reason_text"
                    :content-text="row.reason_text"
                    :title="row.plate_name"
                    :subtitle="buildPlateReasonSubtitle(row)"
                    placement="right-start"
                  />
                </template>
              </el-table-column>
              <el-table-column :label="plateCountLabel" prop="stocks_count" width="92" />
              <el-table-column label="操作" width="144" fixed="right">
                <template #default="{ row }">
                  <el-button
                    size="small"
                    type="primary"
                    link
                    :loading="isWorkspaceActionRunning(`workspace:save-plate:${toText(row?.plate_key)}`)"
                    @click.stop="handleSavePlateToPrePool(row)"
                  >
                    保存到 pre_pools
                  </el-button>
                </template>
              </el-table-column>
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
              :empty-text="stocksEmptyText"
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
              <el-table-column prop="latest_reason" label="最近理由" min-width="180">
                <template #default="{ row }">
                  <Shouban30ReasonPopover
                    :reference-text="row.latest_reason"
                    :content-text="row.latest_reason"
                    :title="`${row.name || row.code6} ${row.code6 || ''}`.trim()"
                    :subtitle="buildStockReasonSubtitle(row)"
                    placement="right-start"
                  />
                </template>
              </el-table-column>
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
              <el-table-column label="理由" min-width="240">
                <template #default="{ row }">
                  <Shouban30ReasonPopover
                    :reference-text="row.stock_reason || row.plate_reason"
                    :title="selectedStock ? `${selectedStock.name || selectedStock.code6} ${selectedStock.code6 || ''}`.trim() : '标的理由'"
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
          </div>
        </section>

        <section class="panel-card panel-card-workspace">
          <div class="panel-card-header">
            <span>工作区</span>
            <span class="muted">{{ prePoolItems.length }} / {{ stockPoolItems.length }}</span>
          </div>
          <div class="panel-summary">
            <span>pre_pool {{ prePoolItems.length }}</span>
            <span>/</span>
            <span>stockpools {{ stockPoolItems.length }}</span>
            <template v-if="workspaceBlkFilename">
              <span>/</span>
              <span>blk {{ workspaceBlkFilename }}</span>
            </template>
          </div>
          <div v-if="workspaceBlkSyncLabel" class="panel-summary panel-summary-filters">
            <span>{{ workspaceBlkSyncLabel }}</span>
          </div>
          <el-alert
            v-if="workspaceError"
            class="panel-alert"
            type="error"
            :closable="false"
            :title="workspaceError"
          />
          <div class="workspace-tabs-wrap">
            <el-tabs v-model="activeWorkspaceTab" class="workspace-tabs">
              <el-tab-pane
                v-for="tab in workspaceTabs"
                :key="tab.key"
                :name="tab.key"
              >
                <template #label>
                  <div class="workspace-tab-label">
                    <span>{{ tab.label }}</span>
                    <span class="tab-meta">{{ tab.rows.length }}</span>
                  </div>
                </template>
                <div class="workspace-tab-actions">
                  <el-button
                    v-if="tab.key === 'pre_pool'"
                    size="small"
                    type="primary"
                    plain
                    :loading="isWorkspaceActionRunning('workspace:pre:sync-tdx')"
                    @click="handleSyncPrePoolToTdx"
                  >
                    {{ tab.sync_action_label }}
                  </el-button>
                  <el-button
                    v-if="tab.key === 'stockpools'"
                    size="small"
                    type="primary"
                    plain
                    :loading="isWorkspaceActionRunning('workspace:stock:sync-tdx')"
                    @click="handleSyncStockPoolToTdx"
                  >
                    {{ tab.sync_action_label }}
                  </el-button>
                </div>
                <div class="panel-table">
                  <el-table
                    v-loading="workspaceLoading"
                    :data="tab.rows"
                    size="small"
                    border
                    height="100%"
                    :empty-text="workspaceEmptyText"
                  >
                    <el-table-column prop="code6" label="代码" width="92">
                      <template #default="{ row }">
                        <span class="mono">{{ row.code6 }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column prop="name" label="名称" min-width="120" show-overflow-tooltip />
                    <el-table-column prop="provider" label="来源" width="84">
                      <template #default="{ row }">
                        {{ formatProvider(row.provider) }}
                      </template>
                    </el-table-column>
                    <el-table-column prop="plate_name" label="板块" min-width="140" show-overflow-tooltip />
                    <el-table-column prop="category" label="分类" min-width="140" show-overflow-tooltip />
                    <el-table-column label="操作" min-width="188" fixed="right">
                      <template #default="{ row }">
                        <div class="workspace-row-actions">
                          <el-button
                            v-if="tab.key === 'pre_pool'"
                            size="small"
                            type="primary"
                            link
                            :loading="isWorkspaceActionRunning(`workspace:pre:add:${row.code6}`)"
                            @click="handleAddPrePoolToStockPools(row)"
                          >
                            {{ row.primary_action_label }}
                          </el-button>
                          <el-button
                            v-if="tab.key === 'stockpools'"
                            size="small"
                            type="primary"
                            link
                            :loading="isWorkspaceActionRunning(`workspace:stock:must:${row.code6}`)"
                            @click="handleAddStockPoolToMustPool(row)"
                          >
                            {{ row.primary_action_label }}
                          </el-button>
                          <el-button
                            v-if="tab.key === 'pre_pool'"
                            size="small"
                            type="danger"
                            link
                            :loading="isWorkspaceActionRunning(`workspace:pre:delete:${row.code6}`)"
                            @click="handleDeletePrePoolRow(row)"
                          >
                            {{ row.secondary_action_label }}
                          </el-button>
                          <el-button
                            v-if="tab.key === 'stockpools'"
                            size="small"
                            type="danger"
                            link
                            :loading="isWorkspaceActionRunning(`workspace:stock:delete:${row.code6}`)"
                            @click="handleDeleteStockPoolRow(row)"
                          >
                            {{ row.secondary_action_label }}
                          </el-button>
                        </div>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>
              </el-tab-pane>
            </el-tabs>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { getGanttStockReasons } from '@/api/ganttApi'
import {
  SHOUBAN30_STOCK_WINDOW_OPTIONS,
  addShouban30PrePoolToStockPool,
  addShouban30StockPoolToMustPool,
  deleteShouban30PrePoolItem,
  deleteShouban30StockPoolItem,
  getShouban30PrePool,
  getShouban30Plates,
  getShouban30StockPool,
  getShouban30Stocks,
  normalizeShouban30StockWindowDays,
  replaceShouban30PrePool,
  syncShouban30PrePoolToTdx,
  syncShouban30StockPoolToTdx,
} from '@/api/ganttShouban30'

import MyHeader from './MyHeader.vue'
import {
  aggregatePlateRows,
  aggregateStockRows,
  buildChanlunFilterStats,
  buildViewStats,
  formatProviderLabel,
  loadProvidersIndependently,
  normalizeSourcePlateRefs,
  sortStockRows,
} from './shouban30Aggregation.mjs'
import Shouban30ReasonPopover from './components/Shouban30ReasonPopover.vue'
import {
  EXTRA_FILTER_OPTIONS,
  filterStockRowsByPlate,
  rebuildPlatesFromFilteredStocks,
  toggleExtraFilter,
} from './shouban30StockFilters.mjs'
import {
  buildCurrentFilterReplacePrePoolPayload,
  buildSinglePlateReplacePrePoolPayload,
  buildWorkspaceTabs,
} from './shouban30PoolWorkspace.mjs'

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
const selectedExtraFilterKeys = ref([])
const prePoolItems = ref([])
const stockPoolItems = ref([])
const activeWorkspaceTab = ref('pre_pool')

const stockReasons = ref([])

const platesLoading = ref(false)
const stocksLoading = ref(false)
const stockReasonsLoading = ref(false)
const workspaceLoading = ref(false)

const platesError = ref('')
const stocksError = ref('')
const stockReasonsError = ref('')
const workspaceError = ref('')

const selectedPlateViewKey = ref('')
const selectedStockCode6 = ref('')
const workspaceActionKey = ref('')
const workspaceBlkSync = ref(null)
const workspaceCategories = ref({
  pre_pool: '',
  stockpools: '',
})
const workspaceBlkFilename = ref('')

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
  return normalizeShouban30StockWindowDays(route.query.days || route.query.stock_window_days)
})
const requestedEndDate = computed(() => {
  return toText(route.query.end_date || route.query.as_of_date)
})

const padDateNumber = (value) => String(value).padStart(2, '0')

const calcCalendarWindowStart = (endDate, days) => {
  const targetEndDate = toText(endDate)
  if (!targetEndDate) return ''
  const match = targetEndDate.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (!match) return ''
  const next = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])))
  next.setUTCDate(next.getUTCDate() - normalizeShouban30StockWindowDays(days) + 1)
  return `${next.getUTCFullYear()}-${padDateNumber(next.getUTCMonth() + 1)}-${padDateNumber(next.getUTCDate())}`
}

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

const filteredSourceStocksByProvider = computed(() => {
  return Object.fromEntries(
    SOURCE_PROVIDERS.map((provider) => [
      provider,
      filterStockRowsByPlate(
        sourceStocksByProvider.value?.[provider] || {},
        selectedExtraFilterKeys.value,
      ),
    ]),
  )
})

const xgbPlates = computed(() => {
  if (stockLoadErrorProviders.value.includes('xgb')) return []
  return rebuildPlatesFromFilteredStocks({
    plates: sourcePlatesByProvider.value.xgb,
    stockRowsByPlate: filteredSourceStocksByProvider.value.xgb,
  })
})

const jygsPlates = computed(() => {
  if (stockLoadErrorProviders.value.includes('jygs')) return []
  return rebuildPlatesFromFilteredStocks({
    plates: sourcePlatesByProvider.value.jygs,
    stockRowsByPlate: filteredSourceStocksByProvider.value.jygs,
  })
})

const aggPlates = computed(() => {
  return aggregatePlateRows({
    xgbPlates: xgbPlates.value,
    jygsPlates: jygsPlates.value,
    stockRowsByProvider: filteredSourceStocksByProvider.value,
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
  return normalizeList(filteredSourceStocksByProvider.value?.[provider]?.[plateKey])
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

const currentViewStockRowsByPlate = computed(() => {
  if (activeViewProvider.value === 'agg') {
    return aggregateStockRowsByPlate.value
  }
  const providerRows = filteredSourceStocksByProvider.value?.[activeViewProvider.value] || {}
  return Object.fromEntries(
    currentPlates.value.map((plate) => [
      toText(plate?.view_key),
      normalizeList(providerRows[toText(plate?.plate_key)]),
    ]),
  )
})

const statsByView = computed(() => {
  return {
    xgb: buildViewStats({
      plates: xgbPlates.value,
      stockRowsByPlate: filteredSourceStocksByProvider.value.xgb,
    }),
    jygs: buildViewStats({
      plates: jygsPlates.value,
      stockRowsByPlate: filteredSourceStocksByProvider.value.jygs,
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

const resolvedEndDate = computed(() => {
  if (activeViewProvider.value === 'agg') {
    return SOURCE_PROVIDERS
      .map((provider) => toText(sourceMetaByProvider.value?.[provider]?.end_date || sourceMetaByProvider.value?.[provider]?.as_of_date))
      .filter(Boolean)
      .sort()
      .at(-1) || ''
  }
  return toText(
    sourceMetaByProvider.value?.[activeViewProvider.value]?.end_date
      || sourceMetaByProvider.value?.[activeViewProvider.value]?.as_of_date,
  )
})

const windowRangeLabel = computed(() => {
  const end = resolvedEndDate.value || requestedEndDate.value
  const start = calcCalendarWindowStart(end, stockWindowDays.value)
  if (!start || !end) return ''
  return `${start} ~ ${end}`
})

const activeViewLabel = computed(() => {
  return VIEW_PROVIDER_OPTIONS.find((item) => item.name === activeViewProvider.value)?.label || 'XGB'
})
const activeExtraFilterLabels = computed(() => {
  return EXTRA_FILTER_OPTIONS
    .filter((item) => selectedExtraFilterKeys.value.includes(item.key))
    .map((item) => item.label)
})
const currentFilterReplacePayload = computed(() => {
  return buildCurrentFilterReplacePrePoolPayload({
    plates: currentPlates.value,
    stockRowsByPlate: currentViewStockRowsByPlate.value,
    stockWindowDays: stockWindowDays.value,
    asOfDate: resolvedEndDate.value || requestedEndDate.value,
    selectedExtraFilterKeys: selectedExtraFilterKeys.value,
  })
})
const workspaceTabs = computed(() => {
  return buildWorkspaceTabs({
    prePoolItems: prePoolItems.value,
    stockPoolItems: stockPoolItems.value,
  })
})
const workspaceEmptyText = computed(() => {
  return workspaceLoading.value ? '工作区加载中' : '暂无工作区记录'
})
const workspaceBlkSyncLabel = computed(() => {
  const sync = workspaceBlkSync.value
  if (!sync?.success) return ''
  const filePath = toText(sync.file_path)
  const fileName = filePath.split(/[\\/]/).filter(Boolean).at(-1) || workspaceBlkFilename.value || '-'
  return `最近 blk 同步 ${sync.count ?? 0} 条 -> ${fileName}`
})

const windowDaysLabel = computed(() => `${stockWindowDays.value}天`)
const plateCountLabel = computed(() => '通过数')
const stockHitCountLabel = computed(() => `${stockWindowDays.value}次`)
const platesEmptyText = computed(() => {
  return selectedExtraFilterKeys.value.length
    ? '当前筛选条件下暂无板块'
    : '暂无首板板块'
})
const stocksEmptyText = computed(() => {
  if (selectedExtraFilterKeys.value.length && !currentPlates.value.length) {
    return '当前筛选条件下暂无标的'
  }
  return currentPlates.value.length ? '请先选择左侧板块' : '暂无热点标的'
})

const formatTabStats = (stats) => {
  const target = stats || EMPTY_STATS
  return `${target.plate_count}板 / ${target.stock_count}股`
}

const formatProvider = (value) => formatProviderLabel(value)

const buildPlateReasonSubtitle = (row) => {
  return `${formatProvider(row?.provider)} / 最后上板 ${toText(row?.last_up_date || row?.seg_to) || '-'}`
}

const buildStockReasonSubtitle = (row) => {
  return `最近上榜 ${toText(row?.latest_trade_date) || '-'}`
}

const buildReasonDetailSubtitle = (row) => {
  const date = toText(row?.date) || '-'
  const time = toText(row?.time)
  return `${formatProvider(row?.provider)} / ${time ? `${date} ${time}` : date}`
}

const isWorkspaceActionRunning = (key) => workspaceActionKey.value === key

const updateWorkspaceMeta = ({ prePoolResponse, stockPoolResponse } = {}) => {
  workspaceCategories.value = {
    pre_pool: toText(prePoolResponse?.meta?.category) || workspaceCategories.value.pre_pool,
    stockpools: toText(stockPoolResponse?.meta?.category) || workspaceCategories.value.stockpools,
  }
  workspaceBlkFilename.value = toText(prePoolResponse?.meta?.blk_filename) || workspaceBlkFilename.value
}

const updateWorkspaceBlkSync = (response) => {
  const blkSync = response?.meta?.blk_sync || response?.data?.blk_sync || null
  if (blkSync) {
    workspaceBlkSync.value = blkSync
  }
}

const loadWorkspace = async () => {
  workspaceLoading.value = true
  workspaceError.value = ''
  try {
    const [prePoolResponse, stockPoolResponse] = await Promise.all([
      getShouban30PrePool(),
      getShouban30StockPool(),
    ])
    prePoolItems.value = normalizeList(prePoolResponse?.data?.items)
    stockPoolItems.value = normalizeList(stockPoolResponse?.data?.items)
    updateWorkspaceMeta({ prePoolResponse, stockPoolResponse })
  } catch (error) {
    workspaceError.value = getErrorMessage(error, '加载工作区失败')
  } finally {
    workspaceLoading.value = false
  }
}

const runWorkspaceAction = async ({
  actionKey,
  action,
  successMessage,
  refreshWorkspace = true,
} = {}) => {
  workspaceActionKey.value = actionKey
  workspaceError.value = ''
  try {
    const response = await action()
    updateWorkspaceBlkSync(response)
    if (refreshWorkspace) {
      await loadWorkspace()
    }
    if (successMessage) {
      ElMessage.success(successMessage)
    }
    return response
  } catch (error) {
    const message = getErrorMessage(error, '工作区操作失败')
    workspaceError.value = message
    ElMessage.error(message)
    return null
  } finally {
    workspaceActionKey.value = ''
  }
}

const buildSinglePlateReplacePayload = (plate) => {
  return buildSinglePlateReplacePrePoolPayload({
    plate,
    stockRowsByPlate: currentViewStockRowsByPlate.value,
    stockWindowDays: stockWindowDays.value,
    asOfDate: resolvedEndDate.value || requestedEndDate.value,
    selectedExtraFilterKeys: selectedExtraFilterKeys.value,
  })
}

const toggleExtraFilterSelection = (key) => {
  selectedExtraFilterKeys.value = toggleExtraFilter(selectedExtraFilterKeys.value, key)
}

const handleSaveCurrentFilter = async () => {
  if (!currentFilterReplacePayload.value.items.length) {
    ElMessage.warning('当前筛选结果为空，无法保存')
    return
  }
  await runWorkspaceAction({
    actionKey: 'workspace:save-current-filter',
    action: () => replaceShouban30PrePool(currentFilterReplacePayload.value),
    successMessage: `已保存 ${currentFilterReplacePayload.value.items.length} 条到 pre_pools`,
  })
}

const handleSavePlateToPrePool = async (plate) => {
  const payload = buildSinglePlateReplacePayload(plate)
  if (!payload.items.length) {
    ElMessage.warning('当前板块没有可保存的标的')
    return
  }
  await runWorkspaceAction({
    actionKey: `workspace:save-plate:${toText(plate?.plate_key)}`,
    action: () => replaceShouban30PrePool(payload),
    successMessage: `${toText(plate?.plate_name) || '当前板块'} 已保存到 pre_pools`,
  })
}

const handleAddPrePoolToStockPools = async (row) => {
  await runWorkspaceAction({
    actionKey: `workspace:pre:add:${toText(row?.code6)}`,
    action: () => addShouban30PrePoolToStockPool({ code6: row?.code6 }),
    successMessage: `${toText(row?.code6)} 已加入 stockpools`,
  })
}

const handleDeletePrePoolRow = async (row) => {
  await runWorkspaceAction({
    actionKey: `workspace:pre:delete:${toText(row?.code6)}`,
    action: () => deleteShouban30PrePoolItem({ code6: row?.code6 }),
    successMessage: `${toText(row?.code6)} 已从 pre_pool 删除`,
  })
}

const handleSyncPrePoolToTdx = async () => {
  await runWorkspaceAction({
    actionKey: 'workspace:pre:sync-tdx',
    action: () => syncShouban30PrePoolToTdx(),
    successMessage: `已将 pre_pool ${prePoolItems.value.length} 条同步到通达信`,
    refreshWorkspace: false,
  })
}

const handleAddStockPoolToMustPool = async (row) => {
  await runWorkspaceAction({
    actionKey: `workspace:stock:must:${toText(row?.code6)}`,
    action: () => addShouban30StockPoolToMustPool({ code6: row?.code6 }),
    successMessage: `${toText(row?.code6)} 已加入 must_pools`,
    refreshWorkspace: false,
  })
}

const handleSyncStockPoolToTdx = async () => {
  await runWorkspaceAction({
    actionKey: 'workspace:stock:sync-tdx',
    action: () => syncShouban30StockPoolToTdx(),
    successMessage: `已将 stockpools ${stockPoolItems.value.length} 条同步到通达信`,
    refreshWorkspace: false,
  })
}

const handleDeleteStockPoolRow = async (row) => {
  await runWorkspaceAction({
    actionKey: `workspace:stock:delete:${toText(row?.code6)}`,
    action: () => deleteShouban30StockPoolItem({ code6: row?.code6 }),
    successMessage: `${toText(row?.code6)} 已从 stockpools 删除`,
  })
}

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
    days: stockWindowDays.value,
    endDate: requestedEndDate.value || undefined,
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
        days: stockWindowDays.value,
        endDate: asOfDate || requestedEndDate.value || undefined,
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
          toText(nextMeta[provider]?.end_date || nextMeta[provider]?.as_of_date),
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
    days: String(stockWindowDays.value),
    end_date: requestedEndDate.value || undefined,
    stock_window_days: undefined,
    as_of_date: undefined,
  })
}

const handleStockWindowChange = (value) => {
  updateQuery({
    p: activeViewProvider.value,
    days: String(normalizeShouban30StockWindowDays(value)),
    end_date: requestedEndDate.value || undefined,
    stock_window_days: undefined,
    as_of_date: undefined,
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
  () => [activeViewProvider.value, stockWindowDays.value, requestedEndDate.value],
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

onMounted(() => {
  loadWorkspace()
})
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

.panel-card-workspace {
  grid-column: 1 / -1;
  min-height: 320px;
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

.workspace-tab-label {
  display: flex;
  gap: 6px;
  align-items: center;
}

.tab-meta {
  font-size: 11px;
  font-weight: 400;
}

.window-buttons {
  align-self: flex-start;
}

.extra-filter-buttons {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.extra-filter-buttons__label {
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
}

.panel-summary {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 12px;
  color: #606266;
}

.panel-summary-filters {
  color: #475569;
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

.workspace-tabs-wrap,
.workspace-tabs {
  flex: 1 1 auto;
  min-height: 0;
}

.workspace-tab-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8px;
}

.workspace-row-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
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
