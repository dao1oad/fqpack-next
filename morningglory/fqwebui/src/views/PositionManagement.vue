<template>
  <WorkbenchPage class="position-page">
    <MyHeader />

    <div class="workbench-body position-body" v-loading="loading">
      <el-alert
        v-if="pageError"
        class="workbench-alert"
        type="error"
        :title="pageError"
        show-icon
        :closable="false"
      />

      <section class="position-workbench-grid">
        <div class="position-workbench-column position-workbench-column--left">
          <WorkbenchDetailPanel class="position-state-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">当前仓位状态</div>
              </div>

              <div class="workbench-toolbar__actions">
                <el-button @click="loadDashboard">刷新</el-button>
              </div>
            </div>

            <div class="position-panel-body position-state-scroll">
              <div class="workbench-summary-row">
                <StatusChip :variant="stateToneChipVariant">
                  {{ statePanel.hero.effective_state_label }}
                </StatusChip>
                <StatusChip :variant="staleChipVariant">
                  {{ statePanel.hero.stale_label }}
                </StatusChip>
                <StatusChip variant="muted">
                  raw state <strong>{{ statePanel.hero.raw_state_label }}</strong>
                </StatusChip>
              </div>

              <div class="position-panel-section">
                <div class="position-panel-section__title">规则矩阵</div>

                <div class="runtime-ledger runtime-position-rule-ledger">
                  <div class="runtime-ledger__header runtime-position-rule-ledger__grid">
                    <span>行为</span>
                    <span>结果</span>
                    <span>原因码</span>
                    <span>说明</span>
                  </div>

                  <div
                    v-for="row in ruleMatrix"
                    :key="row.key"
                    class="runtime-ledger__row runtime-position-rule-ledger__grid"
                    :class="{ 'runtime-ledger__row--blocked': !row.allowed }"
                  >
                    <span class="runtime-ledger__cell runtime-ledger__cell--strong">{{ row.label }}</span>
                    <span class="runtime-ledger__cell runtime-ledger__cell--status">
                      <StatusChip class="runtime-inline-status" :variant="ruleStatusChipVariant(row.allowed)">
                        {{ row.allowed_label }}
                      </StatusChip>
                    </span>
                    <span class="runtime-ledger__cell runtime-ledger__cell--mono runtime-ledger__cell--truncate" :title="row.reason_code">{{ row.reason_code }}</span>
                    <span class="runtime-ledger__cell runtime-position-rule-ledger__description" :title="row.reason_text">{{ row.reason_text }}</span>
                  </div>
                </div>
              </div>

              <div class="position-state-grid position-state-grid--compact">
                <article class="workbench-block position-metric-card position-rule-card">
                  <span>当前命中规则</span>
                  <strong>{{ statePanel.hero.matched_rule_title }}</strong>
                  <p>{{ statePanel.hero.matched_rule_detail }}</p>
                </article>

                <div class="position-metric-grid">
                  <article
                    v-for="item in statePanel.stats"
                    :key="item.key"
                    class="workbench-block position-metric-card"
                  >
                    <span>{{ item.label }}</span>
                    <strong>{{ item.value_label }}</strong>
                  </article>
                </div>

                <div class="position-meta-grid">
                  <article
                    v-for="item in statePanel.meta"
                    :key="item.key"
                    class="workbench-block position-meta-card"
                  >
                    <span>{{ item.label }}</span>
                    <strong>{{ item.value }}</strong>
                  </article>
                </div>
              </div>
            </div>
          </WorkbenchDetailPanel>

          <PositionSubjectOverviewPanel class="position-subject-overview-host" :workbench="subjectWorkbenchRuntime" :selected-symbol="selectedSubjectSymbol" @symbol-select="handleSelectedSubjectChange" />
        </div>

        <div class="position-workbench-column position-workbench-column--right">
          <WorkbenchLedgerPanel class="position-selection-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">选中标的工作区</div>
                <div class="workbench-panel__desc">
                  当前显示左栏选中标的的聚合买入列表 / 按持仓入口止损，以及切片明细。
                </div>
              </div>
            </div>

            <div class="workbench-summary-row">
              <StatusChip variant="muted">
                当前标的 <strong>{{ selectedSubjectSymbol || '-' }}</strong>
              </StatusChip>
              <StatusChip variant="muted">
                名称 <strong>{{ selectedSubjectName }}</strong>
              </StatusChip>
              <StatusChip variant="muted">
                当前入口 <strong>{{ selectedSubjectSelectedEntry?.entryCompactLabel || '-' }}</strong>
              </StatusChip>
              <StatusChip
                v-for="item in selectedSubjectSummaryChips"
                :key="item.key"
                :variant="item.tone"
              >
                {{ item.label }} <strong>{{ item.value }}</strong>
              </StatusChip>
            </div>

            <el-alert
              v-if="selectedSubjectError"
              class="workbench-alert"
              type="error"
              :title="selectedSubjectError"
              :closable="false"
              show-icon
            />

            <div
              v-else-if="selectedSubjectSymbol && selectedSubjectDetail"
              class="position-selection-panel__body"
            >
              <section class="position-selection-section">
                <div class="position-selection-section__title">聚合买入列表 / 按持仓入口止损</div>
                <div v-if="selectedSubjectEntryRows.length" class="position-selection-table-wrap">
                  <el-table
                    :data="selectedSubjectEntryRows"
                    row-key="entry_id"
                    size="small"
                    border
                    height="100%"
                    highlight-current-row
                    :current-row-key="selectedSubjectEntryId"
                    class="position-selection-entry-table"
                    @row-click="handleSelectedEntryChange"
                    @current-change="handleSelectedEntryChange"
                  >
                    <el-table-column label="入口" width="96">
                      <template #default="{ row }">
                        <div
                          class="position-selection-entry-cell position-selection-entry-cell--inline"
                          :title="`${row.entryDisplayLabel || '-'} / ${row.entryIdLabel || row.entry_id || '-'}`"
                        >
                          <strong>{{ row.entryCompactLabel || '-' }}</strong>
                        </div>
                      </template>
                    </el-table-column>

                    <el-table-column label="买入时间" width="148">
                      <template #default="{ row }">
                        <span class="workbench-code position-selection-cell__nowrap">{{ row.entrySummaryDisplay?.entryDateTimeLabel || '-' }}</span>
                      </template>
                    </el-table-column>

                    <el-table-column label="买入价" width="84" align="right">
                      <template #default="{ row }">
                        <span class="workbench-code">{{ row.entrySummaryDisplay?.entryPriceLabel || '-' }}</span>
                      </template>
                    </el-table-column>

                    <el-table-column label="买入数量" width="88" align="right">
                      <template #default="{ row }">
                        <span class="workbench-code">{{ row.entrySummaryDisplay?.originalQuantityLabel || '-' }}</span>
                      </template>
                    </el-table-column>

                    <el-table-column label="剩余 / 占比" width="148" align="right">
                      <template #default="{ row }">
                        <span class="workbench-code position-selection-cell__nowrap">{{ row.entrySummaryDisplay?.remainingPositionLabel || '-' }}</span>
                      </template>
                    </el-table-column>

                    <el-table-column label="市值" width="86" align="right">
                      <template #default="{ row }">
                        <span class="workbench-code">{{ row.entrySummaryDisplay?.remainingMarketValueLabel || '-' }}</span>
                      </template>
                    </el-table-column>

                    <el-table-column label="单笔止损" width="104">
                      <template #default="{ row }">
                        <el-input-number
                          v-if="subjectWorkbenchRuntime.state.stoplossDrafts[selectedSubjectSymbol]?.[row.entry_id]"
                          v-model="subjectWorkbenchRuntime.state.stoplossDrafts[selectedSubjectSymbol][row.entry_id].stop_price"
                          size="small"
                          :min="0"
                          :step="0.01"
                          :precision="2"
                          controls-position="right"
                        />
                        <span v-else class="position-selection-inline-empty">-</span>
                      </template>
                    </el-table-column>

                    <el-table-column label="启用" width="78" align="center">
                      <template #default="{ row }">
                        <el-switch
                          v-if="subjectWorkbenchRuntime.state.stoplossDrafts[selectedSubjectSymbol]?.[row.entry_id]"
                          v-model="subjectWorkbenchRuntime.state.stoplossDrafts[selectedSubjectSymbol][row.entry_id].enabled"
                        />
                        <span v-else class="position-selection-inline-empty">-</span>
                      </template>
                    </el-table-column>

                    <el-table-column label="保存" width="84" fixed="right">
                      <template #default="{ row }">
                        <el-button
                          size="small"
                          type="primary"
                          :loading="Boolean(subjectWorkbenchRuntime.state.savingStoploss[selectedSubjectSymbol])"
                          @click="saveSubjectStoploss(selectedSubjectSymbol, row.entry_id)"
                        >
                          保存
                        </el-button>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>
                <div v-else class="runtime-empty-panel">
                  <strong>当前标的没有 open entry</strong>
                </div>
              </section>

              <section class="position-selection-section">
                <div class="position-selection-section__title">切片明细</div>
                <div v-if="selectedSubjectSliceRows.length" class="position-selection-table-wrap">
                  <el-table
                    :data="selectedSubjectSliceRows"
                    size="small"
                    border
                    height="100%"
                    class="position-selection-slice-table"
                  >
                    <el-table-column label="入口" width="108">
                      <template #default="{ row }">
                        <div class="position-selection-entry-cell position-selection-entry-cell--inline" :title="`${row.entryDisplayLabel || '-'} / ${row.entryIdLabel || row.entry_id || '-'}`">
                          <strong>{{ row.entryCompactLabel || '-' }}</strong>
                        </div>
                      </template>
                    </el-table-column>
                    <el-table-column label="序号" width="72" align="center">
                      <template #default="{ row }">
                        <span class="workbench-code">{{ formatInteger(row.slice_seq) }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column label="守护价" width="84" align="right">
                      <template #default="{ row }">
                        <span class="workbench-code">{{ formatPrice(row.guardian_price) }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column label="原始数量" width="88" align="right">
                      <template #default="{ row }">
                        <span class="workbench-code">{{ formatInteger(row.original_quantity) }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column label="剩余数量" width="88" align="right">
                      <template #default="{ row }">
                        <span class="workbench-code">{{ formatInteger(row.remaining_quantity) }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column label="市值" width="88" align="right">
                      <template #default="{ row }">
                        <span class="workbench-code">{{ formatWanAmount(row.remaining_amount) }}</span>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>
                <div v-else class="runtime-empty-panel">
                  <strong>{{ selectedSubjectSelectedEntry ? '当前选中入口没有 open 切片' : '请先选择一个持仓入口' }}</strong>
                </div>
              </section>
            </div>

            <div v-else class="runtime-empty-panel">
              <strong>{{ selectedSubjectSymbol ? '当前标的详情加载中' : '请先在标的总览中选择一个标的' }}</strong>
            </div>
          </WorkbenchLedgerPanel>

          <WorkbenchLedgerPanel class="position-decision-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">最近决策与上下文</div>
              </div>
            </div>

            <div class="workbench-summary-row">
              <StatusChip variant="muted">
                覆盖范围 <strong>全部标的</strong>
              </StatusChip>
              <StatusChip variant="muted">
                当前页 <strong>{{ pagedDecisionRows.length }}</strong>
              </StatusChip>
              <StatusChip variant="muted">
                排序 <strong>时间从近到远</strong>
              </StatusChip>
              <StatusChip variant="muted">
                默认分页 <strong>{{ decisionPagination.pageSize }} / 页</strong>
              </StatusChip>
              <StatusChip variant="muted">
                当前页码 <strong>{{ decisionPagination.page }}</strong>
              </StatusChip>
            </div>

            <div v-if="pagedDecisionRows.length" class="position-decision-table-wrap">
              <el-table
                :data="pagedDecisionRows"
                row-key="selection_key"
                size="small"
                border
                :fit="false"
                height="100%"
                class="position-decision-table"
                :row-class-name="decisionRowClassName"
              >
                <el-table-column label="触发时间" min-width="152" resizable show-overflow-tooltip>
                  <template #default="{ row }">
                    <span class="workbench-code">{{ row.evaluated_at_label }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="标的" min-width="144" resizable show-overflow-tooltip>
                  <template #default="{ row }">
                    <strong class="position-decision-cell-strong">{{ row.symbol_display }}</strong>
                  </template>
                </el-table-column>
                <el-table-column label="动作" min-width="68" resizable show-overflow-tooltip prop="action_label" />
                <el-table-column label="结果" min-width="108" resizable>
                  <template #default="{ row }">
                    <StatusChip class="runtime-inline-status" :variant="decisionStatusChipVariant(row.tone)">
                      {{ row.allowed_label }}
                    </StatusChip>
                  </template>
                </el-table-column>
                <el-table-column label="门禁状态" min-width="128" resizable show-overflow-tooltip prop="state_label" />
                <el-table-column label="触发来源" min-width="180" resizable show-overflow-tooltip prop="source_display" />
                <el-table-column label="策略" min-width="112" resizable show-overflow-tooltip prop="strategy_label" />
                <el-table-column label="说明" min-width="180" resizable show-overflow-tooltip prop="reason_display" />
                <el-table-column label="持仓标的" min-width="92" resizable show-overflow-tooltip prop="holding_symbol_display" />
                <el-table-column label="实时市值" min-width="118" resizable align="right" show-overflow-tooltip prop="symbol_market_value_label" />
                <el-table-column label="仓位上限" min-width="118" resizable align="right" show-overflow-tooltip prop="symbol_position_limit_label" />
                <el-table-column label="市值来源" min-width="156" resizable show-overflow-tooltip prop="market_value_source_display" />
                <el-table-column label="数量来源" min-width="156" resizable show-overflow-tooltip prop="quantity_source_display" />
                <el-table-column label="盈利减仓" min-width="92" resizable show-overflow-tooltip prop="force_profit_reduce_display" />
                <el-table-column label="减仓模式" min-width="108" resizable show-overflow-tooltip prop="profit_reduce_mode_display" />
                <el-table-column label="Trace" min-width="144" resizable show-overflow-tooltip>
                  <template #default="{ row }">
                    <span class="workbench-code">{{ row.trace_display }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="Intent" min-width="144" resizable show-overflow-tooltip>
                  <template #default="{ row }">
                    <span class="workbench-code">{{ row.intent_display }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="附加上下文" min-width="260" resizable show-overflow-tooltip prop="extra_context_label" />
              </el-table>
            </div>

            <div v-else class="runtime-empty-panel">
              <strong>暂无最近决策记录</strong>
            </div>

            <div class="position-ledger-pagination">
              <el-pagination
                background
                layout="total,sizes,prev,pager,next"
                :current-page="decisionPagination.page"
                :page-size="decisionPagination.pageSize"
                :total="decisionLedgerRows.length"
                :page-sizes="[100, 200, 500]"
                @current-change="handleDecisionPageChange"
                @size-change="handleDecisionPageSizeChange"
              />
            </div>
          </WorkbenchLedgerPanel>
        </div>
      </section>
    </div>
  </WorkbenchPage>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import StatusChip from '../components/workbench/StatusChip.vue'
import WorkbenchDetailPanel from '../components/workbench/WorkbenchDetailPanel.vue'
import WorkbenchLedgerPanel from '../components/workbench/WorkbenchLedgerPanel.vue'
import WorkbenchPage from '../components/workbench/WorkbenchPage.vue'
import PositionSubjectOverviewPanel from '../components/position-management/PositionSubjectOverviewPanel.vue'
import MyHeader from '@/views/MyHeader.vue'
import { positionManagementApi } from '@/api/positionManagementApi'
import { subjectManagementApi } from '@/api/subjectManagementApi'
import {
  buildDetailSummaryChips,
  createSubjectManagementActions,
} from '@/views/subjectManagement.mjs'
import { createPositionManagementSubjectWorkbenchController } from '@/views/positionManagementSubjectWorkbench.mjs'
import {
  buildRecentDecisionLedgerRows,
  buildRuleMatrix,
  buildStatePanel,
  readDashboardPayload,
} from './positionManagement.mjs'
const loading = ref(false)
const pageError = ref('')
const dashboard = ref({})
const selectedSubjectSymbol = ref('')

const decisionPagination = reactive({
  page: 1,
  pageSize: 100,
})

const subjectActions = createSubjectManagementActions(subjectManagementApi)
const subjectWorkbenchController = createPositionManagementSubjectWorkbenchController({
  actions: subjectActions,
  notify: ElMessage,
  reactiveImpl: reactive,
})

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

const saveSubjectConfigBundle = async (symbol) => {
  const parsed = Number(subjectWorkbenchController.state.positionLimitDrafts?.[symbol]?.limit)
  if (!Number.isFinite(parsed) || parsed <= 0) {
    ElMessage.warning(`请先填写 ${symbol} 的有效单标的上限`)
    return
  }
  await subjectWorkbenchController.saveConfigBundle(symbol)
}

const saveSubjectStoploss = async (symbol, entryId) => {
  const draft = subjectWorkbenchController.state.stoplossDrafts?.[symbol]?.[entryId] || {}
  if (draft.enabled) {
    const parsed = Number(draft.stop_price)
    if (!Number.isFinite(parsed) || parsed <= 0) {
      ElMessage.warning(`开启止损前请先填写 ${entryId} 的 stop_price`)
      return
    }
  }
  await subjectWorkbenchController.saveStoploss(symbol, entryId)
}

const subjectWorkbenchRuntime = {
  state: subjectWorkbenchController.state,
  refreshOverview: async (options) => subjectWorkbenchController.refreshOverview(options),
  ensureSymbolsHydrated: async (symbols) => subjectWorkbenchController.ensureSymbolsHydrated(symbols),
  selectEntry: (symbol, entryId) => subjectWorkbenchController.selectEntry(symbol, entryId),
  getSelectedEntryId: (symbol) => subjectWorkbenchController.getSelectedEntryId(symbol),
  getSelectedEntry: (symbol) => subjectWorkbenchController.getSelectedEntry(symbol),
  getSelectedEntrySlices: (symbol) => subjectWorkbenchController.getSelectedEntrySlices(symbol),
  saveConfigBundle: async (symbol) => saveSubjectConfigBundle(symbol),
  saveStoploss: async (symbol, entryId) => saveSubjectStoploss(symbol, entryId),
}

const statePanel = computed(() => buildStatePanel(dashboard.value))
const ruleMatrix = computed(() => buildRuleMatrix(dashboard.value))
const decisionLedgerRows = computed(() => buildRecentDecisionLedgerRows(dashboard.value))
const pagedDecisionRows = computed(() => {
  const start = (decisionPagination.page - 1) * decisionPagination.pageSize
  return decisionLedgerRows.value.slice(start, start + decisionPagination.pageSize)
})
const stateToneChipVariant = computed(() => {
  const tone = statePanel.value?.hero?.effective_state_tone
  if (tone === 'allow') return 'success'
  if (tone === 'hold') return 'warning'
  if (tone === 'reduce') return 'danger'
  return 'muted'
})
const staleChipVariant = computed(() => (
  statePanel.value?.hero?.stale ? 'warning' : 'muted'
))
const selectedSubjectOverviewRow = computed(() => (
  subjectWorkbenchController.state.overviewRows.find((row) => row.symbol === selectedSubjectSymbol.value) || null
))
const selectedSubjectDetail = computed(() => (
  subjectWorkbenchController.state.detailMap[selectedSubjectSymbol.value] || null
))
const selectedSubjectError = computed(() => (
  subjectWorkbenchController.state.detailErrors[selectedSubjectSymbol.value] || ''
))
const selectedSubjectEntryRows = computed(() => (
  selectedSubjectDetail.value?.entries || []
))
const selectedSubjectEntryId = computed(() => (
  subjectWorkbenchRuntime.getSelectedEntryId(selectedSubjectSymbol.value)
))
const selectedSubjectSelectedEntry = computed(() => (
  subjectWorkbenchRuntime.getSelectedEntry(selectedSubjectSymbol.value)
))
const selectedSubjectSliceRows = computed(() => (
  subjectWorkbenchRuntime.getSelectedEntrySlices(selectedSubjectSymbol.value)
))
const selectedSubjectSummaryChips = computed(() => {
  if (!selectedSubjectDetail.value) return []
  return buildDetailSummaryChips(selectedSubjectDetail.value).slice(0, 5)
})
const selectedSubjectName = computed(() => (
  selectedSubjectDetail.value?.name || selectedSubjectOverviewRow.value?.name || '-'
))

watch(
  () => [decisionLedgerRows.value.length, decisionPagination.pageSize],
  () => {
    const totalPages = Math.max(1, Math.ceil(decisionLedgerRows.value.length / decisionPagination.pageSize))
    if (decisionPagination.page > totalPages) {
      decisionPagination.page = totalPages
    }
  },
  { immediate: true },
)

const resolveErrorMessage = (error, fallback) => {
  const responseMessage = error?.response?.data?.error
  const directMessage = error?.message
  return responseMessage || directMessage || fallback
}

const decisionStatusChipVariant = (tone) => (
  tone === 'allow' ? 'success' : 'danger'
)

const decisionRowClassName = ({ row }) => (
  row?.tone === 'reject' ? 'position-decision-row--blocked' : ''
)

const ruleStatusChipVariant = (allowed) => (
  allowed ? 'success' : 'danger'
)

const handleDecisionPageChange = (page) => {
  decisionPagination.page = page
}

const handleDecisionPageSizeChange = (pageSize) => {
  decisionPagination.pageSize = pageSize
  decisionPagination.page = 1
}

const handleSelectedEntryChange = (row) => {
  const entryId = row?.entry_id
  if (!selectedSubjectSymbol.value || !entryId) return
  subjectWorkbenchRuntime.selectEntry(selectedSubjectSymbol.value, entryId)
}

const handleSelectedSubjectChange = (symbol) => {
  selectedSubjectSymbol.value = String(symbol || '').trim()
}

const loadDashboard = async () => {
  loading.value = true
  pageError.value = ''

  const subjectOverviewPromise = subjectWorkbenchRuntime.refreshOverview()
  const [dashboardResult] = await Promise.allSettled([
    positionManagementApi.getDashboard(),
  ])

  if (dashboardResult.status === 'fulfilled') {
    const payload = readDashboardPayload(
      dashboardResult.value,
      {},
    )
    dashboard.value = payload
  } else {
    pageError.value = resolveErrorMessage(
      dashboardResult.reason,
      '加载仓位管理面板失败',
    )
  }

  await subjectOverviewPromise
  loading.value = false
}

onMounted(() => {
  loadDashboard()
})
</script>

<style scoped>
.position-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.position-workbench-grid {
  --position-workbench-left-width: 1.18fr;
  --position-workbench-right-width: 0.94fr;
  display: grid;
  grid-template-columns:
    minmax(0, var(--position-workbench-left-width))
    minmax(0, var(--position-workbench-right-width));
  gap: 12px;
  align-items: stretch;
  flex: 1 1 auto;
  min-height: 0;
}

.position-workbench-column {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
  min-height: 0;
}

.position-workbench-column--left,
.position-workbench-column--right {
  display: grid;
  grid-template-rows: repeat(2, minmax(0, 1fr));
  min-height: 0;
  overflow: hidden;
}

.position-workbench-column > .workbench-panel,
.position-subject-overview-host {
  min-height: 0;
}

.position-state-panel,
.position-subject-overview-host,
.position-selection-panel,
.position-decision-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.position-selection-panel {
  overflow: hidden;
}

.position-panel-body {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  flex-direction: column;
  gap: 6px;
  overflow: hidden;
}

.position-state-scroll {
  min-width: 0;
  padding-right: 4px;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-gutter: stable both-edges;
}

.position-state-grid {
  display: grid;
  gap: 4px;
}

.position-state-grid--compact {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  align-items: stretch;
}

.position-metric-grid,
.position-meta-grid {
  display: contents;
}

.position-metric-card,
.position-meta-card {
  min-height: 72px;
}

.position-metric-card span,
.position-meta-card span {
  color: #909399;
  font-size: 11px;
}

.position-metric-card strong,
.position-meta-card strong {
  display: block;
  margin-top: 2px;
  color: #303133;
  line-height: 1.35;
}

.position-metric-card strong {
  font-size: 15px;
  max-height: calc(1.35em * 2);
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
}

.position-meta-card strong {
  font-size: 11px;
  word-break: break-all;
}

.position-rule-card p {
  margin: 4px 0 0;
  color: #606266;
  font-size: 10px;
  line-height: 1.35;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
}

.position-panel-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 2px;
}

.position-panel-section__title,
.position-selection-section__title {
  color: #21405e;
  font-size: 13px;
  font-weight: 600;
}

.position-selection-panel__body {
  display: grid;
  grid-template-rows: repeat(2, minmax(0, 1fr));
  gap: 10px;
  flex: 1 1 auto;
  min-height: 0;
}

.position-selection-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
}

.position-selection-table-wrap {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.position-selection-entry-table,
.position-selection-slice-table {
  height: 100%;
}

.position-selection-entry-table :deep(.el-input-number),
.position-selection-slice-table :deep(.el-input-number) {
  width: 100%;
}

.position-selection-entry-table :deep(.el-table__body tr.current-row > td.el-table__cell) {
  background: #eef5ff;
}

.position-selection-entry-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.position-selection-entry-cell--inline {
  flex-direction: row;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.position-selection-entry-cell strong {
  color: #21405e;
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.position-selection-entry-cell span,
.position-selection-inline-empty {
  color: #68839d;
  font-size: 12px;
  line-height: 1.45;
}

.position-selection-entry-cell--inline span {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.position-selection-cell__nowrap {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  vertical-align: middle;
}

.position-selection-entry-table :deep(.el-table__header .cell),
.position-selection-slice-table :deep(.el-table__header .cell) {
  white-space: nowrap;
}

.position-decision-table-wrap {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.position-decision-table {
  height: 100%;
}

.position-decision-table :deep(.el-table__cell) {
  padding-top: 6px;
  padding-bottom: 6px;
  vertical-align: middle;
}

.position-decision-table :deep(.el-table__header .cell) {
  white-space: nowrap;
}

.position-decision-table :deep(.cell) {
  white-space: nowrap;
}

.position-decision-table :deep(.el-table__body tr.position-decision-row--blocked > td.el-table__cell) {
  background: #fff7f5;
}

.position-decision-table :deep(.el-table__body tr.position-decision-row--blocked:hover > td.el-table__cell) {
  background: #fff1ed;
}

.position-decision-cell-strong {
  color: #21405e;
}

.runtime-empty-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 120px;
  border: 1px dashed #dbe1ea;
  border-radius: 12px;
  background: #f8fbff;
  color: #68839d;
}

.runtime-ledger {
  display: flex;
  flex-direction: column;
  flex: 0 0 auto;
  min-height: 0;
  overflow: auto;
  border: 1px solid #e5edf5;
  border-radius: 12px;
  background: #fff;
}

.runtime-ledger__header,
.runtime-ledger__row {
  display: grid;
  align-items: center;
  gap: 8px;
  min-width: max-content;
  padding: 8px 10px;
  font-size: 12px;
}

.runtime-ledger__header {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #f6f9fc;
  color: #68839d;
  border-bottom: 1px solid #e5edf5;
}

.runtime-ledger__row {
  border-top: 1px solid #eef3f8;
  background: transparent;
}

.runtime-ledger__row:hover {
  background: #f8fbff;
}

.runtime-ledger__row--blocked {
  background: #fff7f5;
}

.runtime-ledger__row--blocked:hover {
  background: #fff1ed;
}

.runtime-position-decision-ledger {
  --position-decision-ledger-row-height: 40px;
  max-height: calc(var(--position-decision-ledger-row-height) * 15 + 2px);
}

.runtime-position-decision-ledger :is(.runtime-ledger__header, .runtime-ledger__row) {
  min-height: var(--position-decision-ledger-row-height);
}

.runtime-position-decision-ledger__grid {
  grid-template-columns:
    148px
    180px
    72px
    88px
    120px
    188px
    112px
    140px
    86px
    118px
    118px
    156px
    156px
    92px
    108px
    144px
    144px
    minmax(260px, 1.25fr);
}

.runtime-position-rule-ledger :is(.runtime-ledger__header, .runtime-ledger__row) {
  min-height: 34px;
  min-width: 0;
  width: 100%;
}

.runtime-position-rule-ledger__grid {
  grid-template-columns: 102px 80px 136px minmax(0, 1fr);
}

.runtime-position-rule-ledger {
  overflow: hidden;
}

.runtime-position-rule-ledger__description {
  line-height: 1.45;
  white-space: normal;
  word-break: break-word;
}

.runtime-ledger__cell {
  min-width: 0;
  color: #35506c;
}

.runtime-ledger__cell--truncate {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.runtime-ledger__cell--strong {
  color: #21405e;
  font-weight: 600;
}

.runtime-ledger__cell--mono {
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12px;
}

.runtime-ledger__cell--number {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.runtime-ledger__cell--status {
  overflow: visible;
}

.runtime-inline-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 76px;
  gap: 0;
  padding: 4px 8px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
}

.position-ledger-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

@media (max-width: 1680px) {
  .position-workbench-grid {
    grid-template-columns:
      minmax(0, 1fr)
      minmax(0, 1fr);
  }
}

@media (max-width: 1260px) {
  .position-workbench-grid,
  .position-state-grid--compact {
    grid-template-columns: 1fr;
  }

  .position-workbench-column--left,
  .position-workbench-column--right,
  .position-selection-panel__body {
    display: flex;
    flex-direction: column;
  }
}
</style>
