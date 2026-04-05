<template>
  <WorkbenchPage class="reconciliation-page">
    <MyHeader />
    <div class="workbench-body reconciliation-body">
      <WorkbenchToolbar class="reconciliation-toolbar">
        <div class="workbench-toolbar__header">
          <div class="workbench-title-group">
            <div class="workbench-page-title">对账中心</div>
            <div class="workbench-page-meta">
              <span>统一承载 symbol 对账、相关订单、entry / slice、resolution 排障。</span>
              <template v-if="selectedSymbol"><span>/</span><span>当前标的 <span class="workbench-code">{{ selectedSymbol }}</span></span></template>
              <span>/</span><span>当前标签 {{ activeTabLabel }}</span>
            </div>
          </div>
          <div class="workbench-toolbar__actions">
            <el-input v-model="lookupDraft" class="reconciliation-toolbar__symbol-input" clearable placeholder="symbol / internal_order_id / request_id / broker_order_id" @keyup.enter="handleApplyLookup" />
            <el-button @click="handleResetSelection">清空</el-button>
            <el-button type="primary" :loading="loadingOverview || loadingOrders || loadingWorkspace" @click="handleApplyLookup">定位</el-button>
            <el-button :loading="loadingOverview" @click="handleRefresh">刷新</el-button>
          </div>
        </div>
        <el-alert v-if="pageError" class="workbench-alert" type="error" :title="pageError" :closable="false" show-icon />
        <div class="workbench-summary-row">
          <StatusChip>总标的 <strong>{{ summaryChips.totalSymbols }}</strong></StatusChip>
          <StatusChip variant="danger">ERROR <strong>{{ summaryChips.errorCount }}</strong></StatusChip>
          <StatusChip variant="warning">WARN <strong>{{ summaryChips.warnCount }}</strong></StatusChip>
          <StatusChip variant="success">OK <strong>{{ summaryChips.okCount }}</strong></StatusChip>
          <StatusChip variant="muted">open gap <strong>{{ summaryChips.openGapCount }}</strong></StatusChip>
          <StatusChip variant="muted">当前缺 broker <strong>{{ summaryChips.missingBrokerCount }}</strong></StatusChip>
        </div>
      </WorkbenchToolbar>

      <div class="reconciliation-layout">
        <WorkbenchLedgerPanel class="reconciliation-ledger-panel" v-loading="loadingOverview">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">Symbol 对账主表</div>
              <p class="workbench-panel__desc">左栏负责发现异常；右栏开始联动订单、持仓账本与 resolution。</p>
            </div>
            <div class="workbench-panel__actions reconciliation-panel__filters">
              <el-input v-model="overviewFilters.query" clearable placeholder="筛选 symbol / 名称" class="reconciliation-panel__filter reconciliation-panel__filter--query" />
              <el-select v-model="overviewFilters.auditStatus" class="reconciliation-panel__filter reconciliation-panel__filter--select">
                <el-option label="全部结果" value="ALL" />
                <el-option v-for="item in overviewAuditOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-select v-model="overviewFilters.state" class="reconciliation-panel__filter reconciliation-panel__filter--select">
                <el-option label="全部状态" value="ALL" />
                <el-option v-for="item in overviewStateOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </div>
          </div>
          <div class="workbench-table-wrap reconciliation-table-wrap">
            <el-empty v-if="filteredOverviewRows.length === 0" description="当前没有需要展示的对账结果。" />
            <el-table v-else :data="filteredOverviewRows" row-key="symbol" height="100%" border size="small" highlight-current-row :current-row-key="selectedSymbol" @row-click="handleOverviewRowClick">
              <el-table-column label="标的" min-width="140"><template #default="{ row }"><div class="reconciliation-symbol-cell"><strong>{{ row.symbol }}</strong><span>{{ row.name || '-' }}</span></div></template></el-table-column>
              <el-table-column label="检查结果" width="96"><template #default="{ row }"><StatusChip class="runtime-inline-status" :variant="row.audit_status_chip_variant">{{ row.audit_status }}</StatusChip></template></el-table-column>
              <el-table-column label="对账状态" width="108"><template #default="{ row }"><StatusChip class="runtime-inline-status" :variant="row.reconciliation_state_chip_variant">{{ row.reconciliation_state_label }}</StatusChip></template></el-table-column>
              <el-table-column prop="latest_resolution_label" label="latest resolution" min-width="136" />
              <el-table-column prop="broker_quantity_label" label="broker" width="90" />
              <el-table-column prop="snapshot_quantity_label" label="snapshot" width="96" />
              <el-table-column prop="entry_quantity_label" label="entry" width="88" />
              <el-table-column label="signed gap" width="92"><template #default="{ row }">{{ row.detail_items?.[4]?.value || '0' }}</template></el-table-column>
              <el-table-column label="open gap" width="88"><template #default="{ row }">{{ row.detail_items?.[5]?.value || '0' }}</template></el-table-column>
              <el-table-column label="mismatch" min-width="220"><template #default="{ row }"><div class="reconciliation-chip-wrap"><StatusChip v-for="item in row.mismatch_explanations.slice(0, 3)" :key="`${row.symbol}-${item.code}`" :variant="item.chipVariant">{{ item.label }}</StatusChip><span v-if="row.mismatch_explanations.length === 0" class="workbench-muted">当前无 mismatch</span></div></template></el-table-column>
            </el-table>
          </div>
        </WorkbenchLedgerPanel>

        <WorkbenchDetailPanel class="reconciliation-detail-panel">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">排障工作区</div>
              <p class="workbench-panel__desc">右栏承接概览、订单链、持仓账本与 resolution。</p>
            </div>
          </div>
          <el-tabs v-model="activeTab" class="reconciliation-tabs" @tab-change="handleTabChange">
            <el-tab-pane name="overview" label="概览">
              <div v-if="selectedOverviewRow" class="reconciliation-tab-stack">
                <div class="workbench-summary-row">
                  <StatusChip :variant="selectedOverviewRow.audit_status_chip_variant || 'muted'">检查结果 <strong>{{ selectedOverviewRow.audit_status }}</strong></StatusChip>
                  <StatusChip :variant="selectedOverviewRow.reconciliation_state_chip_variant || 'muted'">对账状态 <strong>{{ selectedOverviewRow.reconciliation_state_label || '-' }}</strong></StatusChip>
                </div>
                <div class="reconciliation-tab-grid">
                  <article class="workbench-block reconciliation-block reconciliation-block--table"><div class="reconciliation-block__head">规则检查</div><div class="reconciliation-table-wrap"><el-table :data="selectedOverviewRuleRows" size="small" border height="100%"><el-table-column prop="id" label="规则" width="72" /><el-table-column prop="label" label="说明" min-width="120" /><el-table-column prop="status_label" label="结果" width="92" /><el-table-column prop="expected_relation" label="关系" min-width="120" /></el-table></div></article>
                  <article class="workbench-block reconciliation-block reconciliation-block--table"><div class="reconciliation-block__head">视图对照</div><div class="reconciliation-table-wrap"><el-table :data="selectedOverviewSurfaceRows" size="small" border height="100%"><el-table-column prop="label" label="surface" min-width="112" /><el-table-column prop="quantity_label" label="数量" width="92" /><el-table-column prop="market_value_label" label="市值" width="108" /><el-table-column prop="quantity_source_label" label="数量来源" min-width="120" /></el-table></div></article>
                </div>
              </div>
              <div v-else class="workbench-empty">请先在上半屏选择一个 symbol。</div>
            </el-tab-pane>

            <el-tab-pane name="orders" label="相关订单">
              <div class="reconciliation-tab-stack">
                <div class="workbench-summary-row">
                  <StatusChip>当前订单 <strong>{{ orderStats.total || 0 }}</strong></StatusChip>
                  <StatusChip variant="warning">缺 broker <strong>{{ orderStats.missing_broker_order_count || 0 }}</strong></StatusChip>
                  <StatusChip v-if="activeOrderFilterChips.length === 0" variant="muted">当前无额外筛选</StatusChip>
                  <StatusChip v-for="chip in activeOrderFilterChips" :key="chip" variant="muted">{{ chip }}</StatusChip>
                </div>
                <div class="reconciliation-order-toolbar">
                  <el-select v-model="orderFilters.state" placeholder="状态" clearable class="reconciliation-order-toolbar__control reconciliation-order-toolbar__control--select"><el-option v-for="item in orderStateOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select>
                  <el-input v-model="orderFilters.source" clearable placeholder="source" class="reconciliation-order-toolbar__control reconciliation-order-toolbar__control--query" />
                  <el-button @click="toggleAdvancedOrderFilters">{{ showAdvancedOrderFilters ? '收起筛选' : '高级筛选' }}</el-button>
                  <el-button @click="handleResetOrderFilters">重置</el-button>
                  <el-button type="primary" :loading="loadingOrders || loadingOrderStats" @click="handleApplyOrderFilters">刷新订单</el-button>
                </div>
                <div v-if="showAdvancedOrderFilters" class="filter-grid">
                  <el-input v-model="orderFilters.side" placeholder="方向 buy / sell" clearable />
                  <el-input v-model="orderFilters.strategy_name" placeholder="strategy_name" clearable />
                  <el-input v-model="orderFilters.account_type" placeholder="account_type" clearable />
                  <el-input v-model="orderFilters.internal_order_id" placeholder="internal_order_id" clearable />
                  <el-input v-model="orderFilters.request_id" placeholder="request_id" clearable />
                  <el-input v-model="orderFilters.broker_order_id" placeholder="broker_order_id" clearable />
                </div>
                <div class="reconciliation-tab-grid reconciliation-tab-grid--orders">
                  <article class="workbench-block reconciliation-block reconciliation-block--table" v-loading="loadingOrders">
                    <div class="reconciliation-block__head">订单列表</div>
                    <div class="reconciliation-table-wrap">
                      <el-empty v-if="orderRows.length === 0" description="当前筛选下没有订单。" />
                      <el-table v-else :data="orderRows" row-key="orderLookupId" size="small" border height="100%" highlight-current-row :current-row-key="selectedOrderId" @row-click="handleOrderRowClick">
                        <el-table-column label="标的" min-width="132"><template #default="{ row }"><div class="reconciliation-symbol-cell"><strong>{{ row.symbol || '-' }}</strong><span>{{ row.name || '-' }}</span></div></template></el-table-column>
                        <el-table-column label="更新时间" min-width="160"><template #default="{ row }">{{ formatOrderTimestamp(row.updated_at || row.created_at) }}</template></el-table-column>
                        <el-table-column prop="side" label="方向" width="78" />
                        <el-table-column label="状态" width="96"><template #default="{ row }"><StatusChip class="runtime-inline-status" :variant="row.state_chip_variant || 'muted'">{{ row.state_label || row.state || '-' }}</StatusChip></template></el-table-column>
                        <el-table-column label="委托价 / 量" min-width="126"><template #default="{ row }">{{ formatOrderPrice(row.price) }} / {{ formatOrderQuantity(row.quantity) }}</template></el-table-column>
                      </el-table>
                    </div>
                  </article>
                  <article class="workbench-block reconciliation-block reconciliation-block--detail" v-loading="loadingOrderDetail">
                    <div class="reconciliation-block__head">订单详情</div>
                    <template v-if="orderDetail">
                      <div class="reconciliation-scroll-block">
                        <el-descriptions :column="1" border size="small">
                        <el-descriptions-item label="order">{{ selectedOrderId || '-' }}</el-descriptions-item>
                        <el-descriptions-item label="symbol">{{ orderDetail.order.symbol || '-' }}</el-descriptions-item>
                        <el-descriptions-item label="state">{{ orderDetail.order.state_label || orderDetail.order.state || '-' }}</el-descriptions-item>
                        <el-descriptions-item label="request">{{ orderDetail.request.request_id || '-' }}</el-descriptions-item>
                        <el-descriptions-item label="scope">{{ orderDetail.request.scope_type || '-' }} / {{ orderDetail.request.scope_ref_id || '-' }}</el-descriptions-item>
                        </el-descriptions>
                        <div class="reconciliation-mini-table"><el-table :data="orderDetail.tradeRows" size="small" border><el-table-column prop="trade_fact_id" label="Trade Fact" min-width="128" /><el-table-column prop="quantity" label="Qty" width="84" /><el-table-column label="Price" width="84"><template #default="{ row }">{{ formatOrderPrice(row.price) }}</template></el-table-column></el-table></div>
                      </div>
                    </template>
                    <div v-else class="workbench-empty">先从左侧订单列表选择一笔订单。</div>
                  </article>
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane name="ledger" label="持仓账本">
              <div class="reconciliation-tab-stack">
                <div class="workbench-summary-row"><StatusChip variant="muted">open entry <strong>{{ workspaceEntries.length }}</strong></StatusChip><StatusChip variant="muted">当前 entry <strong>{{ selectedEntryId || '-' }}</strong></StatusChip><StatusChip variant="muted">slice 数 <strong>{{ selectedEntrySlices.length }}</strong></StatusChip></div>
                <div class="reconciliation-ledger-workspace">
                  <article class="workbench-block reconciliation-block reconciliation-block--table"><div class="reconciliation-block__head">Entry 列表</div><div class="reconciliation-table-wrap"><el-empty v-if="workspaceEntries.length === 0" description="当前 symbol 没有 open entry。" /><el-table v-else :data="workspaceEntries" row-key="entry_id" size="small" border height="100%" highlight-current-row :current-row-key="selectedEntryId" @row-click="handleEntryRowClick"><el-table-column prop="entry_short_id" label="entry_id" min-width="92" /><el-table-column label="买入时间" min-width="144"><template #default="{ row }">{{ row.buy_time_label || row.entrySummaryDisplay?.entryDateTimeLabel || '-' }}</template></el-table-column><el-table-column prop="entry_price_label" label="买入价" width="92" /><el-table-column prop="original_quantity" label="原始数量" width="92" /><el-table-column prop="remaining_quantity" label="剩余数量" width="92" /><el-table-column prop="entry_market_value_label" label="对应市值" width="92" /><el-table-column prop="remaining_ratio_label" label="剩余百分比" width="96" /></el-table></div></article>
                  <div class="reconciliation-ledger-side">
                    <article class="workbench-block reconciliation-block reconciliation-block--table reconciliation-ledger-side__top"><div class="reconciliation-block__head">Slice 列表</div><div class="reconciliation-table-wrap"><el-empty v-if="selectedEntrySlices.length === 0" description="当前 entry 没有 open slice。" /><el-table v-else :data="selectedEntrySlices" row-key="entry_slice_id" size="small" border height="100%"><el-table-column prop="entry_slice_short_id" label="slice_id" min-width="92" /><el-table-column prop="entry_short_id" label="entry_id" min-width="92" /><el-table-column prop="slice_seq" label="seq" width="72" /><el-table-column prop="guardian_price" label="guardian_price" width="108" /><el-table-column prop="remaining_quantity" label="剩余数量" width="92" /><el-table-column prop="remaining_amount_label" label="剩余市值" width="92" /></el-table></div></article>
                    <article class="workbench-block reconciliation-block reconciliation-block--detail reconciliation-ledger-side__bottom"><div class="reconciliation-block__head">Entry 详情</div><div v-if="selectedEntry" class="reconciliation-scroll-block"><el-descriptions :column="1" border size="small"><el-descriptions-item label="entry_id">{{ selectedEntry.entry_id || '-' }}</el-descriptions-item><el-descriptions-item label="entry_price">{{ selectedEntry.entry_price_label || '-' }}</el-descriptions-item><el-descriptions-item label="remaining">{{ selectedEntry.remaining_quantity ?? '-' }}</el-descriptions-item><el-descriptions-item label="stoploss">{{ selectedEntry.stoplossLabel || '-' }}</el-descriptions-item></el-descriptions></div><div v-else class="workbench-empty">请先选择一个 entry。</div></article>
                  </div>
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane name="resolution" label="Resolution">
              <div class="reconciliation-tab-stack reconciliation-tab-stack--fill">
                <div class="workbench-summary-row"><StatusChip variant="muted">gap / resolution / rejection <strong>{{ resolutionRows.length }}</strong></StatusChip><StatusChip variant="muted">TPSL 触发历史 <strong>{{ workspaceHistoryRows.length }}</strong></StatusChip><StatusChip v-if="resolutionEndpointMissing" variant="warning">Resolution 数据源 <strong>后端接口未部署</strong></StatusChip><StatusChip v-else-if="resolutionSymbolNotTracked" variant="warning">Resolution 数据源 <strong>symbol 未纳入对账</strong></StatusChip></div>
                <el-alert v-if="resolutionEndpointMissing" class="reconciliation-resolution-alert" type="warning" :closable="false" show-icon title="当前运行中的后端未暴露 reconciliation-workspace 接口，因此 Resolution 只能显示为空。" />
                <el-alert v-else-if="resolutionSymbolNotTracked" class="reconciliation-resolution-alert" type="warning" :closable="false" show-icon :title="resolutionSymbolNotTrackedTitle" />
                <article class="workbench-block reconciliation-block reconciliation-block--table"><div class="reconciliation-block__head">Resolution 列表</div><div class="reconciliation-table-wrap"><el-empty v-if="resolutionRows.length === 0" :description="resolutionEmptyDescription" /><el-table v-else :data="resolutionRows" row-key="row_id" size="small" border height="100%"><el-table-column label="类型" width="104"><template #default="{ row }"><StatusChip :variant="resolutionRowVariant(row.row_type)">{{ row.row_type }}</StatusChip></template></el-table-column><el-table-column prop="row_id" label="id" min-width="164" /><el-table-column prop="state" label="state" width="96" /><el-table-column prop="side" label="side" width="72" /><el-table-column prop="quantity_delta" label="quantity" width="92" /><el-table-column prop="resolution_type" label="resolution_type" min-width="144" /><el-table-column prop="time_label" label="时间" min-width="148" /></el-table></div></article>
                <article class="workbench-block reconciliation-block reconciliation-block--table"><div class="reconciliation-block__head">TPSL / 触发历史</div><div class="reconciliation-table-wrap"><el-empty v-if="workspaceHistoryRows.length === 0" description="当前没有历史事件。" /><el-table v-else :data="workspaceHistoryRows" size="small" border height="100%"><el-table-column prop="kind" label="kind" width="92" /><el-table-column prop="created_at" label="created_at" min-width="156" /><el-table-column prop="batch_id" label="batch_id" min-width="132" /><el-table-column prop="entry_label" label="entry" min-width="132" /><el-table-column prop="downstreamLabel" label="downstream" min-width="168" /></el-table></div></article>
              </div>
            </el-tab-pane>
          </el-tabs>
        </WorkbenchDetailPanel>
      </div>
    </div>
  </WorkbenchPage>
</template>

<script setup>
import { computed, onMounted, ref, toRefs, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import StatusChip from '../components/workbench/StatusChip.vue'
import WorkbenchDetailPanel from '../components/workbench/WorkbenchDetailPanel.vue'
import WorkbenchLedgerPanel from '../components/workbench/WorkbenchLedgerPanel.vue'
import WorkbenchPage from '../components/workbench/WorkbenchPage.vue'
import WorkbenchToolbar from '../components/workbench/WorkbenchToolbar.vue'
import { orderManagementApi } from '@/api/orderManagementApi'
import { positionManagementApi } from '@/api/positionManagementApi'
import { tpslApi } from '@/api/tpslApi'
import MyHeader from './MyHeader.vue'
import { ORDER_STATE_FILTER_OPTIONS, formatOrderPrice, formatOrderQuantity, formatOrderTimestamp } from './orderManagement.mjs'
import { AUDIT_STATUS_META, RECONCILIATION_STATE_META } from './reconciliationStateMeta.mjs'
import { createReconciliationWorkbenchActions } from './reconciliationWorkbench.mjs'
import { createDefaultReconciliationOrderFilters } from './reconciliationWorkbenchPage.mjs'
import { createReconciliationWorkbenchPageController } from './reconciliationWorkbenchPage.mjs'

const route = useRoute()
const router = useRouter()
const normalizeTab = (value) => {
  const normalized = String(value || '').trim()
  if (['entries', 'slices'].includes(normalized)) return 'ledger'
  return ['overview', 'orders', 'ledger', 'resolution'].includes(normalized) ? normalized : 'overview'
}
const normalizeQueryValue = (value) => { const text = String(value || '').trim(); return text || undefined }
const resolveOrderLookupId = (row = {}) => String(row?.orderLookupId || row?.internal_order_id || row?.broker_order_id || row?.broker_order_key || '').trim()
const resolutionRowVariant = (rowType) => rowType === 'gap' ? 'warning' : rowType === 'resolution' ? 'success' : rowType === 'rejection' ? 'danger' : 'muted'

const actions = createReconciliationWorkbenchActions({ positionApi: positionManagementApi, orderApi: orderManagementApi, tpslApi, reconciliationApi: positionManagementApi })
const controller = createReconciliationWorkbenchPageController({ actions })
const { state, filteredOverviewRows, selectedEntry, selectedEntrySlices, refreshOverview, selectSymbol, setActiveTab, selectOrder, selectEntry, applyLookup, resetSelection, syncSelectedOrder, refreshOrderRows, refreshOrderStats } = controller
const { loadingOverview, loadingOrders, loadingOrderStats, loadingOrderDetail, loadingWorkspace, pageError, lookupDraft, activeTab, overviewRows, overviewSummary, overviewFilters, selectedSymbol, orderFilters, orderRows, orderStats, orderDetail, selectedOrderId, orderPage, workspaceDetail, selectedEntryId } = toRefs(state)

const showAdvancedOrderFilters = ref(false)
const routeReady = ref(false)
const syncingRoute = ref(false)
const orderStateOptions = ORDER_STATE_FILTER_OPTIONS
const overviewAuditOptions = Object.values(AUDIT_STATUS_META).map((item) => ({ value: item.key, label: `${item.key} / ${item.label}` }))
const overviewStateOptions = Object.values(RECONCILIATION_STATE_META).map((item) => ({ value: item.key, label: item.label }))
const activeTabLabel = computed(() => activeTab.value === 'orders' ? '相关订单' : activeTab.value === 'ledger' ? '持仓账本' : activeTab.value === 'resolution' ? 'Resolution' : '概览')
const selectedOverviewRow = computed(() => overviewRows.value.find((row) => row.symbol === selectedSymbol.value) || null)
const selectedOverviewRuleRows = computed(() => selectedOverviewRow.value?.rule_badges || [])
const selectedOverviewSurfaceRows = computed(() => selectedOverviewRow.value?.surface_sections || [])
const workspaceEntries = computed(() => workspaceDetail.value?.entries || [])
const workspaceHistoryRows = computed(() => workspaceDetail.value?.historyRows || [])
const workspaceResolutionStatus = computed(() => String(workspaceDetail.value?.resolutionDataStatus || 'loaded').trim() || 'loaded')
const workspaceResolutionErrorMessage = computed(() => String(workspaceDetail.value?.resolutionErrorMessage || '').trim())
const summaryChips = computed(() => ({ totalSymbols: overviewSummary.value?.row_count || 0, errorCount: overviewSummary.value?.audit_status_counts?.ERROR || 0, warnCount: overviewSummary.value?.audit_status_counts?.WARN || 0, okCount: overviewSummary.value?.audit_status_counts?.OK || 0, openGapCount: overviewRows.value.reduce((sum, row) => sum + Number(row?.reconciliation?.open_gap_count || 0), 0), missingBrokerCount: orderStats.value?.missing_broker_order_count || 0 }))
const activeOrderFilterChips = computed(() => [['side', '方向'], ['state', '状态'], ['source', 'source'], ['strategy_name', 'strategy'], ['account_type', '账户'], ['internal_order_id', 'internal'], ['request_id', 'request'], ['broker_order_id', 'broker']].map(([key, label]) => { const value = String(orderFilters.value?.[key] || '').trim(); return value ? `${label}: ${value}` : '' }).filter(Boolean))
const resolutionRows = computed(() => [...(workspaceDetail.value?.gaps || []).map((row) => ({ ...row, row_type: 'gap', row_id: row.gap_id || `${selectedSymbol.value}-gap`, time_label: formatOrderTimestamp(row.detected_at || row.pending_until || row.confirmed_at) })), ...(workspaceDetail.value?.resolutions || []).map((row) => ({ ...row, row_type: 'resolution', row_id: row.resolution_id || `${selectedSymbol.value}-resolution`, time_label: formatOrderTimestamp(row.created_at || row.confirmed_at || row.resolved_at) })), ...(workspaceDetail.value?.rejections || []).map((row) => ({ ...row, row_type: 'rejection', row_id: row.rejection_id || `${selectedSymbol.value}-rejection`, time_label: formatOrderTimestamp(row.trade_time || row.detected_at || row.created_at) }))])
const resolutionEndpointMissing = computed(() => workspaceResolutionStatus.value === 'workspace_endpoint_missing')
const resolutionSymbolNotTracked = computed(() => workspaceResolutionStatus.value === 'workspace_symbol_not_tracked')
const resolutionSymbolNotTrackedTitle = computed(() => workspaceResolutionErrorMessage.value || '当前 symbol 未纳入对账跟踪，因此 Resolution 暂无可展示明细。')
const resolutionEmptyDescription = computed(() => {
  if (resolutionEndpointMissing.value) return '当前运行中的后端未暴露 reconciliation-workspace 接口，因此 Resolution 只能显示为空。'
  if (resolutionSymbolNotTracked.value) return resolutionSymbolNotTrackedTitle.value
  return '当前 symbol 暂无 gap / resolution / rejection 明细。'
})
const buildRouteQuery = () => ({ symbol: normalizeQueryValue(selectedSymbol.value), tab: activeTab.value === 'overview' ? undefined : normalizeQueryValue(activeTab.value), order: activeTab.value === 'orders' ? normalizeQueryValue(selectedOrderId.value) : undefined, entry: activeTab.value === 'ledger' ? normalizeQueryValue(selectedEntryId.value) : undefined })
const routeQueryChanged = (nextQuery) => ['symbol', 'tab', 'order', 'entry'].some((key) => normalizeQueryValue(route.query[key]) !== nextQuery[key])
const syncRouteFromState = async () => { const nextQuery = buildRouteQuery(); if (!routeQueryChanged(nextQuery)) return; syncingRoute.value = true; try { await router.replace({ query: { ...route.query, ...nextQuery } }) } finally { syncingRoute.value = false } }
const handleRefresh = async () => { await refreshOverview(); await syncRouteFromState() }
const handleApplyLookup = async () => { await applyLookup(); await syncRouteFromState() }
const handleResetSelection = async () => { await resetSelection(); await syncRouteFromState() }
const handleOverviewRowClick = async (row) => { await selectSymbol(row?.symbol); await syncRouteFromState() }
const handleTabChange = async (nextTab) => { setActiveTab(nextTab); await syncRouteFromState() }
const handleOrderRowClick = async (row) => { await selectOrder(resolveOrderLookupId(row)); await syncRouteFromState() }
const handleEntryRowClick = async (row) => { selectEntry(row?.entry_id); await syncRouteFromState() }
const handleApplyOrderFilters = async () => { orderPage.value = 1; await refreshOrderRows(); await refreshOrderStats(); await syncSelectedOrder(); await syncRouteFromState() }
const handleResetOrderFilters = async () => { state.orderFilters = { ...createDefaultReconciliationOrderFilters(), symbol: selectedSymbol.value || '' }; orderPage.value = 1; await refreshOrderRows(); await refreshOrderStats(); await syncSelectedOrder(); await syncRouteFromState() }
const toggleAdvancedOrderFilters = () => { showAdvancedOrderFilters.value = !showAdvancedOrderFilters.value }

watch(() => [selectedSymbol.value, activeTab.value, selectedOrderId.value, selectedEntryId.value], async () => { if (!routeReady.value || syncingRoute.value) return; await syncRouteFromState() })

onMounted(async () => {
  lookupDraft.value = String(route.query.symbol || route.query.order || '').trim()
  setActiveTab(normalizeTab(route.query.tab))
  await refreshOverview()
  if (route.query.symbol && route.query.symbol !== selectedSymbol.value) await selectSymbol(route.query.symbol)
  if (route.query.order && route.query.order !== selectedOrderId.value) await selectOrder(route.query.order)
  if (route.query.entry) selectEntry(route.query.entry)
  routeReady.value = true
  await syncRouteFromState()
})
</script>

<style scoped>
.reconciliation-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.reconciliation-toolbar__symbol-input {
  width: min(560px, 42vw);
  min-width: 320px;
}

.reconciliation-layout {
  display: grid;
  grid-template-columns: minmax(360px, 0.9fr) minmax(0, 1.35fr);
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.reconciliation-ledger-panel,
.reconciliation-detail-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.reconciliation-panel__filters {
  flex: 1 1 auto;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
  flex-wrap: nowrap;
  min-width: 0;
}

.reconciliation-panel__filter {
  min-width: 0;
}

.reconciliation-panel__filter--query {
  flex: 0 1 240px;
  width: 240px;
}

.reconciliation-panel__filter--select {
  flex: 0 0 168px;
  width: 168px;
}

.reconciliation-symbol-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  min-width: 0;
}

.reconciliation-symbol-cell span {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  line-height: 1.3;
  color: #6b7280;
}

.reconciliation-chip-wrap {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}

.reconciliation-table-wrap {
  flex: 1 1 auto;
  min-height: 0;
  min-width: 0;
  overflow-y: auto;
  overflow-x: auto;
  scrollbar-gutter: stable both-edges;
}

.reconciliation-table-wrap :deep(.el-table) {
  height: 100%;
}

.reconciliation-tabs {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.reconciliation-tabs :deep(.el-tabs__header) {
  margin-bottom: 10px;
}

.reconciliation-tabs :deep(.el-tabs__content) {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.reconciliation-tabs :deep(.el-tab-pane) {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.reconciliation-tab-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.reconciliation-tab-stack--fill > .reconciliation-block {
  flex: 1 1 0;
}

.reconciliation-tab-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.reconciliation-tab-grid--orders {
  grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr);
}

.reconciliation-ledger-workspace {
  display: grid;
  grid-template-columns: minmax(280px, 0.95fr) minmax(0, 1.05fr);
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.reconciliation-ledger-side {
  display: grid;
  grid-template-rows: repeat(2, minmax(0, 1fr));
  gap: 12px;
  min-height: 0;
  overflow: hidden;
}

.reconciliation-ledger-side__top,
.reconciliation-ledger-side__bottom {
  min-height: 0;
}

.reconciliation-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  overflow: hidden;
}

.reconciliation-block--table,
.reconciliation-block--detail,
.reconciliation-block--fill {
  flex: 1 1 0;
}

.reconciliation-block__head {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.reconciliation-order-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.reconciliation-order-toolbar__control {
  min-width: 0;
}

.reconciliation-order-toolbar__control--select {
  width: 168px;
}

.reconciliation-order-toolbar__control--query {
  width: min(320px, 100%);
}

.filter-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.reconciliation-scroll-block {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  scrollbar-gutter: stable both-edges;
}

.reconciliation-mini-table {
  min-height: 180px;
}

.reconciliation-resolution-alert {
  margin: 0;
}

@media (max-width: 1440px) {
  .reconciliation-panel__filters {
    justify-content: flex-start;
    flex-wrap: wrap;
  }

  .reconciliation-layout {
    grid-template-columns: minmax(300px, 0.85fr) minmax(0, 1.15fr);
  }

  .reconciliation-tab-grid,
  .reconciliation-tab-grid--orders,
  .reconciliation-ledger-workspace {
    grid-template-columns: 1fr;
  }

  .reconciliation-ledger-side {
    grid-template-rows: minmax(220px, 1fr) minmax(180px, 0.9fr);
  }

  .filter-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 960px) {
  .reconciliation-toolbar__symbol-input,
  .reconciliation-panel__filter--query,
  .reconciliation-panel__filter--select,
  .reconciliation-order-toolbar__control--select,
  .reconciliation-order-toolbar__control--query {
    width: 100%;
    min-width: 0;
    flex: 1 1 100%;
  }

  .reconciliation-layout {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(260px, 0.9fr) minmax(320px, 1.1fr);
  }

  .filter-grid {
    grid-template-columns: 1fr;
  }
}
</style>
