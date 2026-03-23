<template>
  <div class="workbench-page position-page">
    <MyHeader />

    <div class="workbench-body position-body" v-loading="loading">
      <section class="workbench-toolbar">
        <div class="workbench-toolbar__header">
          <div class="workbench-title-group">
            <div class="workbench-page-title">仓位管理</div>
            <div class="workbench-page-meta">
              <span>最近决策与上下文统一收口到一张高密度 ledger，缩放后优先保持信息完整与滚动可读。</span>
              <span>/</span>
              <span>配置更新时间 {{ configUpdatedAt }}</span>
              <span>/</span>
              <span>更新人 {{ configUpdatedBy }}</span>
            </div>
          </div>

          <div class="workbench-toolbar__actions">
            <el-button @click="loadDashboard">刷新</el-button>
          </div>
        </div>

        <div class="workbench-summary-row">
          <span class="workbench-summary-chip" :class="stateToneChipClass">
            当前状态 <strong>{{ statePanel.hero.effective_state_label }}</strong>
          </span>
          <span class="workbench-summary-chip" :class="staleChipClass">
            {{ statePanel.hero.stale_label }}
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--muted">
            raw state <strong>{{ statePanel.hero.raw_state_label }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--muted">
            最近决策 <strong>{{ decisionLedgerRows.length }} 条</strong>
          </span>
        </div>
      </section>

      <el-alert
        v-if="pageError"
        class="workbench-alert"
        type="error"
        :title="pageError"
        show-icon
        :closable="false"
      />

      <section class="workbench-panel">
        <div class="workbench-panel__header">
          <div class="workbench-title-group">
            <div class="workbench-panel__title">最近决策与上下文</div>
            <p class="workbench-panel__desc">复用 runtime-observability 的 dense ledger 语法，一次展示决策主信息、仓位上下文、trace 与附加字段；宽度不足时直接横向滚动。</p>
          </div>
        </div>

        <div class="workbench-summary-row">
          <span class="workbench-summary-chip workbench-summary-chip--muted">
            当前页 <strong>{{ pagedDecisionRows.length }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--muted">
            默认分页 <strong>{{ decisionPagination.pageSize }} / 页</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--muted">
            当前页码 <strong>{{ decisionPagination.page }}</strong>
          </span>
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
              <span class="runtime-inline-status" :class="resolveDecisionStatusClass(row.tone)">
                {{ row.allowed_label }}
              </span>
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
      </section>

      <section class="position-lower-grid">
        <div class="position-lower-column">
          <section class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">当前仓位状态</div>
                <p class="workbench-panel__desc">effective state、stale 语义和资产摘要仍由服务端按真实 PositionPolicy 汇总；规则矩阵已并入本卡片。</p>
              </div>
            </div>

            <div class="workbench-summary-row">
              <span class="workbench-summary-chip" :class="stateToneChipClass">
                {{ statePanel.hero.effective_state_label }}
              </span>
              <span class="workbench-summary-chip" :class="staleChipClass">
                {{ statePanel.hero.stale_label }}
              </span>
              <span class="workbench-summary-chip workbench-summary-chip--muted">
                raw state <strong>{{ statePanel.hero.raw_state_label }}</strong>
              </span>
            </div>

            <div class="position-rule-hint">
              <strong>{{ statePanel.hero.matched_rule_title }}</strong>
              <p>{{ statePanel.hero.matched_rule_detail }}</p>
            </div>

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
                    <span class="runtime-inline-status" :class="resolveRuleStatusClass(row.allowed)">
                      {{ row.allowed_label }}
                    </span>
                  </span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--mono runtime-ledger__cell--truncate" :title="row.reason_code">{{ row.reason_code }}</span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--truncate" :title="row.reason_text">{{ row.reason_text }}</span>
                </div>
              </div>
            </div>
          </section>
        </div>

        <div class="position-lower-column">
          <section class="workbench-panel position-config-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">参数 inventory</div>
                <p class="workbench-panel__desc">把真正生效的阈值、代码默认值和系统连接参数合并到一张表，同时保留说明和可编辑边界。</p>
              </div>
            </div>

            <el-table :data="inventoryRows" size="small" border class="position-config-table">
              <el-table-column prop="group_label" label="分组" min-width="120" show-overflow-tooltip />
              <el-table-column label="参数" min-width="220">
                <template #default="{ row }">
                  <div class="inventory-parameter-cell">
                    <strong>{{ row.label }}</strong>
                    <span>{{ row.source_label }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="当前值" min-width="180">
                <template #default="{ row }">
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
                </template>
              </el-table-column>
              <el-table-column prop="description" label="说明" min-width="260" show-overflow-tooltip />
            </el-table>

            <div class="position-edit-footer">
              <span class="workbench-muted">当前开放账户阈值和全局单标的实时仓位上限保持可编辑，其余参数继续只读展示。</span>
              <el-button type="primary" :loading="saving" @click="saveThresholds">保存阈值</el-button>
            </div>
          </section>
        </div>

        <div class="position-lower-column">
          <section class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
            <div class="workbench-panel__title">单标的仓位上限覆盖</div>
                <p class="workbench-panel__desc">右栏只保留单标的仓位上限覆盖。并排展示券商同步仓位、订单推断仓位和 stock_fills 视图；覆盖值可直接编辑，数量不一致或超限时高亮。</p>
              </div>
            </div>

            <div class="workbench-summary-row">
              <span class="workbench-summary-chip workbench-summary-chip--muted">
                单独设置 <strong>{{ overrideSymbolCount }}</strong>
              </span>
              <span class="workbench-summary-chip workbench-summary-chip--warning">
                仓位不一致 <strong>{{ mismatchSymbolCount }}</strong>
              </span>
              <span class="workbench-summary-chip workbench-summary-chip--warning">
                已超限 <strong>{{ blockedSymbolCount }}</strong>
              </span>
            </div>

            <div v-if="symbolLimitRows.length" class="runtime-ledger runtime-position-symbol-limit-ledger">
              <div class="runtime-ledger__header runtime-position-symbol-limit-ledger__grid">
                <span>标的</span>
                <span>券商仓位</span>
                <span>推断仓位</span>
                <span>stock_fills仓位</span>
                <span>默认值</span>
                <span>覆盖值</span>
                <span>有效值</span>
                <span>一致性</span>
                <span>门禁</span>
                <span>操作</span>
              </div>

              <div
                v-for="row in symbolLimitRows"
                :key="row.symbol"
                class="runtime-ledger__row runtime-position-symbol-limit-ledger__grid"
                :class="{
                  'runtime-ledger__row--blocked': row.blocked,
                  'runtime-ledger__row--inconsistent': row.quantity_mismatch,
                }"
              >
                <div class="runtime-ledger__cell position-limit-symbol">
                  <strong>{{ row.symbol }}</strong>
                  <span>{{ row.name }}</span>
                </div>
                <div class="runtime-ledger__cell position-source-cell" :title="row.broker_position_source_label">
                  <strong>{{ row.broker_position_label }}</strong>
                  <span>{{ row.broker_position_source_label }}</span>
                </div>
                <div class="runtime-ledger__cell position-source-cell" :title="row.inferred_position_source_label">
                  <strong>{{ row.inferred_position_label }}</strong>
                  <span>{{ row.inferred_position_source_label }}</span>
                </div>
                <div class="runtime-ledger__cell position-source-cell" :title="row.legacy_position_source_label">
                  <strong>{{ row.legacy_position_label }}</strong>
                  <span>{{ row.legacy_position_source_label }}</span>
                </div>
                <span class="runtime-ledger__cell runtime-ledger__cell--number">{{ row.default_limit_label }}</span>
                <div class="runtime-ledger__cell position-symbol-limit-input">
                  <el-input-number
                    v-model="symbolLimitDrafts[row.symbol]"
                    size="small"
                    :min="0"
                    :step="10000"
                    controls-position="right"
                  />
                </div>
                <span class="runtime-ledger__cell runtime-ledger__cell--number">{{ row.effective_limit_label }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--status" :title="row.consistency_detail_label">
                  <span class="runtime-inline-status" :class="resolvePositionConsistencyStatusClass(row.quantity_mismatch)">
                    {{ row.consistency_label }}
                  </span>
                </span>
                <span class="runtime-ledger__cell runtime-ledger__cell--status">
                  <span class="runtime-inline-status" :class="resolveSymbolLimitStatusClass(row.blocked)">
                    {{ row.blocked_label }}
                  </span>
                </span>
                <div class="runtime-ledger__cell position-symbol-limit-actions">
                  <el-button
                    type="primary"
                    text
                    :loading="Boolean(symbolLimitSaving[row.symbol])"
                    @click="saveSymbolLimit(row)"
                  >
                    保存覆盖
                  </el-button>
                  <el-button
                    text
                    :disabled="!canResetSymbolLimit(row)"
                    @click="resetSymbolLimit(row)"
                  >
                    恢复默认
                  </el-button>
                </div>
              </div>
            </div>

            <div v-else class="runtime-empty-panel">
              <strong>当前没有可展示的单标的仓位上限行</strong>
            </div>
          </section>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import MyHeader from '@/views/MyHeader.vue'
import { positionManagementApi } from '@/api/positionManagementApi'
import {
  buildInventoryRows,
  buildRecentDecisionLedgerRows,
  buildRuleMatrix,
  buildStatePanel,
  buildSymbolLimitRows,
  readDashboardPayload,
} from './positionManagement.mjs'

const loading = ref(false)
const saving = ref(false)
const pageError = ref('')
const dashboard = ref({})

const editableForm = reactive({
  allow_open_min_bail: 0,
  holding_only_min_bail: 0,
  single_symbol_position_limit: 0,
})

const decisionPagination = reactive({
  page: 1,
  pageSize: 100,
})

const symbolLimitDrafts = reactive({})
const symbolLimitSaving = reactive({})

const inventoryRows = computed(() => buildInventoryRows(dashboard.value))
const symbolLimitRows = computed(() => buildSymbolLimitRows(dashboard.value))
const statePanel = computed(() => buildStatePanel(dashboard.value))
const ruleMatrix = computed(() => buildRuleMatrix(dashboard.value))
const decisionLedgerRows = computed(() => buildRecentDecisionLedgerRows(dashboard.value))
const pagedDecisionRows = computed(() => {
  const start = (decisionPagination.page - 1) * decisionPagination.pageSize
  return decisionLedgerRows.value.slice(start, start + decisionPagination.pageSize)
})
const configUpdatedAt = computed(() => dashboard.value?.config?.updated_at || '未配置')
const configUpdatedBy = computed(() => dashboard.value?.config?.updated_by || 'unknown')
const blockedSymbolCount = computed(() => symbolLimitRows.value.filter((row) => row.blocked).length)
const mismatchSymbolCount = computed(() => symbolLimitRows.value.filter((row) => row.quantity_mismatch).length)
const overrideSymbolCount = computed(() => symbolLimitRows.value.filter((row) => row.using_override).length)
const stateToneChipClass = computed(() => {
  const tone = statePanel.value?.hero?.effective_state_tone
  if (tone === 'allow') return 'workbench-summary-chip--success'
  if (tone === 'hold') return 'workbench-summary-chip--warning'
  if (tone === 'reduce') return 'workbench-summary-chip--danger'
  return 'workbench-summary-chip--muted'
})
const staleChipClass = computed(() => (
  statePanel.value?.hero?.stale ? 'workbench-summary-chip--warning' : 'workbench-summary-chip--muted'
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

const resolveDecisionStatusClass = (tone) => (
  tone === 'allow' ? 'runtime-inline-status--success' : 'runtime-inline-status--failed'
)

const resolveRuleStatusClass = (allowed) => (
  allowed ? 'runtime-inline-status--success' : 'runtime-inline-status--failed'
)

const resolveSymbolLimitStatusClass = (blocked) => (
  blocked ? 'runtime-inline-status--failed' : 'runtime-inline-status--success'
)

const resolvePositionConsistencyStatusClass = (quantityMismatch) => (
  quantityMismatch ? 'runtime-inline-status--warning' : 'runtime-inline-status--success'
)

const handleDecisionPageChange = (page) => {
  decisionPagination.page = page
}

const handleDecisionPageSizeChange = (pageSize) => {
  decisionPagination.pageSize = pageSize
  decisionPagination.page = 1
}

const syncEditableForm = () => {
  const thresholds = dashboard.value?.config?.thresholds || {}
  editableForm.allow_open_min_bail = Number(thresholds.allow_open_min_bail || 0)
  editableForm.holding_only_min_bail = Number(thresholds.holding_only_min_bail || 0)
  editableForm.single_symbol_position_limit = Number(thresholds.single_symbol_position_limit || 0)
}

const syncSymbolLimitDrafts = (rows = []) => {
  const symbols = new Set(rows.map((row) => row.symbol))
  Object.keys(symbolLimitDrafts).forEach((symbol) => {
    if (!symbols.has(symbol)) delete symbolLimitDrafts[symbol]
  })
  Object.keys(symbolLimitSaving).forEach((symbol) => {
    if (!symbols.has(symbol)) delete symbolLimitSaving[symbol]
  })
  rows.forEach((row) => {
    symbolLimitDrafts[row.symbol] = row.override_limit_value
    symbolLimitSaving[row.symbol] = false
  })
}

const loadDashboard = async () => {
  loading.value = true
  pageError.value = ''
  try {
    const payload = readDashboardPayload(
      await positionManagementApi.getDashboard(),
      {},
    )
    dashboard.value = payload
    syncEditableForm()
    syncSymbolLimitDrafts(buildSymbolLimitRows(payload))
  } catch (error) {
    pageError.value = resolveErrorMessage(error, '加载仓位管理面板失败')
  } finally {
    loading.value = false
  }
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

const canResetSymbolLimit = (row) => {
  const draft = Number(symbolLimitDrafts[row?.symbol])
  return Boolean(row?.using_override) || Number.isFinite(draft)
}

const saveSymbolLimit = async (row) => {
  const symbol = String(row?.symbol || '').trim()
  if (!symbol) return
  const parsed = Number(symbolLimitDrafts[symbol])
  if (!Number.isFinite(parsed) || parsed <= 0) {
    ElMessage.error(`请先为 ${symbol} 填写有效的覆盖值`)
    return
  }

  symbolLimitSaving[symbol] = true
  try {
    await positionManagementApi.updateSymbolLimit(symbol, {
      limit: parsed,
      use_default: false,
      updated_by: 'web-ui',
    })
    ElMessage.success(`${symbol} 覆盖值已保存`)
    await loadDashboard()
  } catch (error) {
    ElMessage.error(resolveErrorMessage(error, `保存 ${symbol} 覆盖值失败`))
  } finally {
    symbolLimitSaving[symbol] = false
  }
}

const resetSymbolLimit = async (row) => {
  const symbol = String(row?.symbol || '').trim()
  if (!symbol) return

  symbolLimitSaving[symbol] = true
  try {
    await positionManagementApi.updateSymbolLimit(symbol, {
      use_default: true,
      updated_by: 'web-ui',
    })
    ElMessage.success(`${symbol} 已恢复默认值`)
    await loadDashboard()
  } catch (error) {
    ElMessage.error(resolveErrorMessage(error, `恢复 ${symbol} 默认值失败`))
  } finally {
    symbolLimitSaving[symbol] = false
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
  overflow: auto;
}

.position-lower-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.12fr) minmax(0, 0.96fr) minmax(0, 1.04fr);
  gap: 12px;
  align-items: start;
}

.position-lower-column {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.position-config-table {
  margin-top: 6px;
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
  margin-top: 12px;
}

.inventory-parameter-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.inventory-parameter-cell strong {
  color: #303133;
}

.inventory-parameter-cell span,
.inventory-value {
  color: #606266;
  font-size: 12px;
  line-height: 1.5;
}

.position-rule-hint {
  padding: 10px 12px;
  border: 1px dashed #dbe1ea;
  border-radius: 8px;
  background: #f8fafc;
}

.position-rule-hint strong {
  color: #303133;
}

.position-rule-hint p {
  margin: 6px 0 0;
  color: #606266;
  font-size: 12px;
  line-height: 1.5;
}

.position-metric-grid,
.position-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.position-metric-card span,
.position-meta-card span {
  color: #909399;
  font-size: 12px;
}

.position-metric-card strong,
.position-meta-card strong {
  display: block;
  margin-top: 8px;
  color: #303133;
  line-height: 1.35;
}

.position-metric-card strong {
  font-size: 18px;
}

.position-meta-card strong {
  font-size: 13px;
  word-break: break-all;
}

.position-panel-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
}

.position-panel-section__title {
  color: #21405e;
  font-size: 13px;
  font-weight: 600;
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

.runtime-ledger__row--inconsistent {
  background: #fff9ed;
}

.runtime-ledger__row--inconsistent:hover {
  background: #fff4de;
}

.runtime-ledger__row--blocked.runtime-ledger__row--inconsistent {
  background: #fff3ea;
}

.runtime-ledger__row--blocked.runtime-ledger__row--inconsistent:hover {
  background: #ffeade;
}

.runtime-position-decision-ledger {
  --position-decision-ledger-row-height: 40px;
  max-height: calc(var(--position-decision-ledger-row-height) * 11 + 2px);
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

.runtime-position-rule-ledger {
  max-height: 198px;
}

.runtime-position-rule-ledger__grid {
  grid-template-columns: 120px 88px 148px minmax(240px, 1fr);
}

.runtime-position-symbol-limit-ledger {
  --position-symbol-limit-ledger-row-height: 54px;
  max-height: calc(var(--position-symbol-limit-ledger-row-height) * 11 + 2px);
}

.runtime-position-symbol-limit-ledger :is(.runtime-ledger__header, .runtime-ledger__row) {
  min-height: var(--position-symbol-limit-ledger-row-height);
}

.runtime-position-symbol-limit-ledger__grid {
  grid-template-columns:
    170px
    220px
    220px
    220px
    120px
    168px
    120px
    108px
    92px
    160px;
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
  padding: 2px 10px;
  border: 1px solid transparent;
  border-radius: 999px;
  box-sizing: border-box;
  font-size: 12px;
  font-weight: 600;
  line-height: 20px;
}

.runtime-inline-status--success {
  border-color: #c5ebd1;
  background: #eefbf3;
  color: #18794e;
}

.runtime-inline-status--failed {
  border-color: #ffd1cc;
  background: #fff1f0;
  color: #b42318;
}

.runtime-inline-status--warning {
  border-color: #f7d8a8;
  background: #fff7e8;
  color: #9a5b00;
}

.position-ledger-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.position-limit-symbol {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.position-limit-symbol strong {
  color: #21405e;
}

.position-limit-symbol span {
  color: #68839d;
  font-size: 12px;
}

.position-source-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.position-source-cell strong {
  color: #21405e;
  line-height: 1.35;
}

.position-source-cell span {
  color: #68839d;
  font-size: 11px;
  line-height: 1.3;
}

.position-symbol-limit-input :deep(.el-input-number) {
  width: 100%;
}

.position-symbol-limit-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

@media (max-width: 1600px) {
  .position-lower-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1260px) {
  .position-lower-grid,
  .position-metric-grid,
  .position-meta-grid {
    grid-template-columns: 1fr;
  }
}
</style>
