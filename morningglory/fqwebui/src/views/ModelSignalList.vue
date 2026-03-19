<template>
  <div class="model-signal-list-table">
    <div class="model-signal-list-table__main">
      <el-table
        v-loading="isLoading"
        :data="signalList"
        size="small"
        border
        height="100%"
      >
        <el-table-column prop="datetime" label="信号时间" min-width="140">
          <template #default="{ row }">
            <span class="mono">{{ formatText(row.datetime) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="入库时间" min-width="140">
          <template #default="{ row }">
            <span class="mono">{{ formatText(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="标的代码" min-width="104">
          <template #default="{ row }">
            <span class="mono">{{ formatText(row.code) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="标的名称" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">
            <span>{{ formatText(row.name) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="价格" min-width="268">
          <template #default="{ row }">
            <span class="price-summary mono">{{ formatPriceSummary(row.close, row.stop_loss_price) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <div class="model-signal-list-table__pagination">
      <el-pagination
        background
        layout="total,sizes,prev,pager,next"
        v-model:current-page="listQuery.current"
        :page-size="listQuery.size"
        :total="listQuery.total"
        :page-sizes="[100, 200, 500]"
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
      />
    </div>
  </div>
</template>

<script>
import { stockApi } from '@/api/stockApi'
import _ from 'lodash'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { reactive } from 'vue'

export default {
  name: 'ModelSignalList',
  props: {
    title: {
      type: String,
      default: 'stock_pools模型信号'
    }
  },
  setup () {
    const listQuery = reactive({
      size: 100,
      total: 0,
      current: 1
    })
    const { isLoading, data: signalList } = useQuery({
      queryKey: ['stockModelSignalList'],
      queryFn: async () => {
        const rows = await stockApi.getStockModelSignalList({
          page: 1,
          size: 1000
        })
        listQuery.total = _.size(rows)
        const start = (listQuery.current - 1) * listQuery.size
        const end = start + listQuery.size
        return _.slice(rows, start, end)
      },
      refetchInterval: 30000,
      staleTime: 5000
    })
    const queryClient = useQueryClient()
    return { isLoading, signalList, listQuery, queryClient }
  },
  methods: {
    handleSizeChange (currentSize) {
      this.listQuery.size = currentSize
      this.listQuery.current = 1
      this.queryClient.invalidateQueries({ queryKey: ['stockModelSignalList'] })
    },
    handlePageChange (currentPage) {
      this.listQuery.current = currentPage
      this.queryClient.invalidateQueries({ queryKey: ['stockModelSignalList'] })
    },
    formatText (value) {
      const normalized = String(value ?? '').trim()
      return normalized || '--'
    },
    formatPrice (value) {
      if (value === null || value === undefined || value === '') {
        return '--'
      }
      const parsed = Number(value)
      if (!Number.isFinite(parsed)) {
        return '--'
      }
      return parsed.toFixed(3)
    },
    formatStopLossRate (price, stopLossPrice) {
      const firePrice = Number(price)
      const stopPrice = Number(stopLossPrice)
      if (!Number.isFinite(firePrice) || !Number.isFinite(stopPrice) || firePrice === 0) {
        return '--'
      }
      return `${(((stopPrice - firePrice) / firePrice) * 100).toFixed(3)}%`
    },
    formatPriceSummary (price, stopLossPrice) {
      return `触发价 ${this.formatPrice(price)} / 止损价 ${this.formatPrice(stopLossPrice)} / 止损% ${this.formatStopLossRate(price, stopLossPrice)}`
    }
  }
}
</script>

<style lang="stylus" scoped>
.model-signal-list-table
  display flex
  flex 1 1 auto
  flex-direction column
  min-height 0
  overflow hidden

.model-signal-list-table__main
  flex 1 1 auto
  min-height 0
  overflow hidden

.model-signal-list-table__pagination
  display flex
  justify-content flex-end
  padding-top 8px

.price-summary
  display inline-block
  white-space nowrap

.mono
  font-family Consolas, Monaco, 'Courier New', monospace

.model-signal-list-table :deep(.el-table)
  height 100%

.model-signal-list-table :deep(.el-table .el-table__cell)
  vertical-align top
</style>
