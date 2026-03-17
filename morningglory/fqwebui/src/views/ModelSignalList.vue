<template>
  <div style="padding: 4px;" class="model-signal-list-main">
    <el-divider content-position="center">{{ title }}</el-divider>
    <el-table
      v-loading="isLoading"
      :data="signalList"
      size="small"
      fit
      :stripe="true"
      :border="true"
    >
      <el-table-column prop="datetime" label="信号时间" width="140" />
      <el-table-column prop="created_at" label="入库时间" width="160" />
      <el-table-column label="标的" min-width="140">
        <template #default="{ row }">
          <div>{{ row.name || '--' }}</div>
          <div>{{ row.code || '--' }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="period" label="周期" width="80" />
      <el-table-column prop="model" label="模型" width="90" />
      <el-table-column label="价格" width="160">
        <template #default="{ row }">
          <div class="price-cell-line">触发价: {{ formatPrice(row.close) }}</div>
          <div class="price-cell-line">止损价: {{ formatPrice(row.stop_loss_price) }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="source" label="来源" min-width="120" />
    </el-table>
    <el-row>
      <el-pagination
        background
        layout="total,sizes,prev,pager,next"
        v-model:current-page="listQuery.current"
        :page-size="listQuery.size"
        :total="listQuery.total"
        :page-sizes="[10, 50, 100]"
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
        class="mt-5"
      />
    </el-row>
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
      size: 10,
      total: 0,
      current: 1
    })
    const { isLoading, data: signalList } = useQuery({
      queryKey: ['stockModelSignalList'],
      queryFn: async () => {
        const signalList = await stockApi.getStockModelSignalList({
          page: 1,
          size: 1000
        })
        listQuery.total = _.size(signalList)
        const start = (listQuery.current - 1) * listQuery.size
        const end = start + listQuery.size
        return _.slice(signalList, start, end)
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
      this.queryClient.invalidateQueries({ queryKey: ['stockModelSignalList'] })
    },
    handlePageChange (currentPage) {
      this.listQuery.current = currentPage
      this.queryClient.invalidateQueries({ queryKey: ['stockModelSignalList'] })
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
    }
  }
}
</script>

<style lang="stylus" scoped>
.model-signal-list-main :deep() {
  .el-table .el-table__cell {
    vertical-align: top
  }
}

.price-cell-line {
  white-space: nowrap
}
</style>
