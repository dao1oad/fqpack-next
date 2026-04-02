<template>
  <WorkbenchLedgerPanel class="position-reconciliation-panel">
    <div class="workbench-panel__header">
      <div class="workbench-title-group">
        <div class="workbench-panel__title">对账检查</div>
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

      <div v-else-if="filteredRows.length" class="runtime-ledger position-reconciliation-ledger">
        <div class="runtime-ledger__header position-reconciliation-ledger__grid">
          <span>标的</span>
          <span>券商</span>
          <span>PM快照</span>
          <span>Entry账本</span>
          <span>对账状态</span>
          <span>检查结果</span>
          <span>最新 resolution</span>
          <span>详情</span>
        </div>

        <template v-for="row in filteredRows" :key="row.symbol">
          <div
            class="runtime-ledger__row position-reconciliation-ledger__grid"
            :class="{
              'position-reconciliation-ledger__row--error': row.audit_status === 'ERROR',
              'position-reconciliation-ledger__row--warn': row.audit_status === 'WARN',
            }"
          >
            <div class="runtime-ledger__cell position-reconciliation-symbol">
              <strong>{{ row.symbol }}</strong>
              <span>{{ row.name || '-' }}</span>
            </div>
            <span class="runtime-ledger__cell runtime-ledger__cell--number">{{ row.broker_quantity_label }}</span>
            <span class="runtime-ledger__cell runtime-ledger__cell--number">{{ row.snapshot_quantity_label }}</span>
            <span class="runtime-ledger__cell runtime-ledger__cell--number">{{ row.entry_quantity_label }}</span>
            <span class="runtime-ledger__cell runtime-ledger__cell--status">
              <StatusChip class="runtime-inline-status" :variant="row.reconciliation_state_chip_variant">
                {{ row.reconciliation_state_label }}
              </StatusChip>
            </span>
            <span class="runtime-ledger__cell runtime-ledger__cell--status">
              <StatusChip class="runtime-inline-status" :variant="row.audit_status_chip_variant">
                {{ row.audit_status }}
              </StatusChip>
            </span>
            <span class="runtime-ledger__cell runtime-ledger__cell--truncate" :title="row.latest_resolution_label">
              {{ row.latest_resolution_label }}
            </span>
            <div class="runtime-ledger__cell position-reconciliation-actions">
              <el-button text type="primary" @click="toggleExpanded(row.symbol)">
                {{ expandedMap[row.symbol] ? '收起' : '详情' }}
              </el-button>
            </div>
          </div>

          <div
            v-if="expandedMap[row.symbol]"
            class="position-reconciliation-ledger__detail"
          >
            <div class="position-reconciliation-detail-section">
              <div class="position-reconciliation-detail-section__title">规则检查</div>
              <div class="workbench-summary-row">
                <StatusChip
                  v-for="item in row.rule_badges"
                  :key="`${row.symbol}-${item.id}`"
                  :variant="item.status_chip_variant"
                >
                  {{ item.id }} {{ item.label }} / <strong>{{ item.status_label }}</strong>
                </StatusChip>
              </div>
            </div>

            <div class="position-reconciliation-detail-section">
              <div class="position-reconciliation-detail-section__title">异常解释</div>
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
            </div>

            <div class="position-reconciliation-detail-grid">
              <div
                v-for="item in row.surface_sections"
                :key="`${row.symbol}-${item.key}`"
                class="position-reconciliation-detail-card"
              >
                <span>{{ item.label }}</span>
                <strong>{{ item.quantity_label }}</strong>
                <small>市值 {{ item.market_value_label }}</small>
                <small>数量来源 {{ item.quantity_source_label }}</small>
              </div>
            </div>

            <div class="position-reconciliation-detail-section">
              <div class="position-reconciliation-detail-section__title">Reconciliation Evidence</div>
              <div class="position-reconciliation-detail-grid position-reconciliation-detail-grid--compact">
                <div class="position-reconciliation-detail-card">
                  <span>state</span>
                  <strong>{{ row.evidence_sections.reconciliation?.state || row.reconciliation_state }}</strong>
                </div>
                <div class="position-reconciliation-detail-card">
                  <span>signed gap</span>
                  <strong>{{ row.detail_items[4]?.value || '0' }}</strong>
                </div>
                <div class="position-reconciliation-detail-card">
                  <span>open gap</span>
                  <strong>{{ row.detail_items[5]?.value || '0' }}</strong>
                </div>
                <div class="position-reconciliation-detail-card">
                  <span>rule evidence</span>
                  <strong>{{ row.evidence_sections.rules?.length || 0 }}</strong>
                </div>
              </div>
            </div>
          </div>
        </template>
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
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  scrollbar-gutter: stable both-edges;
}

.position-reconciliation-ledger__grid {
  grid-template-columns:
    160px
    92px
    92px
    92px
    112px
    96px
    132px
    72px;
}

.position-reconciliation-ledger__row--error {
  background: #fff4f1;
}

.position-reconciliation-ledger__row--error:hover {
  background: #ffe9e2;
}

.position-reconciliation-ledger__row--warn {
  background: #fff9ed;
}

.position-reconciliation-ledger__row--warn:hover {
  background: #fff4de;
}

.position-reconciliation-symbol {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.position-reconciliation-symbol strong {
  color: #21405e;
}

.position-reconciliation-symbol span {
  color: #68839d;
  font-size: 11px;
}

.position-reconciliation-actions {
  display: flex;
  justify-content: flex-end;
}

.position-reconciliation-ledger__detail {
  padding: 8px 12px 12px;
  border-top: 1px solid #eef3f8;
  background: #f8fbff;
}

.position-reconciliation-detail-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
}

.position-reconciliation-detail-grid--compact {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.position-reconciliation-detail-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 10px;
}

.position-reconciliation-detail-section__title {
  font-size: 12px;
  font-weight: 600;
  color: #4b6580;
}

.position-reconciliation-detail-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  border: 1px solid #e5edf5;
  border-radius: 10px;
  background: #fff;
}

.position-reconciliation-detail-card span,
.position-reconciliation-detail-card small {
  color: #68839d;
  line-height: 1.4;
}

.position-reconciliation-detail-card span {
  font-size: 11px;
}

.position-reconciliation-detail-card strong {
  color: #21405e;
  line-height: 1.4;
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

  .position-reconciliation-detail-grid,
  .position-reconciliation-detail-grid--compact {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
