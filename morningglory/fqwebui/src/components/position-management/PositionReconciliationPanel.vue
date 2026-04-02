<template>
  <WorkbenchLedgerPanel class="position-reconciliation-panel">
    <div class="workbench-panel__header">
      <div class="workbench-title-group">
        <div class="workbench-panel__title">对账检查</div>
        <div class="workbench-panel__desc">
          升级后的多视图一致性审计只负责读，聚焦 broker / snapshot / ledger / compat 的差异解释。
        </div>
      </div>
    </div>

    <div class="position-reconciliation-panel__body">
      <div class="workbench-summary-row">
        <StatusChip variant="muted">
          总标的 <strong>{{ summary.row_count || 0 }}</strong>
        </StatusChip>
        <StatusChip variant="danger">
          ERROR <strong>{{ summary.audit_status_counts?.ERROR || 0 }}</strong>
        </StatusChip>
        <StatusChip variant="warning">
          WARN <strong>{{ summary.audit_status_counts?.WARN || 0 }}</strong>
        </StatusChip>
        <StatusChip variant="success">
          OK <strong>{{ summary.audit_status_counts?.OK || 0 }}</strong>
        </StatusChip>
        <StatusChip
          v-for="item in summaryStateCards"
          :key="item.key"
          :variant="item.chipVariant"
        >
          {{ item.label }} <strong>{{ item.count }}</strong>
        </StatusChip>
        <StatusChip
          v-for="item in summaryRuleCards"
          :key="item.id"
          :variant="item.chipVariant"
        >
          {{ item.label }} <strong>{{ item.statusSummary }}</strong>
        </StatusChip>
      </div>

      <div class="position-reconciliation-toolbar">
        <el-input
          v-model="query"
          clearable
          placeholder="筛选标的 / 名称"
          class="position-reconciliation-toolbar__query"
        />
        <el-select v-model="auditStatus" class="position-reconciliation-toolbar__select">
          <el-option label="全部结果" value="ALL" />
          <el-option
            v-for="item in auditOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
        <el-select v-model="state" class="position-reconciliation-toolbar__select">
          <el-option label="全部状态" value="ALL" />
          <el-option
            v-for="item in stateOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
      </div>

      <el-alert
        v-if="error"
        class="workbench-alert"
        type="error"
        :title="error"
        show-icon
        :closable="false"
      />

      <div v-else-if="loading" class="runtime-empty-panel">
        <strong>对账检查加载中</strong>
      </div>

      <div v-else-if="filteredRows.length" class="position-audit-list">
        <article
          v-for="row in filteredRows"
          :key="row.symbol"
          class="position-audit-row"
          :class="{
            'position-audit-row--error': row.audit_status === 'ERROR',
            'position-audit-row--warn': row.audit_status === 'WARN',
          }"
        >
          <div class="position-audit-row__headline">
            <div class="position-audit-row__symbol">
              <strong>{{ row.symbol }}</strong>
              <span>{{ row.name || '-' }}</span>
            </div>

            <div class="position-audit-row__chips">
              <StatusChip class="runtime-inline-status" :variant="row.audit_status_chip_variant">
                {{ row.audit_status }}
              </StatusChip>
              <StatusChip class="runtime-inline-status" :variant="row.reconciliation_state_chip_variant">
                {{ row.reconciliation_state_label }}
              </StatusChip>
            </div>

            <el-button text type="primary" @click="toggleExpanded(row.symbol)">
              {{ expandedMap[row.symbol] ? '收起证据' : '展开证据' }}
            </el-button>
          </div>

          <div class="position-audit-row__meta">
            <span>latest resolution {{ row.latest_resolution_label }}</span>
            <span>signed gap {{ row.detail_items[4]?.value || '0' }}</span>
            <span>open gap {{ row.detail_items[5]?.value || '0' }}</span>
          </div>

          <div class="position-audit-preview-grid">
            <div
              v-for="item in row.surface_sections.slice(0, 4)"
              :key="`${row.symbol}-${item.key}`"
              class="position-audit-preview-card"
            >
              <span>{{ item.label }}</span>
              <strong>{{ item.quantity_label }} 股</strong>
              <small>市值 {{ item.market_value_label }}</small>
            </div>
          </div>

          <div class="workbench-summary-row">
            <StatusChip
              v-for="item in row.mismatch_explanations"
              :key="`${row.symbol}-${item.code}`"
              :variant="item.chipVariant"
            >
              {{ item.label }}
            </StatusChip>
            <StatusChip
              v-if="row.mismatch_explanations.length === 0"
              variant="success"
            >
              当前无 mismatch
            </StatusChip>
          </div>

          <div
            v-if="expandedMap[row.symbol]"
            class="position-audit-evidence"
          >
            <section class="position-audit-evidence__section">
              <div class="position-audit-evidence__title">视图层证据</div>
              <div class="position-audit-surface-grid">
                <div
                  v-for="item in row.surface_sections"
                  :key="`${row.symbol}-surface-${item.key}`"
                  class="position-audit-evidence-card"
                >
                  <span>{{ item.label }}</span>
                  <strong>{{ item.quantity_label }} 股</strong>
                  <small>市值 {{ item.market_value_label }}</small>
                  <small>数量来源 {{ item.quantity_source_label }}</small>
                  <small>金额来源 {{ item.market_value_source_label }}</small>
                </div>
              </div>
            </section>

            <section class="position-audit-evidence__section">
              <div class="position-audit-evidence__title">规则检查</div>
              <div class="position-audit-rule-grid">
                <div
                  v-for="item in row.rule_badges"
                  :key="`${row.symbol}-rule-${item.id}`"
                  class="position-audit-evidence-card"
                >
                  <span>{{ item.id }} {{ item.label }}</span>
                  <strong>{{ item.status_label }}</strong>
                  <small>{{ item.expected_relation }}</small>
                </div>
              </div>
            </section>

            <section class="position-audit-evidence__section">
              <div class="position-audit-evidence__title">差异说明</div>
              <div class="position-audit-reconciliation-grid">
                <div class="position-audit-evidence-card">
                  <span>state</span>
                  <strong>{{ row.evidence_sections.reconciliation?.state || row.reconciliation_state }}</strong>
                </div>
                <div class="position-audit-evidence-card">
                  <span>signed gap</span>
                  <strong>{{ row.detail_items[4]?.value || '0' }}</strong>
                </div>
                <div class="position-audit-evidence-card">
                  <span>open gap</span>
                  <strong>{{ row.detail_items[5]?.value || '0' }}</strong>
                </div>
                <div class="position-audit-evidence-card">
                  <span>rule evidence</span>
                  <strong>{{ row.evidence_sections.rules?.length || 0 }}</strong>
                </div>
              </div>
            </section>
          </div>
        </article>
      </div>

      <div v-else class="runtime-empty-panel">
        <strong>当前没有需要展示的对账结果</strong>
      </div>
    </div>
  </WorkbenchLedgerPanel>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'

import StatusChip from '../workbench/StatusChip.vue'
import WorkbenchLedgerPanel from '../workbench/WorkbenchLedgerPanel.vue'
import { AUDIT_STATUS_META, RECONCILIATION_STATE_META } from '../../views/reconciliationStateMeta.mjs'
import {
  buildPositionReconciliationRows,
  buildPositionReconciliationSummaryViewModel,
  filterPositionReconciliationRows,
  readPositionReconciliationPayload,
} from '../../views/positionReconciliation.mjs'

const props = defineProps({
  overview: {
    type: Object,
    default: () => ({}),
  },
  loading: {
    type: Boolean,
    default: false,
  },
  error: {
    type: String,
    default: '',
  },
})

const query = ref('')
const auditStatus = ref('ALL')
const state = ref('ALL')
const expandedMap = reactive({})

const normalizedOverview = computed(() => readPositionReconciliationPayload(props.overview, {}))
const summaryViewModel = computed(() => buildPositionReconciliationSummaryViewModel(normalizedOverview.value))
const summary = computed(() => summaryViewModel.value.summary || {
  row_count: 0,
  audit_status_counts: { OK: 0, WARN: 0, ERROR: 0 },
})
const summaryStateCards = computed(() => summaryViewModel.value.stateCards || [])
const summaryRuleCards = computed(() => summaryViewModel.value.ruleCards || [])
const rows = computed(() => buildPositionReconciliationRows(normalizedOverview.value))
const filteredRows = computed(() => filterPositionReconciliationRows(rows.value, {
  query: query.value,
  auditStatus: auditStatus.value,
  state: state.value,
}))
const auditOptions = Object.values(AUDIT_STATUS_META).map((item) => ({
  value: item.key,
  label: `${item.key} / ${item.label}`,
}))
const stateOptions = Object.values(RECONCILIATION_STATE_META).map((item) => ({
  value: item.key,
  label: item.label,
}))

const toggleExpanded = (symbol) => {
  expandedMap[symbol] = !expandedMap[symbol]
}
</script>

<style scoped>
.position-reconciliation-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.position-reconciliation-panel__body {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  flex-direction: column;
  gap: 8px;
}

.position-reconciliation-toolbar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.position-reconciliation-toolbar__query {
  flex: 1 1 220px;
  min-width: 220px;
}

.position-reconciliation-toolbar__select {
  width: 168px;
}

.position-audit-list {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  flex-direction: column;
  gap: 10px;
  overflow: auto;
  padding-right: 2px;
  scrollbar-gutter: stable both-edges;
}

.position-audit-row {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border: 1px solid #e5edf5;
  border-radius: 14px;
  background: #fbfdff;
}

.position-audit-row--error {
  border-color: #fecaca;
  background: #fff7f5;
}

.position-audit-row--warn {
  border-color: #fde68a;
  background: #fffaf0;
}

.position-audit-row__headline,
.position-audit-row__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.position-audit-row__symbol,
.position-audit-row__chips {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.position-audit-row__symbol {
  min-width: 0;
}

.position-audit-row__symbol strong {
  color: #21405e;
}

.position-audit-row__symbol span,
.position-audit-row__meta span,
.position-audit-preview-card span,
.position-audit-preview-card small,
.position-audit-evidence-card span,
.position-audit-evidence-card small {
  color: #68839d;
  font-size: 12px;
  line-height: 1.45;
}

.position-audit-preview-grid,
.position-audit-surface-grid,
.position-audit-rule-grid,
.position-audit-reconciliation-grid {
  display: grid;
  gap: 8px;
}

.position-audit-preview-grid,
.position-audit-reconciliation-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.position-audit-surface-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.position-audit-rule-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.position-audit-preview-card,
.position-audit-evidence-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  border: 1px solid #e5edf5;
  border-radius: 12px;
  background: #fff;
}

.position-audit-preview-card strong,
.position-audit-evidence-card strong {
  color: #21405e;
  line-height: 1.4;
}

.position-audit-evidence {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.position-audit-evidence__section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.position-audit-evidence__title {
  color: #21405e;
  font-size: 12px;
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

@media (max-width: 1260px) {
  .position-reconciliation-toolbar__query,
  .position-reconciliation-toolbar__select {
    width: 100%;
    min-width: 0;
  }

  .position-audit-preview-grid,
  .position-audit-surface-grid,
  .position-audit-rule-grid,
  .position-audit-reconciliation-grid {
    grid-template-columns: 1fr;
  }
}
</style>
