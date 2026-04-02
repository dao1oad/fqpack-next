<template>
  <WorkbenchLedgerPanel class="position-subject-overview-panel">
    <div class="workbench-panel__header">
      <div class="workbench-title-group">
        <div class="workbench-panel__title">标的总览</div>
        <div class="workbench-panel__desc">
          基础配置 + 单标的仓位上限与按持仓入口止损已经并入一张表，直接在中栏完成查看与保存。
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
        placeholder="搜索代码 / 名称 / 分类"
        class="position-subject-toolbar__query"
      />
      <el-select
        v-model="selectedSubjectCategory"
        clearable
        placeholder="全部分类"
        class="position-subject-toolbar__select"
      >
        <el-option
          v-for="option in categoryOptions"
          :key="option"
          :label="option"
          :value="option"
        />
      </el-select>
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
        活跃止损 <strong>{{ activeStoplossCount }}</strong>
      </StatusChip>
    </div>

    <div class="position-subject-table-wrap">
      <el-table
        v-loading="loadingOverview"
        :data="subjectOverviewPage.rows"
        row-key="symbol"
        size="small"
        border
        height="100%"
        class="position-subject-table"
      >
        <el-table-column label="标的" width="114">
          <template #default="{ row }">
            <div class="position-subject-symbol">
              <strong class="workbench-code">{{ row.symbol }}</strong>
              <span>{{ row.name || '-' }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="运行态" min-width="170">
          <template #default="{ row }">
            <div class="position-subject-runtime">
              <span>分类 {{ row.category || '-' }}</span>
              <span>持仓 {{ formatInteger(row.position_quantity) }} 股</span>
              <span>市值 {{ formatWanAmount(row.position_amount) }}</span>
              <span class="workbench-code">{{ formatDateTime(row.runtime?.last_trigger_time) }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="基础配置 + 单标的仓位上限" min-width="380">
          <template #default="{ row }">
            <div
              v-if="detailMap[row.symbol]"
              class="position-subject-config-list"
            >
              <div
                v-for="configRow in buildDenseConfigRows(detailMap[row.symbol] || {})"
                :key="`${row.symbol}-${configRow.key}`"
                class="position-subject-config-row"
              >
                <div class="position-subject-config-row__meta">
                  <strong>{{ configRow.label }}</strong>
                  <span>{{ configRow.currentLabel }}</span>
                </div>

                <div class="position-subject-config-row__editor">
                  <el-input
                    v-if="configRow.key === 'category'"
                    v-model.trim="mustPoolDrafts[row.symbol].category"
                    size="small"
                    placeholder="分类"
                  />
                  <el-input-number
                    v-else-if="configRow.key === 'stop_loss_price'"
                    v-model="mustPoolDrafts[row.symbol].stop_loss_price"
                    size="small"
                    :min="0"
                    :step="0.01"
                    :precision="2"
                    controls-position="right"
                  />
                  <el-input-number
                    v-else-if="configRow.key === 'initial_lot_amount'"
                    v-model="mustPoolDrafts[row.symbol].initial_lot_amount"
                    size="small"
                    :min="0"
                    :step="1000"
                    controls-position="right"
                  />
                  <el-input-number
                    v-else-if="configRow.key === 'lot_amount'"
                    v-model="mustPoolDrafts[row.symbol].lot_amount"
                    size="small"
                    :min="0"
                    :step="1000"
                    controls-position="right"
                  />
                  <el-input-number
                    v-else-if="configRow.key === 'position_limit_value'"
                    v-model="positionLimitDrafts[row.symbol].limit"
                    size="small"
                    :min="0"
                    :step="10000"
                    controls-position="right"
                  />

                  <el-tag size="small" :type="resolveConfigRowTagType(configRow)">
                    {{ configRow.statusLabel }}
                  </el-tag>
                </div>

                <div class="position-subject-config-row__note">
                  {{ configRow.note }}
                </div>
              </div>

              <div class="position-subject-config-actions">
                <el-button
                  size="small"
                  type="primary"
                  :loading="Boolean(savingConfigBundle[row.symbol])"
                  @click="saveConfigBundleForSymbol(row.symbol)"
                >
                  保存配置
                </el-button>
              </div>
            </div>

            <div v-else class="position-subject-inline-empty">
              {{ detailErrors[row.symbol] || '加载标的详情中…' }}
            </div>
          </template>
        </el-table-column>

        <el-table-column label="聚合买入列表 / 按持仓入口止损" min-width="470">
          <template #default="{ row }">
            <div
              v-if="detailMap[row.symbol]?.entries?.length"
              class="position-subject-entry-list"
            >
              <article
                v-for="entry in detailMap[row.symbol].entries"
                :key="entry.entry_id"
                class="position-subject-entry-card"
              >
                <div class="position-subject-entry-card__header">
                  <div class="position-subject-entry-card__title">
                    <strong>{{ entry.entryDisplayLabel }}</strong>
                    <span>{{ entry.entryIdLabel }}</span>
                  </div>

                  <el-popover
                    placement="top-start"
                    trigger="hover"
                    width="380"
                  >
                    <template #reference>
                      <el-link type="primary" :underline="false">切片明细</el-link>
                    </template>

                    <div class="position-subject-popover">
                      <div class="position-subject-popover__section">
                        <div class="position-subject-popover__title">聚合买入列表</div>
                        <div
                          v-if="entry.aggregation_members?.length"
                          class="position-subject-popover__chips"
                        >
                          <span
                            v-for="(member, index) in entry.aggregation_members"
                            :key="`${entry.entry_id}-aggregation-${index}`"
                            class="position-subject-popover__chip"
                          >
                            {{ member.order_id || member.slice_id || member.entry_id || `member-${index + 1}` }}
                            {{ formatInteger(member.quantity) }} 股
                          </span>
                        </div>
                        <div v-else class="position-subject-popover__empty">
                          当前没有 aggregation_members。
                        </div>
                      </div>

                      <div class="position-subject-popover__section">
                        <div class="position-subject-popover__title">切片明细</div>
                        <div
                          v-if="entry.entry_slices?.length"
                          class="position-subject-slice-table"
                        >
                          <div class="position-subject-slice-table__head">
                            <span>序号</span>
                            <span>守护价</span>
                            <span>原始数量</span>
                            <span>剩余数量</span>
                            <span>剩余市值</span>
                          </div>
                          <div
                            v-for="slice in entry.entry_slices"
                            :key="slice.entry_slice_id"
                            class="position-subject-slice-table__row"
                          >
                            <span>{{ formatInteger(slice.slice_seq) }}</span>
                            <span>{{ formatPrice(slice.guardian_price) }}</span>
                            <span>{{ formatInteger(slice.original_quantity) }}</span>
                            <span>{{ formatInteger(slice.remaining_quantity) }}</span>
                            <span>{{ formatWanAmount(slice.remaining_amount) }}</span>
                          </div>
                        </div>
                        <div v-else class="position-subject-popover__empty">
                          当前没有 open 切片。
                        </div>
                      </div>
                    </div>
                  </el-popover>
                </div>

                <div class="position-subject-entry-card__summary">
                  <span>{{ entry.entrySummaryLines?.[0] }}</span>
                  <span>{{ entry.entrySummaryLines?.[1] }}</span>
                </div>

                <div class="position-subject-entry-card__editor">
                  <div class="position-subject-entry-card__field">
                    <span>止损价</span>
                    <el-input-number
                      v-model="stoplossDrafts[row.symbol][entry.entry_id].stop_price"
                      size="small"
                      :min="0"
                      :step="0.01"
                      :precision="2"
                      controls-position="right"
                    />
                  </div>
                  <div class="position-subject-entry-card__field position-subject-entry-card__field--switch">
                    <span>启用</span>
                    <el-switch
                      v-model="stoplossDrafts[row.symbol][entry.entry_id].enabled"
                    />
                  </div>
                  <div class="position-subject-entry-card__actions">
                    <el-button
                      size="small"
                      type="primary"
                      :loading="Boolean(savingStoploss[row.symbol])"
                      @click="saveStoplossForEntry(row.symbol, entry.entry_id)"
                    >
                      保存止损
                    </el-button>
                  </div>
                </div>
              </article>
            </div>

            <div v-else class="position-subject-inline-empty">
              当前标的没有 open entry。
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
import { computed, onMounted, reactive, ref, toRefs, watch } from 'vue'
import { ElMessage } from 'element-plus'

import StatusChip from '../workbench/StatusChip.vue'
import WorkbenchLedgerPanel from '../workbench/WorkbenchLedgerPanel.vue'
import { subjectManagementApi } from '@/api/subjectManagementApi'
import {
  DEFAULT_OVERVIEW_PAGE_SIZE,
  OVERVIEW_PAGE_SIZE_OPTIONS,
  paginateOverviewRows,
} from '@/views/subjectManagementOverviewPagination.mjs'
import {
  buildDenseConfigRows,
  createSubjectManagementActions,
} from '@/views/subjectManagement.mjs'
import { createPositionManagementSubjectWorkbenchController } from '@/views/positionManagementSubjectWorkbench.mjs'
import { formatBeijingTimestamp } from '../../tool/beijingTime.mjs'

const actions = createSubjectManagementActions(subjectManagementApi)
const controller = createPositionManagementSubjectWorkbenchController({
  actions,
  notify: ElMessage,
  reactiveImpl: reactive,
})

const {
  detailErrors,
  detailMap,
  loadingOverview,
  mustPoolDrafts,
  overviewRows,
  pageError,
  positionLimitDrafts,
  savingConfigBundle,
  savingStoploss,
  stoplossDrafts,
} = toRefs(controller.state)

const searchSubjectKeyword = ref('')
const selectedSubjectCategory = ref('')
const subjectOverviewPagination = reactive({
  page: 1,
  pageSize: DEFAULT_OVERVIEW_PAGE_SIZE,
})
const overviewPageSizeOptions = OVERVIEW_PAGE_SIZE_OPTIONS

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

const categoryOptions = computed(() => Array.from(
  new Set((overviewRows.value || []).map((row) => String(row.category || '').trim()).filter(Boolean)),
).sort((left, right) => left.localeCompare(right)))

const filteredOverviewRows = computed(() => {
  const keyword = String(searchSubjectKeyword.value || '').trim().toLowerCase()
  return (overviewRows.value || []).filter((row) => {
    if (selectedSubjectCategory.value && row.category !== selectedSubjectCategory.value) return false
    if (!keyword) return true
    return [
      row.symbol,
      row.name,
      row.category,
    ]
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

const ensureSubjectDetailsForPage = async () => {
  await controller.ensureSymbolsHydrated(
    (subjectOverviewPage.value?.rows || []).map((row) => row.symbol),
  )
}

watch(
  () => [searchSubjectKeyword.value, selectedSubjectCategory.value],
  () => {
    subjectOverviewPagination.page = 1
  },
)

watch(
  () => (subjectOverviewPage.value?.rows || []).map((row) => row.symbol).join(','),
  async () => {
    await ensureSubjectDetailsForPage()
  },
  { immediate: true },
)

const handleRefreshSubjectOverview = async () => {
  await controller.refreshOverview()
  await ensureSubjectDetailsForPage()
}

const handleSubjectOverviewPageChange = (page) => {
  subjectOverviewPagination.page = page
}

const handleSubjectOverviewPageSizeChange = (pageSize) => {
  subjectOverviewPagination.pageSize = pageSize
  subjectOverviewPagination.page = 1
}

const resolveConfigRowTagType = (row) => {
  if (row?.statusTone) return row.statusTone
  if (row?.key === 'position_limit_value') {
    return row?.statusLabel === '单独设置' ? 'warning' : 'info'
  }
  return 'info'
}

const saveConfigBundleForSymbol = async (symbol) => {
  const parsed = Number(positionLimitDrafts.value?.[symbol]?.limit)
  if (!Number.isFinite(parsed) || parsed <= 0) {
    ElMessage.warning(`请先填写 ${symbol} 的有效单标的上限`)
    return
  }
  await controller.saveConfigBundle(symbol)
}

const saveStoplossForEntry = async (symbol, entryId) => {
  const draft = stoplossDrafts.value?.[symbol]?.[entryId] || {}
  if (draft.enabled) {
    const parsed = Number(draft.stop_price)
    if (!Number.isFinite(parsed) || parsed <= 0) {
      ElMessage.warning(`开启止损前请先填写 ${entryId} 的 stop_price`)
      return
    }
  }
  await controller.saveStoploss(symbol, entryId)
}

onMounted(async () => {
  await controller.refreshOverview()
  await ensureSubjectDetailsForPage()
})
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
  grid-template-columns: minmax(220px, 1.3fr) minmax(160px, 0.7fr);
  gap: 8px;
  margin-bottom: 8px;
}

.position-subject-toolbar__query,
.position-subject-toolbar__select {
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

.position-subject-table :deep(.el-input-number) {
  width: 100%;
}

.position-subject-table :deep(.el-table__cell) {
  padding-top: 8px;
  padding-bottom: 8px;
  vertical-align: top;
}

.position-subject-symbol,
.position-subject-runtime {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.position-subject-symbol strong {
  color: #21405e;
}

.position-subject-symbol span,
.position-subject-runtime span {
  color: #68839d;
  font-size: 12px;
  line-height: 1.45;
}

.position-subject-config-list,
.position-subject-entry-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.position-subject-config-row,
.position-subject-entry-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid #e5edf5;
  border-radius: 12px;
  background: #fbfdff;
}

.position-subject-config-row__meta,
.position-subject-config-row__editor,
.position-subject-entry-card__header,
.position-subject-entry-card__editor {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.position-subject-config-row__meta {
  align-items: flex-start;
}

.position-subject-config-row__meta strong,
.position-subject-entry-card__title strong {
  color: #21405e;
}

.position-subject-config-row__meta span,
.position-subject-entry-card__title span,
.position-subject-config-row__note,
.position-subject-entry-card__summary span,
.position-subject-inline-empty {
  color: #68839d;
  font-size: 12px;
  line-height: 1.45;
}

.position-subject-config-row__editor {
  align-items: center;
}

.position-subject-config-row__note,
.position-subject-entry-card__summary {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.position-subject-config-actions {
  display: flex;
  justify-content: flex-end;
}

.position-subject-entry-card__title {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.position-subject-entry-card__field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  flex: 1 1 0;
}

.position-subject-entry-card__field span {
  color: #68839d;
  font-size: 11px;
}

.position-subject-entry-card__field--switch {
  flex: 0 0 auto;
  min-width: 72px;
}

.position-subject-entry-card__actions {
  display: flex;
  justify-content: flex-end;
}

.position-subject-popover {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.position-subject-popover__section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.position-subject-popover__title {
  color: #21405e;
  font-size: 12px;
  font-weight: 600;
}

.position-subject-popover__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.position-subject-popover__chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: 999px;
  background: #eef4fb;
  color: #35506c;
  font-size: 12px;
}

.position-subject-popover__empty {
  color: #68839d;
  font-size: 12px;
}

.position-subject-slice-table {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.position-subject-slice-table__head,
.position-subject-slice-table__row {
  display: grid;
  grid-template-columns: 46px 72px 74px 74px minmax(76px, 1fr);
  gap: 8px;
  font-size: 12px;
  line-height: 1.45;
}

.position-subject-slice-table__head {
  color: #68839d;
}

.position-subject-slice-table__row {
  color: #21405e;
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

  .position-subject-config-row__meta,
  .position-subject-config-row__editor,
  .position-subject-entry-card__header,
  .position-subject-entry-card__editor {
    flex-direction: column;
    align-items: flex-start;
  }

  .position-subject-entry-card__actions,
  .position-subject-config-actions {
    justify-content: flex-start;
  }
}
</style>
