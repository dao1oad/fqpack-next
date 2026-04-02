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

              <div class="position-panel-section">
                <div class="position-panel-section__header">
                  <div class="workbench-title-group">
                    <div class="position-panel-section__title">参数 inventory</div>
                  </div>
                </div>

                <div class="workbench-summary-row">
                  <StatusChip variant="muted">
                    配置时间 <strong>{{ configUpdatedAt }}</strong>
                  </StatusChip>
                  <StatusChip variant="muted">
                    更新人 <strong>{{ configUpdatedBy }}</strong>
                  </StatusChip>
                </div>

                <el-table :data="inventoryRows" size="small" border class="position-config-table">
                  <el-table-column prop="group_label" label="分组" min-width="108" show-overflow-tooltip />
                  <el-table-column label="参数" min-width="188">
                    <template #default="{ row }">
                      <div class="inventory-parameter-cell">
                        <strong>{{ row.label }}</strong>
                        <span>{{ row.source_label }}</span>
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column label="当前值" min-width="184">
                    <template #default="{ row }">
                      <div class="inventory-value-cell">
                        <el-input-number
                          v-if="row.key === 'allow_open_min_bail'"
                          v-model="editableForm.allow_open_min_bail"
                          :min="0"
                          :step="10000"
                          controls-position="right"
                        />
                        <el-input-number
                          v-else-if="row.key === 'holding_only_min_bail'"
                          v-model="editableForm.holding_only_min_bail"
                          :min="0"
                          :step="10000"
                          controls-position="right"
                        />
                        <el-input-number
                          v-else-if="row.key === 'single_symbol_position_limit'"
                          v-model="editableForm.single_symbol_position_limit"
                          :min="0"
                          :step="10000"
                          controls-position="right"
                        />
                        <span v-else class="inventory-value">{{ row.value_label }}</span>
                        <span v-if="row.editable" class="inventory-inline-hint">
                          当前生效：{{ row.value_label }}
                        </span>
                      </div>
                    </template>
                  </el-table-column>
                </el-table>

                <div class="position-edit-footer">
                  <span class="workbench-muted">当前开放账户阈值和全局单标的默认持仓上限保持可编辑，其余参数继续只读展示。</span>
                  <el-button type="primary" :loading="saving" @click="saveThresholds">保存阈值</el-button>
                </div>
              </div>
            </div>
          </WorkbenchDetailPanel>

          <PositionReconciliationPanel
            class="position-reconciliation-panel"
            :overview="reconciliationOverview"
            :loading="reconciliationLoading"
            :error="reconciliationError"
          />
        </div>

        <div class="position-workbench-column position-workbench-column--middle" aria-label="标的总览">
          <PositionSubjectOverviewPanel class="position-subject-overview-host" :workbench="subjectWorkbenchRuntime" :selected-symbol="selectedSubjectSymbol" @symbol-select="handleSelectedSubjectChange" />
        </div>

        <div class="position-workbench-column position-workbench-column--right">
          <WorkbenchLedgerPanel class="position-selection-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">选中标的工作区</div>
                <div class="workbench-panel__desc">
                  当前显示中栏选中标的的聚合买入列表 / 按持仓入口止损，以及切片明细。
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
                    size="small"
                    border
                    height="100%"
                    class="position-selection-entry-table"
                  >
                    <el-table-column label="入口" width="132">
                      <template #default="{ row }">
                        <div class="position-selection-entry-cell">
                          <strong>{{ row.entryDisplayLabel }}</strong>
                          <span>{{ row.entryIdLabel }}</span>
                        </div>
                      </template>
                    </el-table-column>

                    <el-table-column label="买入摘要" min-width="220">
                      <template #default="{ row }">
                        <div class="position-selection-entry-cell">
                          <span>{{ row.entrySummaryLines?.[0] || '-' }}</span>
                          <span>{{ row.entrySummaryLines?.[1] || '-' }}</span>
                        </div>
                      </template>
                    </el-table-column>

                    <el-table-column label="聚合买入" min-width="220">
                      <template #default="{ row }">
                        <div class="position-selection-entry-cell">
                          <span>{{ formatAggregationMembers(row.aggregation_members) }}</span>
                        </div>
                      </template>
                    </el-table-column>

                    <el-table-column label="止损价" width="110">
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

                    <el-table-column label="启用" width="86" align="center">
                      <template #default="{ row }">
                        <el-switch
                          v-if="subjectWorkbenchRuntime.state.stoplossDrafts[selectedSubjectSymbol]?.[row.entry_id]"
                          v-model="subjectWorkbenchRuntime.state.stoplossDrafts[selectedSubjectSymbol][row.entry_id].enabled"
                        />
                        <span v-else class="position-selection-inline-empty">-</span>
                      </template>
                    </el-table-column>

                    <el-table-column label="保存" width="92" fixed="right">
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
                    <el-table-column label="入口" width="132">
                      <template #default="{ row }">
                        <div class="position-selection-entry-cell">
                          <strong>{{ row.entryDisplayLabel }}</strong>
                          <span>{{ row.entry_id }}</span>
                        </div>
                      </template>
                    </el-table-column>
                    <el-table-column label="序号" width="72" align="center">
                      <template #default="{ row }">
                        <span class="workbench-code">{{ formatInteger(row.slice_seq) }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column label="守护价" width="92" align="right">
                      <template #default="{ row }">
                        <span class="workbench-code">{{ formatPrice(row.guardian_price) }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column label="原始数量" width="96" align="right">
                      <template #default="{ row }">
                        <span class="workbench-code">{{ formatInteger(row.original_quantity) }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column label="剩余数量" width="96" align="right">
                      <template #default="{ row }">
                        <span class="workbench-code">{{ formatInteger(row.remaining_quantity) }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column label="剩余市值" min-width="108" align="right">
                      <template #default="{ row }">
                        <span class="workbench-code">{{ formatWanAmount(row.remaining_amount) }}</span>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>
                <div v-else class="runtime-empty-panel">
                  <strong>当前没有 open 切片</strong>
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
                当前标的 <strong>{{ selectedSubjectSymbol || '全部' }}</strong>
              </StatusChip>
              <StatusChip variant="muted">
                当前页 <strong>{{ pagedDecisionRows.length }}</strong>
              </StatusChip>
              <StatusChip variant="muted">
                默认分页 <strong>{{ decisionPagination.pageSize }} / 页</strong>
              </StatusChip>
              <StatusChip variant="muted">
                当前页码 <strong>{{ decisionPagination.page }}</strong>
              </StatusChip>
            </div>

            <div v-if="pagedDecisionRows.length" class="runtime-ledger runtime-position-decision-ledger">
              <div class="runtime-ledger__header runtime-position-decision-ledger__grid">
                <span>触发时间</span>
                <span>标的</span>
                <span>动作</span>
                <span>结果</span>
                <span>门禁状态</span>
                <span>触发来源</span>
                <span>策略</span>
                <span>说明</span>
                <span>持仓标的</span>
                <span>实时市值</span>
                <span>仓位上限</span>
                <span>市值来源</span>
                <span>数量来源</span>
                <span>盈利减仓</span>
                <span>减仓模式</span>
                <span>Trace</span>
                <span>Intent</span>
                <span>附加上下文</span>
              </div>

              <div
                v-for="row in pagedDecisionRows"
                :key="row.selection_key"
                class="runtime-ledger__row runtime-position-decision-ledger__grid"
                :class="{ 'runtime-ledger__row--blocked': row.tone === 'reject' }"
              >
                <span class="runtime-ledger__cell runtime-ledger__cell--mono">{{ row.evaluated_at_label }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--strong runtime-ledger__cell--truncate" :title="row.symbol_display">{{ row.symbol_display }}</span>
                <span class="runtime-ledger__cell">{{ row.action_label }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--status">
                  <StatusChip class="runtime-inline-status" :variant="decisionStatusChipVariant(row.tone)">
                    {{ row.allowed_label }}
                  </StatusChip>
                </span>
                <span class="runtime-ledger__cell">{{ row.state_label }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--truncate" :title="row.source_display">{{ row.source_display }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--truncate" :title="row.strategy_label">{{ row.strategy_label }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--truncate" :title="row.reason_display">{{ row.reason_display }}</span>
                <span class="runtime-ledger__cell">{{ row.holding_symbol_display }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--number">{{ row.symbol_market_value_label }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--number">{{ row.symbol_position_limit_label }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--truncate" :title="row.market_value_source_display">{{ row.market_value_source_display }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--truncate" :title="row.quantity_source_display">{{ row.quantity_source_display }}</span>
                <span class="runtime-ledger__cell">{{ row.force_profit_reduce_display }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--truncate" :title="row.profit_reduce_mode_display">{{ row.profit_reduce_mode_display }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--mono runtime-ledger__cell--truncate" :title="row.trace_display">{{ row.trace_display }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--mono runtime-ledger__cell--truncate" :title="row.intent_display">{{ row.intent_display }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--truncate" :title="row.extra_context_label">{{ row.extra_context_label }}</span>
              </div>
            </div>

            <div v-else class="runtime-empty-panel">
              <strong>{{ selectedSubjectSymbol ? '当前标的暂无最近决策记录' : '暂无最近决策记录' }}</strong>
            </div>

            <div class="position-ledger-pagination">
              <el-pagination
                background
                layout="total,sizes,prev,pager,next"
                :current-page="decisionPagination.page"
                :page-size="decisionPagination.pageSize"
                :total="filteredDecisionLedgerRows.length"
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
import PositionReconciliationPanel from '../components/position-management/PositionReconciliationPanel.vue'
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
  buildInventoryRows,
  buildRecentDecisionLedgerRows,
  buildRuleMatrix,
  buildStatePanel,
  readDashboardPayload,
} from './positionManagement.mjs'
import { formatBeijingTimestamp } from '../tool/beijingTime.mjs'
import { readPositionReconciliationPayload } from './positionReconciliation.mjs'

const loading = ref(false)
const saving = ref(false)
const pageError = ref('')
const dashboard = ref({})
const reconciliationOverview = ref({})
const reconciliationLoading = ref(false)
const reconciliationError = ref('')
const selectedSubjectSymbol = ref('')

const editableForm = reactive({
  allow_open_min_bail: 0,
  holding_only_min_bail: 0,
  single_symbol_position_limit: 0,
})

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

const formatAggregationMembers = (members = []) => {
  if (!Array.isArray(members) || members.length === 0) return '-'
  return members
    .map((member, index) => {
      const identifier = member.order_id || member.broker_order_key || member.slice_id || member.entry_id || `member-${index + 1}`
      return `${identifier} ${formatInteger(member.quantity)} 股`
    })
    .join(' / ')
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
  saveConfigBundle: async (symbol) => saveSubjectConfigBundle(symbol),
  saveStoploss: async (symbol, entryId) => saveSubjectStoploss(symbol, entryId),
}

const inventoryRows = computed(() => buildInventoryRows(dashboard.value))
const statePanel = computed(() => buildStatePanel(dashboard.value))
const ruleMatrix = computed(() => buildRuleMatrix(dashboard.value))
const decisionLedgerRows = computed(() => buildRecentDecisionLedgerRows(dashboard.value))
const filteredDecisionLedgerRows = computed(() => {
  if (!selectedSubjectSymbol.value) return decisionLedgerRows.value
  return decisionLedgerRows.value.filter((row) => row.symbol === selectedSubjectSymbol.value)
})
const pagedDecisionRows = computed(() => {
  const start = (decisionPagination.page - 1) * decisionPagination.pageSize
  return filteredDecisionLedgerRows.value.slice(start, start + decisionPagination.pageSize)
})
const configUpdatedAt = computed(() => formatBeijingTimestamp(dashboard.value?.config?.updated_at, '未配置'))
const configUpdatedBy = computed(() => dashboard.value?.config?.updated_by || 'unknown')
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
const selectedSubjectSliceRows = computed(() => selectedSubjectEntryRows.value.flatMap((entry) => (
  (entry.entry_slices || []).map((slice) => ({
    ...slice,
    entry_id: entry.entry_id,
    entryDisplayLabel: entry.entryDisplayLabel,
  }))
)))
const selectedSubjectSummaryChips = computed(() => {
  if (!selectedSubjectDetail.value) return []
  return buildDetailSummaryChips(selectedSubjectDetail.value).slice(0, 5)
})
const selectedSubjectName = computed(() => (
  selectedSubjectDetail.value?.name || selectedSubjectOverviewRow.value?.name || '-'
))

watch(
  () => [filteredDecisionLedgerRows.value.length, decisionPagination.pageSize],
  () => {
    const totalPages = Math.max(1, Math.ceil(filteredDecisionLedgerRows.value.length / decisionPagination.pageSize))
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

const handleSelectedSubjectChange = (symbol) => {
  selectedSubjectSymbol.value = String(symbol || '').trim()
  decisionPagination.page = 1
}

const syncEditableForm = () => {
  const thresholds = dashboard.value?.config?.thresholds || {}
  editableForm.allow_open_min_bail = Number(thresholds.allow_open_min_bail || 0)
  editableForm.holding_only_min_bail = Number(thresholds.holding_only_min_bail || 0)
  editableForm.single_symbol_position_limit = Number(thresholds.single_symbol_position_limit || 0)
}

const loadDashboard = async () => {
  loading.value = true
  reconciliationLoading.value = true
  pageError.value = ''
  reconciliationError.value = ''

  const subjectOverviewPromise = subjectWorkbenchRuntime.refreshOverview()
  const [dashboardResult, reconciliationResult] = await Promise.allSettled([
    positionManagementApi.getDashboard(),
    positionManagementApi.getReconciliation(),
  ])

  if (dashboardResult.status === 'fulfilled') {
    const payload = readDashboardPayload(
      dashboardResult.value,
      {},
    )
    dashboard.value = payload
    syncEditableForm()
  } else {
    pageError.value = resolveErrorMessage(
      dashboardResult.reason,
      '加载仓位管理面板失败',
    )
  }

  if (reconciliationResult.status === 'fulfilled') {
    reconciliationOverview.value = readPositionReconciliationPayload(
      reconciliationResult.value,
      {},
    )
  } else {
    reconciliationOverview.value = {}
    reconciliationError.value = resolveErrorMessage(
      reconciliationResult.reason,
      '加载仓位对账检查失败',
    )
  }

  await subjectOverviewPromise
  loading.value = false
  reconciliationLoading.value = false
}

const saveThresholds = async () => {
  if (editableForm.allow_open_min_bail <= editableForm.holding_only_min_bail) {
    ElMessage.error('允许开新仓最低保证金必须大于仅允许持仓内买入最低保证金')
    return
  }

  saving.value = true
  try {
    await positionManagementApi.updateConfig({
      allow_open_min_bail: editableForm.allow_open_min_bail,
      holding_only_min_bail: editableForm.holding_only_min_bail,
      single_symbol_position_limit: editableForm.single_symbol_position_limit,
      updated_by: 'web-ui',
    })
    ElMessage.success('仓位管理阈值已保存')
    await loadDashboard()
  } catch (error) {
    ElMessage.error(resolveErrorMessage(error, '保存仓位管理阈值失败'))
  } finally {
    saving.value = false
  }
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
  --position-workbench-left-width: 0.9fr;
  --position-workbench-middle-width: 1.5fr;
  --position-workbench-right-width: 1.12fr;
  display: grid;
  grid-template-columns:
    minmax(0, var(--position-workbench-left-width))
    minmax(0, var(--position-workbench-middle-width))
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
.position-reconciliation-panel,
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

.position-config-table :deep(.cell) {
  padding-top: 4px;
  padding-bottom: 4px;
}

.position-config-table :deep(.el-input-number) {
  width: 100%;
}

.position-edit-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 6px;
  padding-top: 4px;
}

.position-panel-section__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.inventory-parameter-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.inventory-parameter-cell strong {
  color: #303133;
}

.inventory-value-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.inventory-parameter-cell span,
.inventory-inline-hint,
.inventory-value {
  color: #606266;
  font-size: 12px;
  line-height: 1.5;
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

.position-selection-entry-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.position-selection-entry-cell strong {
  color: #21405e;
}

.position-selection-entry-cell span,
.position-selection-inline-empty {
  color: #68839d;
  font-size: 12px;
  line-height: 1.45;
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
      minmax(0, 1.2fr);
  }

  .position-workbench-column--right {
    grid-column: 1 / -1;
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
