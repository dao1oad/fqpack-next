<template>
  <WorkbenchPage class="tpsl-page">
    <MyHeader />

    <div class="workbench-body tpsl-body">
      <WorkbenchToolbar class="tpsl-toolbar">
        <div class="workbench-toolbar__header">
          <div class="workbench-title-group">
            <div class="workbench-page-title">股票止盈止损管理</div>
            <div class="workbench-page-meta">
              <span>左侧只读展示三层止盈价格，右侧按持仓 entry 维护止损，并同页对照 entry ledger、对账状态与触发后订单成交。</span>
              <template v-if="detail">
                <span>/</span>
                <span>当前标的 <span class="workbench-code">{{ detail.symbol }}</span></span>
              </template>
            </div>
          </div>

          <div class="workbench-toolbar__actions">
            <el-button type="primary" :loading="loadingOverview" @click="refreshOverview">刷新</el-button>
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

        <div class="workbench-summary-row">
          <StatusChip>
            标的数 <strong>{{ overviewRows.length }}</strong>
          </StatusChip>
          <StatusChip variant="success">
            持仓中 <strong>{{ holdingCount }}</strong>
          </StatusChip>
          <StatusChip variant="warning">
            活跃止损 <strong>{{ activeStoplossCount }}</strong>
          </StatusChip>
          <StatusChip v-if="detail" variant="muted">
            止盈层 <strong>{{ detail.takeprofitTierCount }}</strong>
          </StatusChip>
          <StatusChip v-if="detail" variant="muted">
            open entry <strong>{{ detail.entries.length }}</strong>
          </StatusChip>
          <StatusChip v-if="detail" variant="muted">
            entry slice <strong>{{ detail.entrySlices.length }}</strong>
          </StatusChip>
          <StatusChip v-if="detail" :variant="detail.reconciliation.state_chip_variant">
            对账 <strong>{{ detail.reconciliation.state_label || '-' }}</strong>
          </StatusChip>
          <StatusChip v-if="detail" variant="muted">
            历史 <strong>{{ detail.historyRows.length }}</strong>
          </StatusChip>
        </div>
      </WorkbenchToolbar>

      <div class="tpsl-layout">
        <WorkbenchSidebarPanel class="tpsl-sidebar-panel">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">标的列表</div>
              <p class="workbench-panel__desc">按标的切换只读止盈三层、entry 止损、entry slice ledger、对账状态和统一触发历史。</p>
            </div>
            <div class="workbench-panel__meta">
              <span>{{ overviewRows.length }} 个标的</span>
            </div>
          </div>

          <div class="symbol-list">
            <button
              v-for="row in overviewRows"
              :key="row.symbol"
              type="button"
              class="symbol-card"
              :class="{ active: row.symbol === selectedSymbol }"
              @click="selectSymbol(row.symbol)"
            >
              <div class="symbol-card-head">
                <div>
                  <strong>{{ row.name || row.symbol }}</strong>
                  <span>{{ row.symbol }}</span>
                </div>
                <StatusChip variant="muted">
                  {{ row.position_amount_label }}
                </StatusChip>
              </div>

              <div class="symbol-card-badges">
                <StatusChip
                  v-for="badge in row.badges"
                  :key="`${row.symbol}-${badge}`"
                  variant="muted"
                >
                  {{ badge }}
                </StatusChip>
                <StatusChip
                  v-if="row.badges.length === 0"
                  variant="muted"
                >
                  未配置
                </StatusChip>
              </div>

              <div class="symbol-card-tiers">
                <StatusChip
                  v-for="tierLabel in row.takeprofitSummary"
                  :key="`${row.symbol}-${tierLabel}`"
                  variant="muted"
                >
                  {{ tierLabel }}
                </StatusChip>
              </div>

              <div class="symbol-card-foot">
                <span>止损 entry {{ row.active_stoploss_entry_count || 0 }}</span>
                <span>{{ row.last_trigger_label }} · {{ row.last_trigger_time }}</span>
              </div>
            </button>
          </div>
        </WorkbenchSidebarPanel>

        <main class="tpsl-main-stack">
          <WorkbenchDetailPanel v-if="detail" class="tpsl-detail-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">
                  {{ detail.name || detail.symbol }}
                  <span class="workbench-muted workbench-code">{{ detail.symbol }}</span>
                </div>
                <div class="workbench-panel__meta">
                  <span>当前持仓 {{ detail.position.quantity || 0 }} 股</span>
                  <span>/</span>
                  <span>实时仓位 {{ detail.positionAmountLabel }}</span>
                  <span>/</span>
                  <span>止盈层 {{ detail.takeprofitTierCount }} 个</span>
                  <span>/</span>
                  <span>open entry {{ detail.entries.length }} 个</span>
                </div>
              </div>

              <div class="workbench-toolbar__actions">
                <el-button :loading="loadingDetail" @click="reloadCurrentSymbol">刷新详情</el-button>
                <el-button type="warning" :disabled="!detail.takeprofitTierCount" @click="handleRearm">Rearm</el-button>
              </div>
            </div>
          </WorkbenchDetailPanel>

          <WorkbenchLedgerPanel v-if="detail" class="tpsl-ledger-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">按持仓入口止损</div>
                <p class="workbench-panel__desc">只展示 open entry。每行可单独设置 stop_price 和 enabled。</p>
              </div>
            </div>

            <el-table :data="detail.entries" stripe size="small" border>
              <el-table-column prop="entry_id" label="Entry" min-width="176" />
              <el-table-column label="买入时间" min-width="176">
                <template #default="{ row }">
                  {{ row.buy_time_label || '-' }}
                </template>
              </el-table-column>
              <el-table-column label="买入价" width="92">
                <template #default="{ row }">
                  {{ row.buy_price_real }}
                </template>
              </el-table-column>
              <el-table-column label="原始/剩余" width="156">
                <template #default="{ row }">
                  {{ row.original_quantity }} / {{ row.remaining_quantity }}
                </template>
              </el-table-column>
              <el-table-column label="Stop Price" min-width="176">
                <template #default="{ row }">
                  <el-input-number
                    v-model="stoplossDrafts[row.entry_id].stop_price"
                    :min="0"
                    :step="0.01"
                    :precision="2"
                    controls-position="right"
                  />
                </template>
              </el-table-column>
              <el-table-column label="Enabled" width="116">
                <template #default="{ row }">
                  <el-switch
                    v-model="stoplossDrafts[row.entry_id].enabled"
                    inline-prompt
                    active-text="开"
                    inactive-text="关"
                  />
                </template>
              </el-table-column>
              <el-table-column label="卖出摘要" min-width="136">
                <template #default="{ row }">
                  {{ row.sellHistoryLabel }}
                </template>
              </el-table-column>
              <el-table-column label="操作" width="88">
                <template #default="{ row }">
                  <el-button
                    type="primary"
                    text
                    :loading="savingStoploss[row.entry_id]"
                    @click="handleSaveStoploss(row.entry_id)"
                  >
                    保存
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </WorkbenchLedgerPanel>

          <WorkbenchLedgerPanel v-if="detail" class="tpsl-ledger-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">Entry Slice Ledger</div>
                <p class="workbench-panel__desc">展示当前 entry 切片账本，方便和止盈止损批次、实际成交以及剩余数量对照。</p>
              </div>
            </div>

            <el-empty v-if="detail.entrySlices.length === 0" description="当前没有 entry slice 记录。" />
            <el-table v-else :data="detail.entrySlices" stripe size="small" border>
              <el-table-column prop="entry_slice_id" label="Slice" min-width="164" />
              <el-table-column prop="entry_id" label="Entry" min-width="164" />
              <el-table-column prop="guardian_price" label="Guardian 价" width="100" />
              <el-table-column prop="original_quantity" label="原始数量" width="96" />
              <el-table-column prop="remaining_quantity" label="剩余数量" width="96" />
              <el-table-column prop="status" label="状态" width="96" />
            </el-table>
          </WorkbenchLedgerPanel>

          <WorkbenchLedgerPanel v-if="detail" class="tpsl-ledger-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">对账状态</div>
                <p class="workbench-panel__desc">展示券商持仓与系统 ledger 的差额状态，不再把自动平账伪装成外部订单。</p>
              </div>
            </div>

            <div class="workbench-summary-row">
              <StatusChip :variant="detail.reconciliation.state_chip_variant">
                状态 <strong>{{ detail.reconciliation.state_label || '-' }}</strong>
              </StatusChip>
              <StatusChip variant="muted">
                signed gap <strong>{{ detail.reconciliation.signed_gap_quantity || 0 }}</strong>
              </StatusChip>
              <StatusChip variant="muted">
                open gap <strong>{{ detail.reconciliation.open_gap_count || 0 }}</strong>
              </StatusChip>
              <StatusChip variant="muted">
                最新 resolution <strong>{{ detail.reconciliation.latest_resolution_type || '-' }}</strong>
              </StatusChip>
            </div>
          </WorkbenchLedgerPanel>

          <WorkbenchLedgerPanel v-if="detail" class="tpsl-ledger-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">统一触发历史</div>
                <p class="workbench-panel__desc">同页查看 takeprofit / stoploss 触发，以及后续 request、order、trade。</p>
              </div>
              <div class="workbench-panel__actions">
                <el-select v-model="historyKind" class="history-filter" @change="loadHistory">
                  <el-option label="全部" value="all" />
                  <el-option label="止盈" value="takeprofit" />
                  <el-option label="止损" value="stoploss" />
                </el-select>
                <el-button :loading="loadingHistory" @click="loadHistory">刷新历史</el-button>
              </div>
            </div>

            <el-empty v-if="detail.historyRows.length === 0" description="当前没有历史事件。" />
            <el-table v-else :data="detail.historyRows" size="small" border>
              <el-table-column prop="kind" label="类型" width="96" />
              <el-table-column prop="created_at" label="触发时间" min-width="172" />
              <el-table-column prop="batch_id" label="Batch" min-width="128" />
              <el-table-column prop="triggerLabel" label="层级/止损价" min-width="110" />
              <el-table-column prop="triggerPriceLabel" label="触发价" width="88" />
              <el-table-column prop="entry_label" label="影响 entry" min-width="120" />
              <el-table-column prop="downstreamLabel" label="后续结果" min-width="160" />
              <el-table-column label="明细" min-width="260">
                <template #default="{ row }">
                  <div class="history-chip-row">
                    <StatusChip
                      v-for="request in row.order_requests || []"
                      :key="request.request_id"
                      variant="muted"
                    >
                      request {{ request.request_id }}
                    </StatusChip>
                    <StatusChip
                      v-for="order in row.orders || []"
                      :key="order.internal_order_id"
                      variant="muted"
                    >
                      order {{ order.internal_order_id }} · {{ order.state }}
                    </StatusChip>
                    <StatusChip
                      v-for="trade in row.trades || []"
                      :key="trade.trade_fact_id"
                      variant="muted"
                    >
                      trade {{ trade.trade_fact_id }} · {{ trade.quantity }}@{{ trade.price }}
                    </StatusChip>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </WorkbenchLedgerPanel>

          <section v-else class="workbench-empty">
            左侧先选择一个标的。
          </section>
        </main>
      </div>
    </div>
  </WorkbenchPage>
</template>

<script setup>
import { onMounted, toRefs } from 'vue'
import { ElMessage } from 'element-plus'

import StatusChip from '../components/workbench/StatusChip.vue'
import WorkbenchDetailPanel from '../components/workbench/WorkbenchDetailPanel.vue'
import WorkbenchLedgerPanel from '../components/workbench/WorkbenchLedgerPanel.vue'
import WorkbenchPage from '../components/workbench/WorkbenchPage.vue'
import WorkbenchSidebarPanel from '../components/workbench/WorkbenchSidebarPanel.vue'
import WorkbenchToolbar from '../components/workbench/WorkbenchToolbar.vue'
import { tpslApi } from '@/api/tpslApi'
import MyHeader from '@/views/MyHeader.vue'
import { createTpslManagementActions } from '@/views/tpslManagement.mjs'
import { createTpslManagementPageController } from '@/views/tpslManagementPage.mjs'

const actions = createTpslManagementActions(tpslApi)
const {
  state,
  holdingCount,
  activeStoplossCount,
  refreshOverview,
  selectSymbol,
  reloadCurrentSymbol,
  handleRearm,
  handleSaveStoploss,
  loadHistory,
} = createTpslManagementPageController({
  actions,
  notify: ElMessage,
})

const {
  loadingOverview,
  loadingDetail,
  loadingHistory,
  pageError,
  overviewRows,
  selectedSymbol,
  detail,
  historyKind,
  stoplossDrafts,
  savingStoploss,
} = toRefs(state)

onMounted(async () => {
  await refreshOverview()
})
</script>

<style scoped>
.tpsl-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.tpsl-layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
}

.tpsl-sidebar-panel,
.tpsl-main-stack {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.symbol-list,
.tpsl-main-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
}

.symbol-list {
  flex: 1 1 auto;
  overflow: auto;
  padding-right: 4px;
  scrollbar-gutter: stable;
}

.tpsl-main-stack {
  overflow: auto;
}

.symbol-card {
  width: 100%;
  padding: 12px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fff;
  text-align: left;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.symbol-card:hover,
.symbol-card.active {
  border-color: #409eff;
  box-shadow: 0 0 0 1px rgba(64, 158, 255, 0.16);
}

.symbol-card-head,
.symbol-card-foot {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}

.symbol-card-head strong {
  display: block;
  color: #303133;
}

.symbol-card-head span,
.symbol-card-foot {
  color: #606266;
  font-size: 12px;
}

.symbol-card-badges,
.symbol-card-tiers,
.history-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.history-filter {
  width: 120px;
}

@media (max-width: 1320px) {
  .tpsl-layout {
    grid-template-columns: 1fr;
  }
}
</style>
