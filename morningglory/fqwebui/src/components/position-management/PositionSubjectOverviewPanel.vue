<template>
  <WorkbenchLedgerPanel class="position-subject-overview-panel">
    <div class="workbench-panel__header">
      <div class="workbench-title-group">
        <div class="workbench-panel__title">标的总览</div>
        <div class="workbench-panel__desc">
          当前页按持仓优先、仓位市值降序展示。设置项全部横向收敛进主表，点击任一行驱动右栏联动。
        </div>
      </div>

      <div class="workbench-toolbar__actions">
        <el-button :loading="loadingOverview" @click="handleRefreshSubjectOverview">刷新</el-button>
      </div>
    </div>

    <el-alert
      v-if="pageError"
      class="workbench-alert"
      type="error"
      :title="pageError"
      :closable="false"
      show-icon
    />

    <div class="position-subject-toolbar">
      <el-input
        v-model="searchSubjectKeyword"
        clearable
        placeholder="搜索代码 / 名称"
        class="position-subject-toolbar__query"
      />
    </div>

    <div class="workbench-summary-row">
      <StatusChip variant="muted">
        总标的 <strong>{{ overviewRows.length }}</strong>
      </StatusChip>
      <StatusChip variant="muted">
        当前页 <strong>{{ subjectOverviewPage.rows.length }}</strong>
      </StatusChip>
      <StatusChip variant="success">
        已加载详情 <strong>{{ loadedDetailCount }}</strong>
      </StatusChip>
      <StatusChip variant="warning">
        活跃单笔止损 <strong>{{ activeStoplossCount }}</strong>
      </StatusChip>
    </div>

    <div class="position-subject-table-wrap">
      <el-table
        ref="subjectOverviewTableRef"
        v-loading="loadingOverview"
        :data="subjectOverviewPage.rows"
        row-key="symbol"
        size="small"
        border
        height="100%"
        highlight-current-row
        class="position-subject-table position-subject-table--dense"
        @row-click="handleSubjectRowClick"
        @current-change="handleSubjectCurrentChange"
      >
        <el-table-column label="标的" width="148" fixed="left">
          <template #default="{ row }">
            <div class="position-subject-symbol">
              <strong class="workbench-code">{{ row.symbol }}</strong>
              <span>{{ row.name || '-' }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="持仓股数" width="98" align="right">
          <template #default="{ row }">
            <span class="workbench-code position-subject-number">
              {{ formatInteger(row.position_quantity) }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="持仓市值" width="110" align="right">
          <template #default="{ row }">
            <span class="workbench-code position-subject-number">
              {{ formatWanAmount(row.position_amount) }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="门禁" width="120">
          <template #default="{ row }">
            <StatusChip
              class="runtime-inline-status"
              :variant="resolvePmStateChipVariant(detailForSymbol(row.symbol))"
            >
              {{ resolvePmStateLabel(detailForSymbol(row.symbol)) }}
            </StatusChip>
          </template>
        </el-table-column>

        <el-table-column label="Guardian 层级买入" width="158">
          <template #default="{ row }">
            <div class="position-subject-summary-stack">
              <div class="position-subject-summary-line">
                <span
                  class="position-subject-inline-state"
                  :class="{ active: row.guardian.enabled }"
                >
                  {{ row.guardian.enabled ? '开启' : '关闭' }}
                </span>
                <span>{{ row.guardian.last_hit_level || '-' }}</span>
              </div>
              <div class="position-subject-summary-line workbench-code">
                B1 {{ formatPrice(row.guardian.buy_1) }}
              </div>
              <div class="position-subject-summary-line workbench-code">
                B2 {{ formatPrice(row.guardian.buy_2) }}
              </div>
              <div class="position-subject-summary-line workbench-code">
                B3 {{ formatPrice(row.guardian.buy_3) }}
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="止盈价格" width="164">
          <template #default="{ row }">
            <div class="position-subject-summary-stack">
              <div
                v-for="item in row.takeprofitSummary"
                :key="`${row.symbol}-takeprofit-${item.level}`"
                class="position-subject-summary-line"
              >
                <span class="workbench-code">L{{ item.level }}</span>
                <span class="workbench-code">{{ item.priceLabel }}</span>
                <span
                  class="position-subject-inline-state"
                  :class="{ active: item.enabled }"
                >
                  {{ item.enabledLabel }}
                </span>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="全仓止损价" width="110">
          <template #default="{ row }">
            <div class="position-subject-input-cell" :title="configNote(row.symbol, 'stop_loss_price')">
              <el-input-number
                v-if="workbench.state.mustPoolDrafts[row.symbol]"
                v-model="workbench.state.mustPoolDrafts[row.symbol].stop_loss_price"
                :placeholder="mustPoolNumberPlaceholder(row.symbol, 'stop_loss_price', formatPrice)"
                size="small"
                :min="0"
                :step="0.01"
                :precision="2"
                controls-position="right"
              />
              <span v-else class="position-subject-cell-muted">-</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="首笔买入金额" width="122">
          <template #default="{ row }">
            <div class="position-subject-input-cell" :title="configNote(row.symbol, 'initial_lot_amount')">
              <el-input-number
                v-if="workbench.state.mustPoolDrafts[row.symbol]"
                v-model="workbench.state.mustPoolDrafts[row.symbol].initial_lot_amount"
                :placeholder="mustPoolNumberPlaceholder(row.symbol, 'initial_lot_amount', formatInteger)"
                size="small"
                :min="0"
                :step="1000"
                controls-position="right"
              />
              <span v-else class="position-subject-cell-muted">-</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="默认买入金额" width="122">
          <template #default="{ row }">
            <div class="position-subject-input-cell" :title="configNote(row.symbol, 'lot_amount')">
              <el-input-number
                v-if="workbench.state.mustPoolDrafts[row.symbol]"
                v-model="workbench.state.mustPoolDrafts[row.symbol].lot_amount"
                :placeholder="mustPoolNumberPlaceholder(row.symbol, 'lot_amount', formatInteger)"
                size="small"
                :min="0"
                :step="1000"
                controls-position="right"
              />
              <span v-else class="position-subject-cell-muted">-</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="单标的仓位上限" width="126">
          <template #default="{ row }">
            <div class="position-subject-input-cell" :title="configNote(row.symbol, 'position_limit_value')">
              <el-input-number
                v-if="workbench.state.positionLimitDrafts[row.symbol]"
                v-model="workbench.state.positionLimitDrafts[row.symbol].limit"
                size="small"
                :min="0"
                :step="10000"
                controls-position="right"
              />
              <span v-else class="position-subject-cell-muted">-</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="活跃单笔止损" width="92" align="center">
          <template #default="{ row }">
            <span class="position-subject-cell-strong">{{ row.stoplossActiveCount }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Open Entry" width="92" align="center">
          <template #default="{ row }">
            <span class="position-subject-cell-strong">{{ row.openEntryCount }}</span>
          </template>
        </el-table-column>

        <el-table-column label="最近触发" width="164">
          <template #default="{ row }">
            <div class="position-subject-runtime">
              <span>{{ formatTriggerKind(row.runtime?.last_trigger_kind) }}</span>
              <span class="workbench-code">{{ formatDateTime(row.runtime?.last_trigger_time) }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="保存" width="94" fixed="right">
          <template #default="{ row }">
            <div class="position-subject-save-cell">
              <el-button
                size="small"
                type="primary"
                :loading="Boolean(workbench.state.savingConfigBundle[row.symbol])"
                @click.stop="saveConfigBundleForSymbol(row.symbol)"
              >
                保存
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="position-subject-pagination">
      <el-pagination
        background
        layout="total,sizes,prev,pager,next"
        :current-page="subjectOverviewPagination.page"
        :page-size="subjectOverviewPagination.pageSize"
        :total="subjectOverviewPage.total"
        :page-sizes="overviewPageSizeOptions"
        @current-change="handleSubjectOverviewPageChange"
        @size-change="handleSubjectOverviewPageSizeChange"
      />
    </div>
  </WorkbenchLedgerPanel>
</template>

<script setup>
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import StatusChip from '../workbench/StatusChip.vue'
import WorkbenchLedgerPanel from '../workbench/WorkbenchLedgerPanel.vue'
import {
  DEFAULT_OVERVIEW_PAGE_SIZE,
  OVERVIEW_PAGE_SIZE_OPTIONS,
  paginateOverviewRows,
} from '@/views/subjectManagementOverviewPagination.mjs'
import { buildDenseConfigRows } from '@/views/subjectManagement.mjs'
import { formatBeijingTimestamp } from '../../tool/beijingTime.mjs'

const props = defineProps({
  workbench: {
    type: Object,
    required: true,
  },
  selectedSymbol: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['symbol-select'])

const subjectOverviewTableRef = ref(null)
const searchSubjectKeyword = ref('')
const subjectOverviewPagination = reactive({
  page: 1,
  pageSize: DEFAULT_OVERVIEW_PAGE_SIZE,
})
const overviewPageSizeOptions = OVERVIEW_PAGE_SIZE_OPTIONS

const workbench = computed(() => props.workbench)
const overviewRows = computed(() => workbench.value?.state?.overviewRows || [])
const loadingOverview = computed(() => Boolean(workbench.value?.state?.loadingOverview))
const pageError = computed(() => workbench.value?.state?.pageError || '')
const detailMap = computed(() => workbench.value?.state?.detailMap || {})

const formatPrice = (value) => {
  if (value === null || value === undefined || value === '') return '-'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '-'
  return Number.isInteger(parsed) ? parsed.toFixed(1) : String(parsed)
}

const formatInteger = (value) => {
  if (value === null || value === undefined || value === '') return '-'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '-'
  return String(Math.trunc(parsed))
}

const formatWanAmount = (value) => {
  if (value === null || value === undefined || value === '') return '-'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '-'
  return `${(parsed / 10000).toFixed(2)} 万`
}

const formatDateTime = (value) => formatBeijingTimestamp(value)
const formatTriggerKind = (value) => {
  const label = String(value ?? '').trim()
  if (!label) return '-'
  const mapping = {
    takeprofit: '止盈',
    stoploss: '止损',
  }
  return mapping[label] || label
}

const filteredOverviewRows = computed(() => {
  const keyword = String(searchSubjectKeyword.value || '').trim().toLowerCase()
  return (overviewRows.value || []).filter((row) => {
    if (!keyword) return true
    return [row.symbol, row.name]
      .join(' ')
      .toLowerCase()
      .includes(keyword)
  })
})

const subjectOverviewPage = computed(() => paginateOverviewRows(
  filteredOverviewRows.value,
  subjectOverviewPagination,
))

const loadedDetailCount = computed(() => Object.keys(detailMap.value || {}).length)
const activeStoplossCount = computed(() => (
  (overviewRows.value || []).filter((row) => Number(row.stoplossActiveCount || 0) > 0).length
))

const detailConfigMap = computed(() => Object.fromEntries(
  Object.entries(detailMap.value || {}).map(([symbol, detail]) => [
    symbol,
    Object.fromEntries(buildDenseConfigRows(detail || {}).map((item) => [item.key, item])),
  ]),
))

const detailForSymbol = (symbol) => detailMap.value?.[symbol] || null

const resolvePmStateLabel = (detail) => (
  detail?.positionManagementSummary?.effective_state_label || '待加载'
)

const resolvePmStateChipVariant = (detail) => (
  detail?.positionManagementSummary?.effective_state_chip_variant || 'muted'
)

const configNote = (symbol, key) => detailConfigMap.value?.[symbol]?.[key]?.note || ''

const mustPoolNumberPlaceholder = (symbol, key, formatter) => {
  const draftValue = workbench.value?.state?.mustPoolDrafts?.[symbol]?.[key]
  if (draftValue !== null && draftValue !== undefined && draftValue !== '') return ''
  const effectiveValue = detailForSymbol(symbol)?.baseConfigSummary?.[key]?.effective_value
  const effectiveLabel = formatter(effectiveValue)
  return effectiveLabel === '-' ? '未配置' : effectiveLabel
}

const applyCurrentRow = async (symbol) => {
  await nextTick()
  const targetRow = (subjectOverviewPage.value?.rows || []).find((row) => row.symbol === symbol) || null
  subjectOverviewTableRef.value?.setCurrentRow?.(targetRow)
}

const emitSelectedSymbol = (symbol) => {
  emit('symbol-select', String(symbol || '').trim())
}

const ensureSubjectDetailsForPage = async () => {
  await workbench.value.ensureSymbolsHydrated(
    (subjectOverviewPage.value?.rows || []).map((row) => row.symbol),
  )
}

const syncSelectedSubject = async () => {
  const pageRows = subjectOverviewPage.value?.rows || []
  if (!pageRows.length) {
    if (props.selectedSymbol) {
      emitSelectedSymbol('')
    }
    await applyCurrentRow('')
    return
  }

  await ensureSubjectDetailsForPage()

  const nextSymbol = pageRows.some((row) => row.symbol === props.selectedSymbol)
    ? props.selectedSymbol
    : pageRows[0].symbol

  if (nextSymbol !== props.selectedSymbol) {
    emitSelectedSymbol(nextSymbol)
  }
  await applyCurrentRow(nextSymbol)
}

watch(
  () => searchSubjectKeyword.value,
  () => {
    subjectOverviewPagination.page = 1
  },
)

watch(
  () => (subjectOverviewPage.value?.rows || []).map((row) => row.symbol).join(','),
  async () => {
    await syncSelectedSubject()
  },
  { immediate: true },
)

watch(
  () => props.selectedSymbol,
  async (symbol) => {
    await applyCurrentRow(symbol)
  },
)

const handleRefreshSubjectOverview = async () => {
  await workbench.value.refreshOverview()
  await ensureSubjectDetailsForPage()
  await syncSelectedSubject()
}

const handleSubjectOverviewPageChange = (page) => {
  subjectOverviewPagination.page = page
}

const handleSubjectOverviewPageSizeChange = (pageSize) => {
  subjectOverviewPagination.pageSize = pageSize
  subjectOverviewPagination.page = 1
}

const handleSubjectRowClick = (row) => {
  if (!row?.symbol) return
  emitSelectedSymbol(row.symbol)
}

const handleSubjectCurrentChange = (row) => {
  if (!row?.symbol || row.symbol === props.selectedSymbol) return
  emitSelectedSymbol(row.symbol)
}

const saveConfigBundleForSymbol = async (symbol) => {
  const parsed = Number(workbench.value?.state?.positionLimitDrafts?.[symbol]?.limit)
  if (!Number.isFinite(parsed) || parsed <= 0) {
    ElMessage.warning(`请先填写 ${symbol} 的有效单标的上限`)
    return
  }
  await workbench.value.saveConfigBundle(symbol)
}
</script>

<style scoped>
.position-subject-overview-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.position-subject-toolbar {
  display: grid;
  grid-template-columns: minmax(220px, 1fr);
  gap: 8px;
  margin-bottom: 8px;
}

.position-subject-toolbar__query {
  width: 100%;
}

.position-subject-table-wrap {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.position-subject-table {
  height: 100%;
}

.position-subject-table--dense :deep(.el-table__cell) {
  padding-top: 6px;
  padding-bottom: 6px;
  vertical-align: middle;
}

.position-subject-table--dense :deep(.el-input-number) {
  width: 100%;
}

.position-subject-table--dense :deep(.el-table__body tr.current-row > td.el-table__cell) {
  background: #eef5ff;
}

.position-subject-symbol,
.position-subject-runtime {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.position-subject-summary-stack {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.position-subject-symbol strong,
.position-subject-cell-strong {
  color: #21405e;
}

.position-subject-symbol span,
.position-subject-runtime span,
.position-subject-summary-line,
.position-subject-cell-muted {
  color: #68839d;
  font-size: 12px;
  line-height: 1.45;
}

.position-subject-summary-line {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.position-subject-inline-state {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 36px;
  padding: 1px 6px;
  border-radius: 999px;
  background: #eef4fb;
  color: #5f7890;
  font-size: 11px;
  line-height: 1.5;
}

.position-subject-inline-state.active {
  background: rgba(64, 158, 255, 0.12);
  color: #1d5fa8;
}

.position-subject-input-cell,
.position-subject-save-cell {
  display: flex;
  align-items: center;
}

.position-subject-input-cell {
  min-height: 28px;
}

.position-subject-number {
  color: #21405e;
  font-variant-numeric: tabular-nums;
}

.position-subject-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
}

@media (max-width: 1320px) {
  .position-subject-toolbar {
    grid-template-columns: 1fr;
  }
}
</style>
