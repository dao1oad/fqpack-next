<template>
  <WorkbenchLedgerPanel class="position-subject-overview-panel">
    <div class="workbench-panel__header">
      <div class="workbench-title-group">
        <div class="workbench-panel__title">标的总览</div>
        <div class="workbench-panel__desc">
          当前页按持仓优先、仓位市值降序展示。设置项全部横向收敛进主表，点击任一行驱动右栏联动。
        </div>
      </div>

      <div class="workbench-toolbar__actions position-subject-header__actions">
        <el-input
          v-model="searchSubjectKeyword"
          clearable
          placeholder="搜索代码 / 名称"
          class="position-subject-toolbar__query"
        />
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
        :fit="true"
        height="100%"
        highlight-current-row
        class="position-subject-table position-subject-table--dense"
        @row-click="handleSubjectRowClick"
        @current-change="handleSubjectCurrentChange"
      >
        <el-table-column label="标的" width="104" fixed="left">
          <template #default="{ row }">
            <div class="position-subject-symbol">
              <strong class="workbench-code">{{ row.symbol }}</strong>
              <span>{{ row.name || '-' }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="检查结果" min-width="84">
          <template #default="{ row }">
            <StatusChip class="runtime-inline-status" :variant="row.audit_status_chip_variant || 'muted'">
              {{ row.audit_status_label || row.audit_status || '未跟踪' }}
            </StatusChip>
          </template>
        </el-table-column>

        <el-table-column label="持仓" min-width="96">
          <template #default="{ row }">
            <div class="position-subject-metric-stack">
              <span class="position-subject-metric-stack__primary workbench-code">
                {{ formatQuantityWithUnit(row.position_quantity) }}
              </span>
              <span class="position-subject-metric-stack__secondary workbench-code">
                {{ formatWanAmount(row.position_amount) }}
              </span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="订单状态" min-width="84">
          <template #default="{ row }">
            <div class="position-subject-status-stack">
              <span class="position-subject-status-line">
                <strong class="workbench-code position-subject-status-line__label">SL</strong>
                <span>{{ formatInteger(row.stoplossActiveCount) }}</span>
              </span>
              <span class="position-subject-status-line">
                <strong class="workbench-code position-subject-status-line__label">Open</strong>
                <span>{{ formatInteger(row.openEntryCount) }}</span>
              </span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="Guardian 买入层级（配置）" min-width="128">
          <template #default="{ row }">
            <div class="position-subject-summary-stack">
              <div
                v-for="item in row.guardianLevelSummary"
                :key="`${row.symbol}-guardian-${item.level}`"
                class="position-subject-summary-line"
              >
                <span class="workbench-code position-subject-summary-line__level">B{{ item.level }}</span>
                <span class="workbench-code position-subject-summary-line__price">{{ item.priceLabel }}</span>
                <span
                  class="position-subject-inline-state position-subject-summary-line__state"
                  :class="{ active: item.enabled }"
                >
                  {{ item.enabledLabel }}
                </span>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="止盈价格层级" min-width="128">
          <template #default="{ row }">
            <div class="position-subject-summary-stack">
              <div
                v-for="item in row.takeprofitSummary"
                :key="`${row.symbol}-takeprofit-${item.level}`"
                class="position-subject-summary-line"
              >
                <span class="workbench-code position-subject-summary-line__level">L{{ item.level }}</span>
                <span class="workbench-code position-subject-summary-line__price">{{ item.priceLabel }}</span>
                <span
                  class="position-subject-inline-state position-subject-summary-line__state"
                  :class="{ active: item.enabled }"
                >
                  {{ item.enabledLabel }}
                </span>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="Guardian 层级触发" min-width="104" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="position-subject-trigger-line">
              <span class="workbench-code position-subject-trigger-line__kind">{{ row.guardianTrigger?.kindLabel || '-' }}</span>
              <span class="workbench-code position-subject-trigger-line__time">{{ row.guardianTrigger?.timeLabel || '-' }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="止盈层级触发" min-width="104" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="position-subject-trigger-line">
              <span class="workbench-code position-subject-trigger-line__kind">{{ row.takeprofitTrigger?.kindLabel || '-' }}</span>
              <span class="workbench-code position-subject-trigger-line__time">{{ row.takeprofitTrigger?.timeLabel || '-' }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="单笔止损触发" min-width="104" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="position-subject-trigger-line">
              <span class="workbench-code position-subject-trigger-line__kind">{{ row.entryStoplossTrigger?.kindLabel || '-' }}</span>
              <span class="workbench-code position-subject-trigger-line__time">{{ row.entryStoplossTrigger?.timeLabel || '-' }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="全仓止损价" min-width="88">
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

        <el-table-column label="单标的仓位上限" min-width="96">
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

        <el-table-column label="保存" width="70" fixed="right">
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

const formatQuantityWithUnit = (value) => {
  const label = formatInteger(value)
  return label === '-' ? label : `${label} 股`
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

.position-subject-header__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.position-subject-toolbar__query {
  width: 280px;
  min-width: 220px;
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

.position-subject-metric-stack,
.position-subject-status-stack {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.position-subject-symbol strong,
.position-subject-cell-strong {
  color: #21405e;
}

.position-subject-symbol span {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.position-subject-symbol span,
.position-subject-runtime span,
.position-subject-summary-line,
.position-subject-cell-muted,
.position-subject-status-line,
.position-subject-metric-stack__secondary {
  color: #68839d;
  font-size: 12px;
  line-height: 1.45;
}

.position-subject-status-stack {
  gap: 2px;
}

.position-subject-metric-stack__primary,
.position-subject-status-line__label {
  color: #21405e;
  font-size: 12px;
  line-height: 1.45;
}

.position-subject-trigger-line {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  color: #68839d;
  font-size: 12px;
  line-height: 1.45;
  white-space: nowrap;
}

.position-subject-trigger-line__kind {
  color: #21405e;
  flex: 0 0 auto;
}

.position-subject-trigger-line__time {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.position-subject-status-line {
  display: flex;
  align-items: center;
  gap: 4px;
}

.position-subject-summary-line {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 4px;
}

.position-subject-summary-line__level,
.position-subject-summary-line__price {
  min-width: 0;
}

.position-subject-summary-line__price {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.position-subject-summary-line__state {
  justify-self: end;
}

.position-subject-inline-state {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 32px;
  padding: 1px 5px;
  border-radius: 999px;
  background: rgba(245, 108, 108, 0.12);
  color: #c45656;
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
  .position-subject-header__actions {
    width: 100%;
    justify-content: flex-end;
  }

  .position-subject-toolbar__query {
    width: min(100%, 280px);
  }
}
</style>
