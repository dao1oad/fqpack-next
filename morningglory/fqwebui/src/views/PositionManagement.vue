<template>
  <div class="workbench-page position-page">
    <MyHeader />

    <div class="workbench-body position-body" v-loading="loading">
      <section class="workbench-toolbar">
        <div class="workbench-toolbar__header">
          <div class="workbench-title-group">
            <div class="workbench-page-title">仓位管理</div>
            <div class="workbench-page-meta">
              <span>统一查看阈值、当前仓位状态、holding scope 和规则命中</span>
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
            规则 <strong>{{ statePanel.hero.matched_rule_title }}</strong>
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

      <section class="workbench-panel position-config-panel">
        <div class="workbench-panel__header">
          <div class="workbench-title-group">
            <div class="workbench-panel__title">参数 inventory</div>
            <p class="workbench-panel__desc">把真正生效的阈值、代码默认值和系统连接参数合并到一张表，同时保留说明和可编辑边界。</p>
          </div>
        </div>

        <el-table :data="inventoryRows" size="small" border class="position-config-table">
          <el-table-column prop="group_label" label="分组" min-width="140" show-overflow-tooltip />
          <el-table-column label="参数" min-width="240">
            <template #default="{ row }">
              <div class="inventory-parameter-cell">
                <strong>{{ row.label }}</strong>
                <span>{{ row.source_label }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="当前值" min-width="220">
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
          <el-table-column prop="description" label="说明" min-width="360" show-overflow-tooltip />
        </el-table>

        <div class="position-edit-footer">
          <span class="workbench-muted">当前开放账户阈值和单标的实时仓位上限保持可编辑，其余参数继续只读展示。</span>
          <el-button type="primary" :loading="saving" @click="saveThresholds">保存阈值</el-button>
        </div>
      </section>

      <div class="position-state-grid">
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

        <section class="workbench-panel">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">持仓范围与规则矩阵</div>
              <p class="workbench-panel__desc">holding scope 使用与门禁一致的 union 口径，规则矩阵直接回答当前哪些行为允许、为什么。</p>
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

      <section class="workbench-panel">
        <div class="workbench-panel__header">
          <div class="workbench-title-group">
            <div class="workbench-panel__title">最近决策</div>
            <p class="workbench-panel__desc">辅助确认最近策略单被允许还是拒绝，以及对应原因码。</p>
          </div>
        </div>

        <el-table v-if="recentDecisionRows.length" :data="recentDecisionRows" size="small" border>
          <el-table-column prop="strategy_label" label="策略" min-width="140" />
          <el-table-column prop="action_label" label="动作" width="86" />
          <el-table-column prop="symbol_label" label="标的代码" width="100" />
          <el-table-column prop="symbol_name_label" label="标的名称" min-width="140" />
          <el-table-column prop="state_label" label="状态" min-width="120" />
          <el-table-column label="结果" width="88">
            <template #default="{ row }">
              <span
                class="workbench-summary-chip"
                :class="row.tone === 'allow' ? 'workbench-summary-chip--success' : 'workbench-summary-chip--danger'"
              >
                {{ row.allowed_label }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="reason_text" label="说明" min-width="260" />
          <el-table-column prop="evaluated_at_label" label="评估时间" min-width="176" />
        </el-table>

        <div v-else class="workbench-empty">暂无最近决策记录。</div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import MyHeader from '@/views/MyHeader.vue'
import { positionManagementApi } from '@/api/positionManagementApi'
import {
  buildHoldingScopeView,
  buildInventoryRows,
  buildRecentDecisionRows,
  buildRuleMatrix,
  buildStatePanel,
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

const inventoryRows = computed(() => buildInventoryRows(dashboard.value))
const statePanel = computed(() => buildStatePanel(dashboard.value))
const holdingScope = computed(() => buildHoldingScopeView(dashboard.value))
const ruleMatrix = computed(() => buildRuleMatrix(dashboard.value))
const recentDecisionRows = computed(() => buildRecentDecisionRows(dashboard.value))
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
.inventory-value,
.position-holding-copy {
  color: #606266;
  font-size: 12px;
  line-height: 1.5;
}

.position-state-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(0, 1.15fr);
  gap: 12px;
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
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.position-metric-card span,
.position-meta-card span {
  display: block;
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

.position-meta-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
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

@media (max-width: 1320px) {
  .position-state-grid,
  .position-metric-grid,
  .position-meta-grid {
    grid-template-columns: 1fr;
  }
}
</style>
