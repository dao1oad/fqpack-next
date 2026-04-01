<template>
  <WorkbenchPage class="order-page">
    <MyHeader />

    <div class="workbench-body order-body">
      <WorkbenchToolbar class="order-toolbar">
        <div class="workbench-toolbar__header">
          <div class="workbench-title-group">
            <div class="workbench-page-title">订单管理</div>
            <div class="workbench-page-meta">
              <span>订单账本、请求上下文、状态流转、成交回报</span>
              <span>/</span>
              <span>当前列表 {{ total }} 条</span>
              <template v-if="selectedOrderId">
                <span>/</span>
                <span>选中 <span class="workbench-code">{{ selectedOrderId }}</span></span>
              </template>
            </div>
          </div>

        <div class="workbench-toolbar__actions">
          <el-button @click="resetFilters">重置</el-button>
          <el-button @click="toggleAdvancedFilters">高级筛选</el-button>
          <el-button type="primary" :loading="loadingOrders || loadingStats" @click="applyFilters">
            刷新
          </el-button>
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

        <div v-if="showAdvancedFilters" class="filter-grid">
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
          <el-input v-model="filters.date_from" placeholder="date_from，ISO 时间或 YYYY-MM-DD（按北京时间）" clearable />
          <el-input v-model="filters.date_to" placeholder="date_to，ISO 时间或 YYYY-MM-DD（按北京时间）" clearable />
        </div>

        <div class="filter-foot">
          <div class="workbench-inline-tags">
            <el-switch
              v-model="filters.missing_broker_only"
              inline-prompt
              active-text="缺 broker 单号"
              inactive-text="全部订单"
            />
            <span class="workbench-muted">时间筛选支持 `2026-03-13` 或 ISO 时间。</span>
          </div>

          <div class="workbench-summary-row order-filter-chips">
            <StatusChip
              v-for="chip in activeFilterChips"
              :key="chip"
              variant="muted"
            >
              {{ chip }}
            </StatusChip>
            <StatusChip
              v-if="activeFilterChips.length === 0"
              variant="muted"
            >
              当前无额外筛选
            </StatusChip>
          </div>
        </div>
      </WorkbenchToolbar>

      <WorkbenchPanel class="order-stats-panel" v-loading="loadingStats">
        <div class="workbench-panel__header">
          <div class="workbench-title-group">
            <div class="workbench-panel__title">订单摘要</div>
            <p class="workbench-panel__desc">保留原有统计口径，用摘要条承载更多信息。</p>
          </div>
        </div>

        <div class="workbench-summary-row">
          <StatusChip>
            总订单 <strong>{{ stats.total }}</strong>
          </StatusChip>
          <StatusChip variant="warning">
            缺 broker 单号 <strong>{{ stats.missing_broker_order_count }}</strong>
          </StatusChip>
          <StatusChip variant="success">
            已成交 / 部分成交 <strong>{{ stats.filled_count }} / {{ stats.partial_filled_count }}</strong>
          </StatusChip>
          <StatusChip variant="muted">
            撤单 <strong>{{ stats.canceled_count }}</strong>
          </StatusChip>
          <StatusChip variant="muted">
            失败 <strong>{{ stats.failed_count }}</strong>
          </StatusChip>
          <StatusChip variant="muted">
            最近更新时间 <strong>{{ stats.latest_updated_at }}</strong>
          </StatusChip>
          <StatusChip
            v-for="item in stats.sideCards"
            :key="item.key"
            variant="muted"
          >
            {{ item.label }} <strong>{{ item.value }}</strong>
          </StatusChip>
          <StatusChip
            v-for="item in stats.stateCards"
            :key="item.key"
            variant="muted"
          >
            {{ item.label }} <strong>{{ item.value }}</strong>
          </StatusChip>
        </div>
      </WorkbenchPanel>

      <div class="order-main-grid">
        <WorkbenchLedgerPanel class="order-list-panel" v-loading="loadingOrders">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">订单列表</div>
              <p class="workbench-panel__desc">默认展示最近订单；点 symbol 可直接切到该标的历史。</p>
            </div>
            <div class="workbench-panel__meta">
              <span>共 {{ total }} 条</span>
              <span>/</span>
              <span>页 {{ page }}</span>
              <span>/</span>
              <span>每页 {{ size }}</span>
            </div>
          </div>

          <div class="workbench-table-wrap">
            <el-empty v-if="rows.length === 0" description="当前筛选下没有订单。" />
            <template v-else>
              <el-table
                :data="rows"
                stripe
                height="100%"
                :row-class-name="tableRowClassName"
                @row-click="handleRowClick"
              >
                <el-table-column label="标的代码" min-width="136">
                  <template #default="{ row }">
                    <div class="order-symbol-cell">
                      <el-button text type="primary" @click.stop="focusSymbol(row.symbol)">
                        {{ row.symbol || '-' }}
                      </el-button>
                      <span class="order-symbol-name">{{ row.name || '-' }}</span>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="更新时间" min-width="176">
                  <template #default="{ row }">
                    {{ formatOrderTimestamp(row.updated_at || row.created_at) }}
                  </template>
                </el-table-column>
                <el-table-column prop="side" label="方向" width="86" />
                <el-table-column prop="state" label="订单状态" width="160" />
                <el-table-column prop="strategy_name" label="策略" min-width="132" />
                <el-table-column prop="source" label="来源" width="148" />
                <el-table-column label="委托价 / 委托量" min-width="132">
                  <template #default="{ row }">
                    {{ formatOrderPrice(row.price) }} / {{ formatOrderQuantity(row.quantity) }}
                  </template>
                </el-table-column>
                <el-table-column label="成交量 / 成交均价" min-width="118">
                  <template #default="{ row }">
                    {{ formatOrderQuantity(row.filled_quantity) }} / {{ formatOrderPrice(row.avg_filled_price) }}
                  </template>
                </el-table-column>
                <el-table-column prop="broker_order_id" label="券商单号" min-width="132" />
              </el-table>
            </template>
          </div>

          <div v-if="rows.length" class="pagination-row">
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
        </WorkbenchLedgerPanel>

        <WorkbenchDetailPanel class="order-detail-panel" v-loading="loadingDetail">
          <template v-if="detail">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">{{ detail.headerTitle }}</div>
                <div class="workbench-panel__meta">
                  <span>{{ detail.requestSummary }}</span>
                  <span>/</span>
                  <span>{{ detail.tradeSummary }}</span>
                </div>
              </div>

              <div class="workbench-summary-row">
                <StatusChip variant="muted">
                  {{ detail.order.side || '-' }}
                </StatusChip>
                <StatusChip variant="muted">
                  {{ detail.order.state || '-' }}
                </StatusChip>
                <StatusChip variant="muted">
                  {{ detail.tradeSummary }}
                </StatusChip>
              </div>
            </div>

            <div class="workbench-summary-row order-identifier-row">
              <StatusChip
                v-for="item in detail.identifierRows"
                :key="item.key"
                variant="muted"
              >
                <span>{{ item.key }}</span>
                <strong>{{ item.value }}</strong>
              </StatusChip>
            </div>

            <div class="order-detail-grid">
              <article class="workbench-block order-detail-block">
                <div class="order-detail-block__head">订单主记录</div>
                <el-descriptions :column="1" border size="small">
                  <el-descriptions-item label="symbol">{{ detail.order.symbol || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="side">{{ detail.order.side || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="state">{{ detail.order.state || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="account_type">{{ detail.order.account_type || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="filled">{{ detail.order.filled_quantity ?? '-' }}</el-descriptions-item>
                  <el-descriptions-item label="avg_filled_price">{{ detail.order.avg_filled_price ?? '-' }}</el-descriptions-item>
                  <el-descriptions-item label="submitted_at">{{ formatOrderTimestamp(detail.order.submitted_at) }}</el-descriptions-item>
                  <el-descriptions-item label="updated_at">{{ formatOrderTimestamp(detail.order.updated_at) }}</el-descriptions-item>
                </el-descriptions>
              </article>

              <article class="workbench-block order-detail-block">
                <div class="order-detail-block__head">请求信息</div>
                <el-descriptions :column="1" border size="small">
                  <el-descriptions-item label="request_id">{{ detail.request.request_id || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="source">{{ detail.request.source || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="strategy_name">{{ detail.request.strategy_name || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="scope_type">{{ detail.request.scope_type || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="scope_ref_id">{{ detail.request.scope_ref_id || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="remark">{{ detail.request.remark || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="created_at">{{ formatOrderTimestamp(detail.request.created_at) }}</el-descriptions-item>
                </el-descriptions>
              </article>

              <article class="workbench-block order-detail-block">
                <div class="order-detail-block__head">状态流转</div>
                <el-empty v-if="detail.timelineRows.length === 0" description="暂无事件" />
                <el-timeline v-else class="order-timeline">
                  <el-timeline-item
                    v-for="item in detail.timelineRows"
                    :key="item.event_id || `${item.event_type}-${item.created_at}`"
                    :timestamp="formatOrderTimestamp(item.created_at)"
                    placement="top"
                  >
                    <strong>{{ item.event_type || '-' }}</strong>
                    <p>{{ item.state || '-' }}</p>
                  </el-timeline-item>
                </el-timeline>
              </article>

              <article class="workbench-block order-detail-block">
                <div class="order-detail-block__head">成交回报</div>
                <el-empty v-if="detail.tradeRows.length === 0" description="暂无成交" />
                <el-table v-else :data="detail.tradeRows" stripe size="small" height="100%">
                  <el-table-column prop="trade_fact_id" label="Trade Fact" min-width="140" />
                  <el-table-column prop="quantity" label="Qty" width="90" />
                  <el-table-column prop="price" label="Price" width="96">
                    <template #default="{ row }">
                      {{ formatOrderPrice(row.price) }}
                    </template>
                  </el-table-column>
                  <el-table-column label="Trade Time" min-width="168">
                    <template #default="{ row }">
                      {{ row.trade_time_label || formatOrderTimestamp(row.trade_time) }}
                    </template>
                  </el-table-column>
                  <el-table-column prop="source" label="Source" min-width="120" />
                </el-table>
              </article>
            </div>
          </template>

          <div v-else class="workbench-empty">先从左侧订单列表选择一笔订单。</div>
        </WorkbenchDetailPanel>
      </div>
    </div>
  </WorkbenchPage>
</template>

<script setup>
import { computed, onMounted, ref, toRefs } from 'vue'

import StatusChip from '../components/workbench/StatusChip.vue'
import WorkbenchDetailPanel from '../components/workbench/WorkbenchDetailPanel.vue'
import WorkbenchLedgerPanel from '../components/workbench/WorkbenchLedgerPanel.vue'
import WorkbenchPage from '../components/workbench/WorkbenchPage.vue'
import WorkbenchPanel from '../components/workbench/WorkbenchPanel.vue'
import WorkbenchToolbar from '../components/workbench/WorkbenchToolbar.vue'
import MyHeader from '@/views/MyHeader.vue'
import { orderManagementApi } from '@/api/orderManagementApi'
import {
  createOrderManagementActions,
  formatOrderPrice,
  formatOrderQuantity,
  formatOrderTimestamp,
} from '@/views/orderManagement.mjs'
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
const showAdvancedFilters = ref(false)

const toggleAdvancedFilters = () => {
  showAdvancedFilters.value = !showAdvancedFilters.value
}

const activeFilterChips = computed(() => {
  const chips = []
  const valueMap = [
    ['symbol', 'symbol'],
    ['side', '方向'],
    ['state', '状态'],
    ['source', 'source'],
    ['strategy_name', 'strategy'],
    ['account_type', '账户'],
    ['internal_order_id', 'internal'],
    ['request_id', 'request'],
    ['broker_order_id', 'broker'],
    ['time_field', '时间口径'],
    ['date_from', 'from'],
    ['date_to', 'to'],
  ]
  for (const [key, label] of valueMap) {
    const value = String(filters.value?.[key] ?? '').trim()
    if (!value) continue
    chips.push(`${label} ${value}`)
  }
  if (filters.value?.missing_broker_only) {
    chips.push('仅缺 broker 单号')
  }
  return chips
})

const handleRowClick = async (row) => {
  await selectOrder(
    row?.orderLookupId || row?.internal_order_id || row?.broker_order_id || row?.broker_order_key,
  )
}

const tableRowClassName = ({ row }) => {
  const rowLookupId = String(
    row?.orderLookupId || row?.internal_order_id || row?.broker_order_id || row?.broker_order_key || '',
  ).trim()
  return rowLookupId && rowLookupId === selectedOrderId.value ? 'order-row-active' : ''
}

onMounted(async () => {
  await refreshAll()
})
</script>

<style scoped>
.order-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.filter-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.filter-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.order-filter-chips {
  justify-content: flex-end;
}

.order-stats-panel {
  position: relative;
  z-index: 2;
  gap: 8px;
}

.order-main-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.18fr) minmax(400px, 0.92fr);
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  position: relative;
  z-index: 1;
}

.order-list-panel,
.order-detail-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.order-detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}

.order-detail-block {
  min-height: 0;
}

.order-detail-block__head {
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.order-symbol-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  min-width: 0;
}

.order-symbol-name {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  line-height: 1.3;
  color: #6b7280;
}

.order-timeline {
  margin-top: 2px;
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 2px;
}

:deep(.order-row-active td) {
  background: #ecf5ff !important;
}

@media (max-width: 1440px) {
  .filter-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .order-main-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .filter-grid,
  .order-detail-grid {
    grid-template-columns: 1fr;
  }
}
</style>
