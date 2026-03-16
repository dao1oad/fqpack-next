<template>
  <div class="workbench-page tpsl-page">
    <MyHeader />

    <div class="workbench-body tpsl-body">
      <section class="workbench-toolbar">
        <div class="workbench-toolbar__header">
          <div class="workbench-title-group">
            <div class="workbench-page-title">股票止盈止损管理</div>
            <div class="workbench-page-meta">
              <span>按标的维护止盈层次，按买入 lot 维护止损，并在同页追触发后的订单与成交。</span>
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
          <span class="workbench-summary-chip">
            标的数 <strong>{{ overviewRows.length }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--success">
            持仓中 <strong>{{ holdingCount }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--warning">
            活跃止损 <strong>{{ activeStoplossCount }}</strong>
          </span>
          <span v-if="detail" class="workbench-summary-chip workbench-summary-chip--muted">
            止盈层 <strong>{{ detail.takeprofitTierCount }}</strong>
          </span>
          <span v-if="detail" class="workbench-summary-chip workbench-summary-chip--muted">
            open buy lot <strong>{{ detail.buyLots.length }}</strong>
          </span>
          <span v-if="detail" class="workbench-summary-chip workbench-summary-chip--muted">
            历史 <strong>{{ detail.historyRows.length }}</strong>
          </span>
        </div>
      </section>

      <div class="tpsl-layout">
        <aside class="workbench-panel tpsl-sidebar-panel">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">标的列表</div>
              <p class="workbench-panel__desc">按标的切换止盈层次、stoploss buy lot 和统一触发历史。</p>
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
                <span class="workbench-summary-chip workbench-summary-chip--muted">
                  {{ row.position_amount_label }}
                </span>
              </div>

              <div class="symbol-card-badges">
                <span
                  v-for="badge in row.badges"
                  :key="`${row.symbol}-${badge}`"
                  class="workbench-summary-chip workbench-summary-chip--muted"
                >
                  {{ badge }}
                </span>
                <span
                  v-if="row.badges.length === 0"
                  class="workbench-summary-chip workbench-summary-chip--muted"
                >
                  未配置
                </span>
              </div>

              <div class="symbol-card-foot">
                <span>止损 lot {{ row.active_stoploss_buy_lot_count || 0 }}</span>
                <span>{{ row.last_trigger_label }} · {{ row.last_trigger_time }}</span>
              </div>
            </button>
          </div>
        </aside>

        <main class="tpsl-main-stack">
          <section v-if="detail" class="workbench-panel">
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
                  <span>open buy lot {{ detail.buyLots.length }} 个</span>
                </div>
              </div>

              <div class="workbench-toolbar__actions">
                <el-button :loading="loadingDetail" @click="reloadCurrentSymbol">刷新详情</el-button>
              </div>
            </div>
          </section>

          <section v-if="detail" class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">标的止盈层次</div>
                <p class="workbench-panel__desc">编辑价位，或直接按层级启停并 rearm。</p>
              </div>
              <div class="workbench-panel__actions">
                <el-button @click="addTier">新增层级</el-button>
                <el-button type="warning" :disabled="!selectedSymbol" @click="handleRearm">Rearm</el-button>
                <el-button type="primary" :loading="savingTakeprofit" :disabled="!selectedSymbol" @click="handleSaveTakeprofit">
                  保存层级
                </el-button>
              </div>
            </div>

            <el-empty v-if="takeprofitDrafts.length === 0" description="还没有止盈层次，先新增一层。" />
            <el-table v-else :data="takeprofitDrafts" stripe size="small" border>
              <el-table-column label="Level" width="84">
                <template #default="{ row }">
                  <strong>L{{ row.level }}</strong>
                </template>
              </el-table-column>
              <el-table-column label="Price" min-width="160">
                <template #default="{ row }">
                  <el-input-number v-model="row.price" :min="0" :step="0.01" :precision="2" controls-position="right" />
                </template>
              </el-table-column>
              <el-table-column label="Manual" width="124">
                <template #default="{ row }">
                  <el-switch
                    :model-value="Boolean(row.manual_enabled)"
                    inline-prompt
                    active-text="开"
                    inactive-text="关"
                    @change="(value) => handleToggleTier(row.level, value)"
                  />
                </template>
              </el-table-column>
              <el-table-column label="Armed" width="100">
                <template #default="{ row }">
                  <el-tag :type="armedLevels[String(row.level)] ? 'success' : 'info'">
                    {{ armedLevels[String(row.level)] ? '已布防' : '未布防' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="84">
                <template #default="{ row }">
                  <el-button text type="danger" @click="removeTier(row.level)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </section>

          <section v-if="detail" class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">按买入订单止损</div>
                <p class="workbench-panel__desc">只展示 open buy lot。每行可单独设置 stop_price 和 enabled。</p>
              </div>
            </div>

            <el-table :data="detail.buyLots" stripe size="small" border>
              <el-table-column prop="buy_lot_id" label="Buy Lot" min-width="176" />
              <el-table-column label="买入时间" min-width="146">
                <template #default="{ row }">
                  {{ row.date || '-' }} {{ row.time || '' }}
                </template>
              </el-table-column>
              <el-table-column label="买入价" width="92">
                <template #default="{ row }">
                  {{ row.buy_price_real }}
                </template>
              </el-table-column>
              <el-table-column label="原始/剩余" width="118">
                <template #default="{ row }">
                  {{ row.original_quantity }} / {{ row.remaining_quantity }}
                </template>
              </el-table-column>
              <el-table-column label="Stop Price" min-width="176">
                <template #default="{ row }">
                  <el-input-number
                    v-model="stoplossDrafts[row.buy_lot_id].stop_price"
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
                    v-model="stoplossDrafts[row.buy_lot_id].enabled"
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
                    :loading="savingStoploss[row.buy_lot_id]"
                    @click="handleSaveStoploss(row.buy_lot_id)"
                  >
                    保存
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </section>

          <section v-if="detail" class="workbench-panel">
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
              <el-table-column prop="buy_lot_label" label="影响 buy lot" min-width="120" />
              <el-table-column prop="downstreamLabel" label="后续结果" min-width="160" />
              <el-table-column label="明细" min-width="260">
                <template #default="{ row }">
                  <div class="history-chip-row">
                    <span
                      v-for="request in row.order_requests || []"
                      :key="request.request_id"
                      class="workbench-summary-chip workbench-summary-chip--muted"
                    >
                      request {{ request.request_id }}
                    </span>
                    <span
                      v-for="order in row.orders || []"
                      :key="order.internal_order_id"
                      class="workbench-summary-chip workbench-summary-chip--muted"
                    >
                      order {{ order.internal_order_id }} · {{ order.state }}
                    </span>
                    <span
                      v-for="trade in row.trades || []"
                      :key="trade.trade_fact_id"
                      class="workbench-summary-chip workbench-summary-chip--muted"
                    >
                      trade {{ trade.trade_fact_id }} · {{ trade.quantity }}@{{ trade.price }}
                    </span>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </section>

          <section v-else class="workbench-empty">
            左侧先选择一个标的。
          </section>
        </main>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, toRefs } from 'vue'
import { ElMessage } from 'element-plus'

import { tpslApi } from '@/api/tpslApi'
import MyHeader from '@/views/MyHeader.vue'
import { createTpslManagementActions } from '@/views/tpslManagement.mjs'
import { createTpslManagementPageController } from '@/views/tpslManagementPage.mjs'

const actions = createTpslManagementActions(tpslApi)
const {
  state,
  holdingCount,
  activeStoplossCount,
  armedLevels,
  refreshOverview,
  selectSymbol,
  reloadCurrentSymbol,
  addTier,
  removeTier,
  handleSaveTakeprofit,
  handleToggleTier,
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
  savingTakeprofit,
  pageError,
  overviewRows,
  selectedSymbol,
  detail,
  takeprofitDrafts,
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
.history-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.history-filter {
  width: 120px;
}

@media (max-width: 1180px) {
  .tpsl-layout {
    grid-template-columns: 1fr;
  }
}
</style>
