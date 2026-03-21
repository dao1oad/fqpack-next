<template>
  <div class="workbench-page position-page">
    <MyHeader />

    <div class="workbench-body position-body" v-loading="loading">
      <section class="workbench-toolbar">
        <div class="workbench-toolbar__header">
          <div class="workbench-title-group">
            <div class="workbench-page-title">仓位管理</div>
            <div class="workbench-page-meta">
              <span>最近决策置顶，统一查看门禁结论、上下文语义和当前状态</span>
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
            最近决策 <strong>{{ recentDecisionRows.length }} 条</strong>
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

      <section class="position-decision-grid">
        <section class="workbench-panel">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">最近决策</div>
              <p class="workbench-panel__desc">左侧集中看最近门禁结论、触发时间、来源模块和核心摘要；点击后右侧切到该条上下文细节。</p>
            </div>
          </div>

          <div class="workbench-summary-row">
            <span class="workbench-summary-chip workbench-summary-chip--muted">
              当前选中
              <strong>{{ selectedDecision?.symbol_label || '无' }}</strong>
            </span>
            <span class="workbench-summary-chip workbench-summary-chip--muted">
              触发来源
              <strong>{{ selectedDecision?.source_module_label || '-' }}</strong>
            </span>
          </div>

          <div v-if="recentDecisionRows.length" class="position-decision-list">
            <button
              v-for="row in recentDecisionRows"
              :key="row.selection_key"
              type="button"
              class="position-decision-card"
              :class="{ 'position-decision-card--active': selectedDecisionKey === row.selection_key }"
              @click="selectedDecisionKey = row.selection_key"
            >
              <div class="position-decision-card__header">
                <div class="position-decision-card__symbol">
                  <strong>{{ row.symbol_label }}</strong>
                  <span>{{ row.symbol_name_label }}</span>
                </div>
                <span
                  class="workbench-summary-chip"
                  :class="row.tone === 'allow' ? 'workbench-summary-chip--success' : 'workbench-summary-chip--danger'"
                >
                  {{ row.allowed_label }}
                </span>
              </div>

              <div class="position-decision-card__summary">
                <div class="position-decision-card__summary-item">
                  <span>触发时间</span>
                  <strong>{{ row.evaluated_at_label }}</strong>
                </div>
                <div class="position-decision-card__summary-item">
                  <span>触发来源</span>
                  <strong>{{ row.source_module_label }}</strong>
                </div>
                <div class="position-decision-card__summary-item">
                  <span>门禁状态</span>
                  <strong>{{ row.state_label }}</strong>
                </div>
                <div class="position-decision-card__summary-item">
                  <span>动作</span>
                  <strong>{{ row.action_label }}</strong>
                </div>
              </div>

              <div class="position-decision-card__reason">{{ row.reason_text }}</div>
            </button>
          </div>

          <div v-else class="workbench-empty">暂无最近决策记录。</div>
        </section>

        <section class="workbench-panel">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">决策上下文详情</div>
              <p class="workbench-panel__desc">右侧把当前选中决策拆成中文语义表格，尽量把来源、门禁原因、仓位上下文与追踪字段一次看全。</p>
            </div>
          </div>

          <div v-if="selectedDecision" class="workbench-summary-row">
            <span class="workbench-summary-chip workbench-summary-chip--muted">
              标的 <strong>{{ selectedDecision.symbol_label }}</strong>
            </span>
            <span class="workbench-summary-chip workbench-summary-chip--muted">
              策略 <strong>{{ selectedDecision.strategy_label }}</strong>
            </span>
            <span
              class="workbench-summary-chip"
              :class="selectedDecision.tone === 'allow' ? 'workbench-summary-chip--success' : 'workbench-summary-chip--danger'"
            >
              {{ selectedDecision.allowed_label }}
            </span>
          </div>

          <el-table
            v-if="decisionDetailRows.length"
            :data="decisionDetailRows"
            size="small"
            border
            class="position-decision-detail-table"
          >
            <el-table-column prop="label" label="上下文项" min-width="180" />
            <el-table-column prop="value" label="中文语义" min-width="360" show-overflow-tooltip />
          </el-table>

          <div v-else class="workbench-empty">选择左侧最近决策后，可在这里查看该条门禁决策的完整上下文。</div>
        </section>
      </section>

      <section class="position-lower-grid">
        <div class="position-lower-column">
          <section class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">当前仓位状态</div>
                <p class="workbench-panel__desc">effective state、stale 语义和资产摘要均由服务端按真实 PositionPolicy 汇总。</p>
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
              <span class="workbench-muted">当前开放账户阈值和单标的实时仓位上限保持可编辑，其余参数继续只读展示。</span>
              <el-button type="primary" :loading="saving" @click="saveThresholds">保存阈值</el-button>
            </div>
          </section>

          <section class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">单标的仓位上限覆盖</div>
                <p class="workbench-panel__desc">这里展示默认值、单独设置值、有效值和当前是否已触发禁止买入。具体编辑入口放在标的管理和行情图表页。</p>
              </div>
            </div>

            <el-table v-if="symbolLimitRows.length" :data="symbolLimitRows" size="small" border>
              <el-table-column prop="symbol" label="标的代码" width="100" />
              <el-table-column prop="name" label="标的名称" min-width="140" />
              <el-table-column prop="market_value_label" label="当前市值" min-width="120" />
              <el-table-column prop="default_limit_label" label="默认值" min-width="120" />
              <el-table-column prop="override_limit_label" label="覆盖值" min-width="120" />
              <el-table-column prop="effective_limit_label" label="有效值" min-width="120" />
              <el-table-column prop="source_label" label="来源" width="92" />
              <el-table-column prop="blocked_label" label="门禁" width="92" />
            </el-table>

            <div v-else class="workbench-empty">当前没有可展示的单标的仓位上限行。</div>
          </section>
        </div>

        <div class="position-lower-column position-lower-column--stacked">
          <section class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">持仓范围</div>
                <p class="workbench-panel__desc">holding scope 使用与门禁一致的 union 口径，只认最新一次券商同步的持仓真值。</p>
              </div>
            </div>

            <div class="workbench-summary-row">
              <span class="workbench-summary-chip workbench-summary-chip--muted">
                count <strong>{{ holdingScope.count_label }}</strong>
              </span>
              <span class="workbench-summary-chip workbench-summary-chip--muted">
                source <strong>{{ holdingScope.source }}</strong>
              </span>
            </div>

            <div class="position-holding-panel">
              <div class="position-holding-copy">{{ holdingScope.description }}</div>
              <div class="position-code-chip-list">
                <span
                  v-for="code in holdingScope.codes"
                  :key="code"
                  class="workbench-summary-chip workbench-summary-chip--muted"
                >
                  {{ code }}
                </span>
                <span
                  v-if="holdingScope.codes.length === 0"
                  class="workbench-summary-chip workbench-summary-chip--muted"
                >
                  当前无持仓代码
                </span>
              </div>
            </div>
          </section>

          <section class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">规则矩阵</div>
                <p class="workbench-panel__desc">直接回答当前哪些行为允许、为什么。</p>
              </div>
            </div>

            <el-table :data="ruleMatrix" size="small" border>
              <el-table-column prop="label" label="行为" min-width="120" />
              <el-table-column label="结果" width="88">
                <template #default="{ row }">
                  <span
                    class="workbench-summary-chip"
                    :class="row.allowed ? 'workbench-summary-chip--success' : 'workbench-summary-chip--danger'"
                  >
                    {{ row.allowed_label }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="reason_code" label="原因码" min-width="140" />
              <el-table-column prop="reason_text" label="说明" min-width="220" />
            </el-table>
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
  buildHoldingScopeView,
  buildInventoryRows,
  buildRecentDecisionDetailRows,
  buildRecentDecisionRows,
  buildRuleMatrix,
  buildStatePanel,
  buildSymbolLimitRows,
  readDashboardPayload,
} from './positionManagement.mjs'

const loading = ref(false)
const saving = ref(false)
const pageError = ref('')
const dashboard = ref({})
const selectedDecisionKey = ref('')

const editableForm = reactive({
  allow_open_min_bail: 0,
  holding_only_min_bail: 0,
  single_symbol_position_limit: 0,
})

const inventoryRows = computed(() => buildInventoryRows(dashboard.value))
const symbolLimitRows = computed(() => buildSymbolLimitRows(dashboard.value))
const statePanel = computed(() => buildStatePanel(dashboard.value))
const holdingScope = computed(() => buildHoldingScopeView(dashboard.value))
const ruleMatrix = computed(() => buildRuleMatrix(dashboard.value))
const recentDecisionRows = computed(() => buildRecentDecisionRows(dashboard.value))
const selectedDecision = computed(() => (
  recentDecisionRows.value.find((item) => item.selection_key === selectedDecisionKey.value) ||
  recentDecisionRows.value[0] ||
  null
))
const decisionDetailRows = computed(() => buildRecentDecisionDetailRows(selectedDecision.value))
const configUpdatedAt = computed(() => dashboard.value?.config?.updated_at || '未配置')
const configUpdatedBy = computed(() => dashboard.value?.config?.updated_by || 'unknown')
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

watch(recentDecisionRows, (rows) => {
  if (!rows.some((item) => item.selection_key === selectedDecisionKey.value)) {
    selectedDecisionKey.value = rows[0]?.selection_key || ''
  }
}, { immediate: true })

const syncEditableForm = () => {
  const thresholds = dashboard.value?.config?.thresholds || {}
  editableForm.allow_open_min_bail = Number(thresholds.allow_open_min_bail || 0)
  editableForm.holding_only_min_bail = Number(thresholds.holding_only_min_bail || 0)
  editableForm.single_symbol_position_limit = Number(thresholds.single_symbol_position_limit || 0)
}

const resolveErrorMessage = (error, fallback) => {
  const responseMessage = error?.response?.data?.error
  const directMessage = error?.message
  return responseMessage || directMessage || fallback
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

.position-decision-grid,
.position-lower-grid {
  display: grid;
  gap: 12px;
}

.position-decision-grid {
  grid-template-columns: minmax(320px, 0.96fr) minmax(0, 1.24fr);
}

.position-lower-grid {
  grid-template-columns: minmax(0, 1.05fr) minmax(0, 1.08fr) minmax(0, 0.95fr);
  align-items: start;
}

.position-lower-column,
.position-lower-column--stacked {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.position-decision-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 620px;
  overflow: auto;
}

.position-decision-card {
  width: 100%;
  padding: 14px;
  border: 1px solid #dbe1ea;
  border-radius: 10px;
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, background 0.18s ease;
}

.position-decision-card:hover,
.position-decision-card--active {
  border-color: #6f8ad8;
  box-shadow: 0 10px 26px rgba(44, 72, 146, 0.08);
  background: #f8fbff;
}

.position-decision-card__header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.position-decision-card__symbol {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.position-decision-card__symbol strong {
  color: #1f2937;
  font-size: 15px;
  line-height: 1.3;
}

.position-decision-card__symbol span,
.position-decision-card__reason,
.inventory-parameter-cell span,
.inventory-value,
.position-holding-copy {
  color: #606266;
  font-size: 12px;
  line-height: 1.5;
}

.position-decision-card__summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.position-decision-card__summary-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.position-decision-card__summary-item span,
.position-metric-card span,
.position-meta-card span {
  color: #909399;
  font-size: 12px;
}

.position-decision-card__summary-item strong {
  color: #303133;
  line-height: 1.4;
  font-size: 13px;
}

.position-decision-card__reason {
  margin-top: 12px;
}

.position-decision-detail-table {
  margin-top: 8px;
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

.position-metric-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
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

.position-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.position-meta-card strong {
  font-size: 13px;
  word-break: break-all;
}

.position-holding-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.position-code-chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

@media (max-width: 1480px) {
  .position-lower-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1260px) {
  .position-decision-grid,
  .position-lower-grid,
  .position-decision-card__summary,
  .position-metric-grid,
  .position-meta-grid {
    grid-template-columns: 1fr;
  }
}
</style>
