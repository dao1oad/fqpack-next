<template>
  <div class="tpsl-page">
    <MyHeader />

    <div class="tpsl-shell">
      <aside class="tpsl-sidebar">
        <div class="sidebar-head">
          <div>
            <p class="eyebrow">Stock TPSL</p>
            <h1>股票止盈止损管理</h1>
            <p class="sidebar-copy">按标的维护止盈层次，按买入 lot 维护止损，并在同页追触发后的订单与成交。</p>
          </div>
          <el-button type="primary" :loading="loadingOverview" @click="refreshOverview">刷新</el-button>
        </div>

        <el-alert
          v-if="pageError"
          class="page-alert"
          type="error"
          :title="pageError"
          :closable="false"
          show-icon
        />

        <div class="overview-metrics">
          <article>
            <span>标的数</span>
            <strong>{{ overviewRows.length }}</strong>
          </article>
          <article>
            <span>持仓中</span>
            <strong>{{ holdingCount }}</strong>
          </article>
          <article>
            <span>活跃止损</span>
            <strong>{{ activeStoplossCount }}</strong>
          </article>
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
              <span class="position-pill">{{ row.position_quantity || 0 }} 股</span>
            </div>
            <div class="symbol-card-badges">
              <span v-for="badge in row.badges" :key="`${row.symbol}-${badge}`">{{ badge }}</span>
              <span v-if="row.badges.length === 0">未配置</span>
            </div>
            <div class="symbol-card-foot">
              <span>止损 lot {{ row.active_stoploss_buy_lot_count || 0 }}</span>
              <span>{{ row.last_trigger_label }} · {{ row.last_trigger_time }}</span>
            </div>
          </button>
        </div>
      </aside>

      <main class="tpsl-main">
        <section v-if="detail" class="hero-card">
          <div>
            <p class="eyebrow">Detail</p>
            <h2>{{ detail.name || detail.symbol }} <small>{{ detail.symbol }}</small></h2>
            <p>当前持仓 {{ detail.position.quantity || 0 }} 股，止盈层 {{ detail.takeprofitTierCount }} 个，open buy lot {{ detail.buyLots.length }} 个。</p>
          </div>
          <div class="hero-meta">
            <span>历史 {{ detail.historyRows.length }} 条</span>
            <el-button :loading="loadingDetail" @click="reloadCurrentSymbol">刷新详情</el-button>
          </div>
        </section>

        <section v-if="detail" class="panel-card">
          <div class="panel-head">
            <div>
              <h3>标的止盈层次</h3>
              <p>编辑价位，或直接按层级启停并 rearm。</p>
            </div>
            <div class="panel-actions">
              <el-button @click="addTier">新增层级</el-button>
              <el-button type="warning" :disabled="!selectedSymbol" @click="handleRearm">Rearm</el-button>
              <el-button type="primary" :loading="savingTakeprofit" :disabled="!selectedSymbol" @click="handleSaveTakeprofit">保存层级</el-button>
            </div>
          </div>

          <el-empty v-if="takeprofitDrafts.length === 0" description="还没有止盈层次，先新增一层。" />
          <el-table v-else :data="takeprofitDrafts" stripe>
            <el-table-column label="Level" width="90">
              <template #default="{ row }">
                <strong>L{{ row.level }}</strong>
              </template>
            </el-table-column>
            <el-table-column label="Price" min-width="160">
              <template #default="{ row }">
                <el-input-number v-model="row.price" :min="0" :step="0.01" :precision="2" controls-position="right" />
              </template>
            </el-table-column>
            <el-table-column label="Manual" width="140">
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
            <el-table-column label="Armed" width="120">
              <template #default="{ row }">
                <el-tag :type="armedLevels[String(row.level)] ? 'success' : 'info'">
                  {{ armedLevels[String(row.level)] ? '已布防' : '未布防' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button text type="danger" @click="removeTier(row.level)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>

        <section v-if="detail" class="panel-card">
          <div class="panel-head">
            <div>
              <h3>按买入订单止损</h3>
              <p>只展示 open buy lot。每行可单独设置 stop_price 和 enabled。</p>
            </div>
          </div>

          <el-table :data="detail.buyLots" stripe>
            <el-table-column prop="buy_lot_id" label="Buy Lot" min-width="180" />
            <el-table-column label="买入时间" min-width="150">
              <template #default="{ row }">
                {{ row.date || '-' }} {{ row.time || '' }}
              </template>
            </el-table-column>
            <el-table-column label="买入价" width="100">
              <template #default="{ row }">
                {{ row.buy_price_real }}
              </template>
            </el-table-column>
            <el-table-column label="原始/剩余" width="120">
              <template #default="{ row }">
                {{ row.original_quantity }} / {{ row.remaining_quantity }}
              </template>
            </el-table-column>
            <el-table-column label="Stop Price" min-width="180">
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
            <el-table-column label="Enabled" width="120">
              <template #default="{ row }">
                <el-switch
                  v-model="stoplossDrafts[row.buy_lot_id].enabled"
                  inline-prompt
                  active-text="开"
                  inactive-text="关"
                />
              </template>
            </el-table-column>
            <el-table-column label="卖出摘要" min-width="140">
              <template #default="{ row }">
                {{ row.sellHistoryLabel }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button type="primary" text :loading="savingStoploss[row.buy_lot_id]" @click="handleSaveStoploss(row.buy_lot_id)">
                  保存
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>

        <section v-if="detail" class="panel-card">
          <div class="panel-head">
            <div>
              <h3>统一触发历史</h3>
              <p>同页查看 takeprofit / stoploss 触发，以及后续 request、order、trade。</p>
            </div>
            <div class="panel-actions">
              <el-select v-model="historyKind" class="history-filter" @change="loadHistory">
                <el-option label="全部" value="all" />
                <el-option label="止盈" value="takeprofit" />
                <el-option label="止损" value="stoploss" />
              </el-select>
              <el-button :loading="loadingHistory" @click="loadHistory">刷新历史</el-button>
            </div>
          </div>

          <el-empty v-if="detail.historyRows.length === 0" description="当前没有历史事件。" />
          <div v-else class="history-list">
            <article v-for="row in detail.historyRows" :key="row.event_id || row.batch_id" class="history-card">
              <div class="history-card-head">
                <div>
                  <strong>{{ row.kind || row.event_type }}</strong>
                  <span>{{ row.created_at || '-' }}</span>
                </div>
                <el-tag>{{ row.batch_id || '无 batch' }}</el-tag>
              </div>
              <div class="history-grid">
                <div>
                  <span>层级/止损价</span>
                  <strong>{{ row.triggerLabel }}</strong>
                </div>
                <div>
                  <span>触发价</span>
                  <strong>{{ row.triggerPriceLabel }}</strong>
                </div>
                <div>
                  <span>影响 buy lot</span>
                  <strong>{{ row.buy_lot_label }}</strong>
                </div>
                <div>
                  <span>后续结果</span>
                  <strong>{{ row.downstreamLabel }}</strong>
                </div>
              </div>
              <div class="history-chip-row">
                <span v-for="request in row.order_requests || []" :key="request.request_id">request {{ request.request_id }}</span>
                <span v-for="order in row.orders || []" :key="order.internal_order_id">order {{ order.internal_order_id }} · {{ order.state }}</span>
                <span v-for="trade in row.trades || []" :key="trade.trade_fact_id">trade {{ trade.trade_fact_id }} · {{ trade.quantity }}@{{ trade.price }}</span>
              </div>
            </article>
          </div>
        </section>

        <section v-else class="empty-main">
          <el-empty description="左侧先选择一个标的。" />
        </section>
      </main>
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
.tpsl-page {
  --bg: #f5efe6;
  --paper: #fffdf8;
  --ink: #203246;
  --muted: #6d7d8d;
  --line: #d8d3c8;
  --accent: #b35c2e;
  --accent-soft: #f0ddcf;
  --ok: #2e7d5a;
  --shadow: 0 18px 40px rgba(36, 48, 60, 0.08);
  min-height: 100vh;
  background:
    radial-gradient(circle at top left, rgba(255, 218, 176, 0.55), transparent 28%),
    linear-gradient(180deg, #f9f4eb 0%, #f1ebe1 100%);
}

.tpsl-shell {
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr);
  gap: 18px;
  padding: 18px;
}

.tpsl-sidebar,
.panel-card,
.hero-card,
.empty-main {
  background: var(--paper);
  border: 1px solid rgba(151, 128, 108, 0.18);
  border-radius: 22px;
  box-shadow: var(--shadow);
}

.tpsl-sidebar {
  padding: 18px;
}

.sidebar-head,
.panel-head,
.hero-card,
.history-grid,
.symbol-card-head,
.symbol-card-foot {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.sidebar-head h1,
.panel-head h3,
.hero-card h2 {
  margin: 4px 0;
  color: var(--ink);
}

.sidebar-copy,
.panel-head p,
.hero-card p,
.symbol-card span,
.symbol-card-foot,
.history-card span {
  color: var(--muted);
}

.eyebrow {
  margin: 0;
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--accent);
}

.page-alert {
  margin: 16px 0;
}

.overview-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.overview-metrics article {
  padding: 14px;
  border-radius: 16px;
  background: linear-gradient(180deg, #fff8ee 0%, #f6ecde 100%);
}

.overview-metrics span {
  display: block;
  color: var(--muted);
  font-size: 12px;
}

.overview-metrics strong {
  display: block;
  margin-top: 8px;
  font-size: 22px;
  color: var(--ink);
}

.symbol-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.symbol-card {
  width: 100%;
  padding: 14px;
  text-align: left;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: #fff;
  transition: transform 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
}

.symbol-card:hover,
.symbol-card.active {
  border-color: rgba(179, 92, 46, 0.6);
  box-shadow: 0 12px 26px rgba(179, 92, 46, 0.12);
  transform: translateY(-1px);
}

.symbol-card strong {
  display: block;
  color: var(--ink);
}

.position-pill,
.symbol-card-badges span,
.history-chip-row span {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 4px 10px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12px;
}

.symbol-card-badges,
.history-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 12px 0;
}

.tpsl-main {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.hero-card,
.panel-card,
.empty-main {
  padding: 20px;
}

.hero-card h2 small {
  color: var(--muted);
  font-size: 16px;
}

.hero-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 10px;
}

.panel-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.history-filter {
  width: 120px;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.history-card {
  padding: 16px;
  border-radius: 18px;
  border: 1px solid var(--line);
  background: linear-gradient(180deg, #fffdf9 0%, #f8f2ea 100%);
}

.history-card-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.history-card-head strong,
.history-grid strong {
  display: block;
  color: var(--ink);
}

.history-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}

.empty-main {
  min-height: 320px;
  display: grid;
  place-items: center;
}

@media (max-width: 1080px) {
  .tpsl-shell {
    grid-template-columns: 1fr;
  }

  .sidebar-head,
  .panel-head,
  .hero-card,
  .history-card-head,
  .history-grid {
    flex-direction: column;
    grid-template-columns: 1fr;
  }

  .overview-metrics {
    grid-template-columns: 1fr;
  }
}
</style>
