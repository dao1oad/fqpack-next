<template>
  <div class="order-page">
    <MyHeader />

    <div class="order-shell">
      <section class="filter-card">
        <div class="card-head">
          <div>
            <p class="eyebrow">Order Ledger</p>
            <h1>订单管理</h1>
            <p>统一查看订单账本、请求上下文、状态流转和成交回报。</p>
          </div>
          <div class="head-actions">
            <el-button @click="resetFilters">重置</el-button>
            <el-button type="primary" :loading="loadingOrders || loadingStats" @click="applyFilters">刷新</el-button>
          </div>
        </div>

        <el-alert
          v-if="pageError"
          class="page-alert"
          type="error"
          :title="pageError"
          :closable="false"
          show-icon
        />

        <div class="filter-grid">
          <el-input v-model="filters.symbol" placeholder="symbol，如 600000" clearable />
          <el-select v-model="filters.side" placeholder="方向" clearable>
            <el-option label="买入" value="buy" />
            <el-option label="卖出" value="sell" />
          </el-select>
          <el-select v-model="filters.state" placeholder="状态" clearable>
            <el-option label="ACCEPTED" value="ACCEPTED" />
            <el-option label="QUEUED" value="QUEUED" />
            <el-option label="SUBMITTED" value="SUBMITTED" />
            <el-option label="PARTIAL_FILLED" value="PARTIAL_FILLED" />
            <el-option label="FILLED" value="FILLED" />
            <el-option label="CANCELLED" value="CANCELLED" />
          </el-select>
          <el-input v-model="filters.source" placeholder="source / source_type" clearable />
          <el-input v-model="filters.strategy_name" placeholder="strategy_name" clearable />
          <el-select v-model="filters.account_type" placeholder="账户类型" clearable>
            <el-option label="STOCK" value="STOCK" />
            <el-option label="CREDIT" value="CREDIT" />
          </el-select>
          <el-input v-model="filters.internal_order_id" placeholder="internal_order_id" clearable />
          <el-input v-model="filters.request_id" placeholder="request_id" clearable />
          <el-input v-model="filters.broker_order_id" placeholder="broker_order_id" clearable />
          <el-select v-model="filters.time_field" placeholder="时间口径">
            <el-option label="更新时间" value="updated_at" />
            <el-option label="创建时间" value="created_at" />
            <el-option label="提交时间" value="submitted_at" />
          </el-select>
          <el-input v-model="filters.date_from" placeholder="date_from，ISO 时间或 YYYY-MM-DD" clearable />
          <el-input v-model="filters.date_to" placeholder="date_to，ISO 时间或 YYYY-MM-DD" clearable />
        </div>

        <div class="filter-foot">
          <el-switch
            v-model="filters.missing_broker_only"
            inline-prompt
            active-text="缺 broker 单号"
            inactive-text="全部订单"
          />
          <span class="filter-hint">时间筛选支持 `2026-03-13` 或 ISO 时间。</span>
        </div>
      </section>

      <section class="stats-grid" v-loading="loadingStats">
        <article class="stat-card">
          <span>总订单数</span>
          <strong>{{ stats.total }}</strong>
          <small>最近更新时间 {{ stats.latest_updated_at }}</small>
        </article>
        <article class="stat-card">
          <span>缺 broker 单号</span>
          <strong>{{ stats.missing_broker_order_count }}</strong>
          <small>排查 queued / submit 异常优先看这里</small>
        </article>
        <article class="stat-card">
          <span>已成交 / 部分成交</span>
          <strong>{{ stats.filled_count }} / {{ stats.partial_filled_count }}</strong>
          <small>撤单 {{ stats.canceled_count }}，失败 {{ stats.failed_count }}</small>
        </article>
        <article class="stat-card stat-card--wide">
          <span>买卖分布</span>
          <div class="chip-row">
            <span v-for="item in stats.sideCards" :key="item.key">{{ item.label }} {{ item.value }}</span>
            <span v-if="stats.sideCards.length === 0">暂无</span>
          </div>
          <div class="chip-row">
            <span v-for="item in stats.stateCards" :key="item.key">{{ item.label }} {{ item.value }}</span>
            <span v-if="stats.stateCards.length === 0">暂无状态分布</span>
          </div>
        </article>
      </section>

      <div class="main-grid">
        <section class="table-card" v-loading="loadingOrders">
          <div class="card-head card-head--compact">
            <div>
              <h2>订单列表</h2>
              <p>默认展示最近订单；点 symbol 可直接切到该标的历史。</p>
            </div>
            <span class="muted">共 {{ total }} 条</span>
          </div>

          <el-empty v-if="rows.length === 0" description="当前筛选下没有订单。" />
          <template v-else>
            <el-table
              :data="rows"
              stripe
              height="520"
              :row-class-name="tableRowClassName"
              @row-click="handleRowClick"
            >
              <el-table-column label="Symbol" min-width="120">
                <template #default="{ row }">
                  <el-button text type="primary" @click.stop="focusSymbol(row.symbol)">
                    {{ row.symbol || '-' }}
                  </el-button>
                </template>
              </el-table-column>
              <el-table-column prop="side" label="Side" width="90" />
              <el-table-column prop="state" label="State" width="140" />
              <el-table-column prop="strategy_name" label="Strategy" min-width="140" />
              <el-table-column prop="source" label="Source" width="120" />
              <el-table-column label="Price / Qty" min-width="140">
                <template #default="{ row }">
                  {{ row.price ?? '-' }} / {{ row.quantity ?? '-' }}
                </template>
              </el-table-column>
              <el-table-column label="Filled" min-width="120">
                <template #default="{ row }">
                  {{ row.filled_quantity }} / {{ row.avg_filled_price ?? '-' }}
                </template>
              </el-table-column>
              <el-table-column prop="internal_order_id" label="Internal Order" min-width="170" />
              <el-table-column prop="request_id" label="Request" min-width="160" />
              <el-table-column prop="broker_order_id" label="Broker" min-width="140" />
              <el-table-column label="Updated" min-width="180">
                <template #default="{ row }">
                  {{ row.updated_at || row.created_at || '-' }}
                </template>
              </el-table-column>
            </el-table>

            <div class="pagination-row">
              <el-pagination
                background
                layout="total, sizes, prev, pager, next"
                :total="total"
                :current-page="page"
                :page-size="size"
                :page-sizes="[10, 20, 50, 100]"
                @current-change="changePage"
                @size-change="changeSize"
              />
            </div>
          </template>
        </section>

        <section class="detail-card" v-loading="loadingDetail">
          <template v-if="detail">
            <div class="card-head">
              <div>
                <p class="eyebrow">Order Detail</p>
                <h2>{{ detail.headerTitle }}</h2>
                <p>{{ detail.requestSummary }}</p>
              </div>
              <div class="chip-row">
                <span>{{ detail.order.side || '-' }}</span>
                <span>{{ detail.order.state || '-' }}</span>
                <span>{{ detail.tradeSummary }}</span>
              </div>
            </div>

            <div class="identifier-grid">
              <article v-for="item in detail.identifierRows" :key="item.key" class="identifier-card">
                <span>{{ item.key }}</span>
                <strong>{{ item.value }}</strong>
              </article>
            </div>

            <div class="info-grid">
              <article class="info-card">
                <h3>订单主记录</h3>
                <el-descriptions :column="1" border size="small">
                  <el-descriptions-item label="symbol">{{ detail.order.symbol || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="side">{{ detail.order.side || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="state">{{ detail.order.state || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="account_type">{{ detail.order.account_type || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="filled">{{ detail.order.filled_quantity ?? '-' }}</el-descriptions-item>
                  <el-descriptions-item label="avg_filled_price">{{ detail.order.avg_filled_price ?? '-' }}</el-descriptions-item>
                  <el-descriptions-item label="submitted_at">{{ detail.order.submitted_at || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="updated_at">{{ detail.order.updated_at || '-' }}</el-descriptions-item>
                </el-descriptions>
              </article>

              <article class="info-card">
                <h3>请求信息</h3>
                <el-descriptions :column="1" border size="small">
                  <el-descriptions-item label="request_id">{{ detail.request.request_id || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="source">{{ detail.request.source || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="strategy_name">{{ detail.request.strategy_name || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="scope_type">{{ detail.request.scope_type || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="scope_ref_id">{{ detail.request.scope_ref_id || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="remark">{{ detail.request.remark || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="created_at">{{ detail.request.created_at || '-' }}</el-descriptions-item>
                </el-descriptions>
              </article>
            </div>

            <div class="info-grid">
              <article class="info-card">
                <h3>状态流转</h3>
                <el-empty v-if="detail.timelineRows.length === 0" description="暂无事件" />
                <el-timeline v-else>
                  <el-timeline-item
                    v-for="item in detail.timelineRows"
                    :key="item.event_id || `${item.event_type}-${item.created_at}`"
                    :timestamp="item.created_at || '-'"
                    placement="top"
                  >
                    <strong>{{ item.event_type || '-' }}</strong>
                    <p>{{ item.state || '-' }}</p>
                  </el-timeline-item>
                </el-timeline>
              </article>

              <article class="info-card">
                <h3>成交回报</h3>
                <el-empty v-if="detail.tradeRows.length === 0" description="暂无成交" />
                <el-table v-else :data="detail.tradeRows" stripe size="small">
                  <el-table-column prop="trade_fact_id" label="Trade Fact" min-width="140" />
                  <el-table-column prop="quantity" label="Qty" width="90" />
                  <el-table-column prop="price" label="Price" width="90" />
                  <el-table-column prop="trade_time" label="Trade Time" min-width="140" />
                  <el-table-column prop="source" label="Source" min-width="120" />
                </el-table>
              </article>
            </div>
          </template>
          <el-empty v-else description="先从左侧订单列表选择一笔订单。" />
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, toRefs } from 'vue'

import MyHeader from '@/views/MyHeader.vue'
import { orderManagementApi } from '@/api/orderManagementApi'
import { createOrderManagementActions } from '@/views/orderManagement.mjs'
import { createOrderManagementPageController } from '@/views/orderManagementPage.mjs'

const actions = createOrderManagementActions(orderManagementApi)
const {
  state,
  refreshAll,
  applyFilters,
  resetFilters,
  selectOrder,
  focusSymbol,
  changePage,
  changeSize,
} = createOrderManagementPageController({
  actions,
})

const {
  loadingOrders,
  loadingStats,
  loadingDetail,
  pageError,
  filters,
  rows,
  stats,
  detail,
  selectedOrderId,
  page,
  size,
  total,
} = toRefs(state)

const handleRowClick = async (row) => {
  await selectOrder(row?.internal_order_id)
}

const tableRowClassName = ({ row }) => {
  return row?.internal_order_id === selectedOrderId.value ? 'order-row-active' : ''
}

onMounted(async () => {
  await refreshAll()
})
</script>

<style scoped>
.order-page {
  --bg: #eef3f0;
  --paper: #fbfcfa;
  --line: #dbe5de;
  --ink: #18322a;
  --muted: #5f786f;
  --accent: #1f7a5d;
  --accent-soft: #dff3ea;
  min-height: 100vh;
  background:
    radial-gradient(circle at top right, rgba(31, 122, 93, 0.12), transparent 28%),
    linear-gradient(180deg, #f4f8f5 0%, #e8efea 100%);
}

.order-shell {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 18px;
}

.filter-card,
.table-card,
.detail-card,
.stat-card,
.identifier-card,
.info-card {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 22px;
  box-shadow: 0 18px 42px rgba(28, 52, 44, 0.08);
}

.filter-card,
.table-card,
.detail-card {
  padding: 20px;
}

.card-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.card-head--compact {
  margin-bottom: 14px;
}

.card-head h1,
.card-head h2,
.info-card h3 {
  margin: 4px 0;
  color: var(--ink);
}

.card-head p,
.muted,
.filter-hint,
.identifier-card span,
.stat-card span,
.stat-card small {
  color: var(--muted);
}

.eyebrow {
  margin: 0;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-size: 12px;
  color: var(--accent);
}

.head-actions,
.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.chip-row span {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12px;
}

.page-alert {
  margin: 16px 0;
}

.filter-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
}

.filter-foot {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  margin-top: 14px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.stat-card {
  padding: 18px;
}

.stat-card strong {
  display: block;
  margin: 8px 0;
  font-size: 28px;
  color: var(--ink);
}

.stat-card--wide {
  grid-column: span 2;
}

.main-grid,
.info-grid,
.identifier-grid {
  display: grid;
  gap: 18px;
}

.main-grid {
  grid-template-columns: minmax(0, 1.15fr) minmax(360px, 0.85fr);
}

.identifier-grid {
  grid-template-columns: repeat(5, minmax(0, 1fr));
  margin: 18px 0;
}

.identifier-card {
  padding: 14px;
}

.identifier-card strong {
  display: block;
  margin-top: 8px;
  color: var(--ink);
  word-break: break-word;
}

.info-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-top: 18px;
}

.info-card {
  padding: 16px;
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

:deep(.order-row-active td) {
  background: #eff8f3 !important;
}

@media (max-width: 1180px) {
  .filter-grid,
  .stats-grid,
  .main-grid,
  .identifier-grid,
  .info-grid {
    grid-template-columns: 1fr;
  }

  .stat-card--wide {
    grid-column: auto;
  }

  .card-head,
  .filter-foot {
    flex-direction: column;
  }
}
</style>
