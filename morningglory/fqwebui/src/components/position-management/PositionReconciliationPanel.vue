<template>
  <WorkbenchLedgerPanel class="position-reconciliation-panel">
    <div class="workbench-panel__header">
      <div class="workbench-title-group">
        <div class="workbench-panel__title">对账检查</div>
        <div class="workbench-panel__desc">
          一致性审计保持只读，按 dense ledger 展示 broker / snapshot / ledger / compat 差异解释。
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

      <div v-else-if="filteredRows.length" class="position-reconciliation-ledger">
        <div class="position-reconciliation-ledger__header position-reconciliation-ledger__grid">
          <span>标的</span>
          <span>结果</span>
          <span>对账状态</span>
          <span>latest resolution</span>
          <span>signed gap</span>
          <span>open gap</span>
          <span>mismatch</span>
          <span>关键视图</span>
          <span>证据</span>
        </div>

        <div
          v-for="row in filteredRows"
          :key="row.symbol"
          class="position-reconciliation-ledger__item"
          :class="{
            'position-reconciliation-ledger__item--error': row.audit_status === 'ERROR',
            'position-reconciliation-ledger__item--warn': row.audit_status === 'WARN',
          }"
        >
          <div class="position-reconciliation-ledger__row position-reconciliation-ledger__grid">
            <div class="position-reconciliation-symbol-cell">
              <strong>{{ row.symbol }}</strong>
              <span>{{ row.name || '-' }}</span>
            </div>

            <div class="position-reconciliation-chip-cell">
              <StatusChip class="runtime-inline-status" :variant="row.audit_status_chip_variant">
                {{ row.audit_status }}
              </StatusChip>
            </div>

            <div class="position-reconciliation-chip-cell">
              <StatusChip class="runtime-inline-status" :variant="row.reconciliation_state_chip_variant">
                {{ row.reconciliation_state_label }}
              </StatusChip>
            </div>

            <span class="position-reconciliation-text-cell">{{ row.latest_resolution_label }}</span>
            <span class="position-reconciliation-number-cell">{{ row.detail_items[4]?.value || '0' }}</span>
            <span class="position-reconciliation-number-cell">{{ row.detail_items[5]?.value || '0' }}</span>

            <div class="position-reconciliation-mismatch-cell">
              <StatusChip
                v-for="item in row.mismatch_explanations.slice(0, 3)"
                :key="`${row.symbol}-${item.code}`"
                :variant="item.chipVariant"
              >
                {{ item.label }}
              </StatusChip>
              <span
                v-if="row.mismatch_explanations.length === 0"
                class="position-reconciliation-inline-empty"
              >
                当前无 mismatch
              </span>
            </div>

            <div class="position-reconciliation-surface-cell">
              <div
                v-for="item in row.surface_sections.slice(0, 3)"
                :key="`${row.symbol}-${item.key}`"
                class="position-reconciliation-surface-line"
              >
                <strong>{{ item.label }}</strong>
                <span>{{ item.quantity_label }} 股 / {{ item.market_value_label }}</span>
              </div>
            </div>

            <div class="position-reconciliation-action-cell">
              <el-button text type="primary" @click="toggleExpanded(row.symbol)">
                {{ expandedMap[row.symbol] ? '收起' : '展开' }}
              </el-button>
            </div>
          </div>

          <div
            v-if="expandedMap[row.symbol]"
            class="position-reconciliation-expanded"
          >
            <section class="position-reconciliation-expanded__section">
              <div class="position-reconciliation-expanded__title">视图层证据表</div>
              <div class="position-reconciliation-expanded__table position-reconciliation-expanded__surface-table">
                <div class="position-reconciliation-expanded__table-head">
                  <span>视图</span>
                  <span>数量</span>
                  <span>市值</span>
                  <span>数量来源</span>
                  <span>金额来源</span>
                </div>
                <div
                  v-for="item in row.surface_sections"
                  :key="`${row.symbol}-surface-${item.key}`"
                  class="position-reconciliation-expanded__table-row"
                >
                  <span>{{ item.label }}</span>
                  <span>{{ item.quantity_label }} 股</span>
                  <span>{{ item.market_value_label }}</span>
                  <span>{{ item.quantity_source_label }}</span>
                  <span>{{ item.market_value_source_label }}</span>
                </div>
              </div>
            </section>

            <section class="position-reconciliation-expanded__section">
              <div class="position-reconciliation-expanded__title">规则检查表</div>
              <div class="position-reconciliation-expanded__table position-reconciliation-expanded__rule-table">
                <div class="position-reconciliation-expanded__table-head">
                  <span>规则</span>
                  <span>结果</span>
                  <span>关系</span>
                  <span>差异码</span>
                </div>
                <div
                  v-for="item in row.rule_badges"
                  :key="`${row.symbol}-rule-${item.id}`"
                  class="position-reconciliation-expanded__table-row"
                >
                  <span>{{ item.id }} {{ item.label }}</span>
                  <span>{{ item.status_label }}</span>
                  <span>{{ item.expected_relation }}</span>
                  <span>{{ (item.mismatch_codes || []).join(' / ') || '-' }}</span>
                </div>
              </div>
            </section>

            <section class="position-reconciliation-expanded__section">
              <div class="position-reconciliation-expanded__title">差异说明表</div>
              <div class="position-reconciliation-expanded__table position-reconciliation-expanded__reconciliation-table">
                <div class="position-reconciliation-expanded__table-head">
                  <span>字段</span>
                  <span>值</span>
                </div>
                <div class="position-reconciliation-expanded__table-row">
                  <span>state</span>
                  <span>{{ row.evidence_sections.reconciliation?.state || row.reconciliation_state }}</span>
                </div>
                <div class="position-reconciliation-expanded__table-row">
                  <span>signed gap</span>
                  <span>{{ row.detail_items[4]?.value || '0' }}</span>
                </div>
                <div class="position-reconciliation-expanded__table-row">
                  <span>open gap</span>
                  <span>{{ row.detail_items[5]?.value || '0' }}</span>
                </div>
                <div class="position-reconciliation-expanded__table-row">
                  <span>rule evidence</span>
                  <span>{{ row.evidence_sections.rules?.length || 0 }}</span>
                </div>
              </div>
            </section>
          </div>
        </div>
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

.position-reconciliation-ledger {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  flex-direction: column;
  overflow: auto;
  border: 1px solid #e5edf5;
  border-radius: 12px;
  background: #fff;
}

.position-reconciliation-ledger__header,
.position-reconciliation-ledger__row {
  display: grid;
  align-items: stretch;
  gap: 8px;
  min-width: max-content;
  padding: 8px 10px;
  font-size: 12px;
}

.position-reconciliation-ledger__grid {
  grid-template-columns:
    148px
    88px
    112px
    128px
    84px
    84px
    minmax(220px, 1.15fr)
    minmax(220px, 1.15fr)
    78px;
}

.position-reconciliation-ledger__header {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #f6f9fc;
  color: #68839d;
  border-bottom: 1px solid #e5edf5;
}

.position-reconciliation-ledger__item {
  border-top: 1px solid #eef3f8;
}

.position-reconciliation-ledger__item--error > .position-reconciliation-ledger__row {
  background: #fff7f5;
}

.position-reconciliation-ledger__item--warn > .position-reconciliation-ledger__row {
  background: #fffaf0;
}

.position-reconciliation-ledger__row:hover {
  background: #f8fbff;
}

.position-reconciliation-symbol-cell,
.position-reconciliation-surface-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.position-reconciliation-symbol-cell strong,
.position-reconciliation-surface-line strong,
.position-reconciliation-number-cell {
  color: #21405e;
}

.position-reconciliation-symbol-cell span,
.position-reconciliation-surface-line span,
.position-reconciliation-text-cell,
.position-reconciliation-inline-empty {
  color: #68839d;
  line-height: 1.45;
}

.position-reconciliation-number-cell {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.position-reconciliation-mismatch-cell,
.position-reconciliation-chip-cell,
.position-reconciliation-action-cell {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  flex-wrap: wrap;
}

.position-reconciliation-action-cell {
  justify-content: flex-end;
}

.position-reconciliation-expanded {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px;
  background: #fbfdff;
  border-top: 1px solid #e5edf5;
}

.position-reconciliation-expanded__section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.position-reconciliation-expanded__title {
  color: #21405e;
  font-size: 12px;
  font-weight: 600;
}

.position-reconciliation-expanded__table {
  display: flex;
  flex-direction: column;
  border: 1px solid #e5edf5;
  border-radius: 10px;
  background: #fff;
  overflow: hidden;
}

.position-reconciliation-expanded__table-head,
.position-reconciliation-expanded__table-row {
  display: grid;
  gap: 8px;
  padding: 8px 10px;
  font-size: 12px;
}

.position-reconciliation-expanded__surface-table :is(.position-reconciliation-expanded__table-head, .position-reconciliation-expanded__table-row) {
  grid-template-columns: 108px 96px 96px minmax(160px, 1fr) minmax(160px, 1fr);
}

.position-reconciliation-expanded__rule-table :is(.position-reconciliation-expanded__table-head, .position-reconciliation-expanded__table-row) {
  grid-template-columns: 168px 88px minmax(140px, 1fr) minmax(160px, 1fr);
}

.position-reconciliation-expanded__reconciliation-table :is(.position-reconciliation-expanded__table-head, .position-reconciliation-expanded__table-row) {
  grid-template-columns: 148px minmax(180px, 1fr);
}

.position-reconciliation-expanded__table-head {
  color: #68839d;
  background: #f6f9fc;
}

.position-reconciliation-expanded__table-row {
  color: #21405e;
  border-top: 1px solid #eef3f8;
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

  .position-reconciliation-ledger__grid,
  .position-reconciliation-expanded__surface-table :is(.position-reconciliation-expanded__table-head, .position-reconciliation-expanded__table-row),
  .position-reconciliation-expanded__rule-table :is(.position-reconciliation-expanded__table-head, .position-reconciliation-expanded__table-row),
  .position-reconciliation-expanded__reconciliation-table :is(.position-reconciliation-expanded__table-head, .position-reconciliation-expanded__table-row) {
    grid-template-columns: 1fr;
  }
}
</style>
