<template>
  <div style="padding: 4px;" class="signal-list-main">
    <el-divider content-position="center">{{ title }}</el-divider>
    <el-table
      v-loading="isLoading"
      :data="signalList"
      size="small"
      fit
      :stripe="true"
      :border="true"
    >
      <el-table-column label="品种" width="120">
        <template #default="scope">
          <div>
            <el-link
              type="primary"
              :underline="false"
              @click="jumpToKline(scope.row.symbol, scope.row.period)"
            >
              {{ scope.row.symbol }}
            </el-link>
          </div>
          <div>
            <el-link
              type="primary"
              :underline="false"
              @click="jumpToKline(scope.row.symbol, scope.row.period)"
            >
              {{ scope.row.name }}
            </el-link>
          </div>
          <div>
            <span>{{ scope.row.fire_time }}</span>
          </div>
          <div>
            <span>{{ scope.row.period }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column width="50" label="买/卖">
        <template #default="scope">
          <span>{{ scope.row.position === 'BUY_LONG' ? '买' : '卖' }}</span>
        </template>
      </el-table-column>
      <el-table-column width="120" label="价格">
        <template #default="scope">
          <div>
            <span>触发价: {{ scope.row.price }}</span>
          </div>
          <div>
            <span>止损价: {{ scope.row.stop_lose_price }}</span>
          </div>
          <div>
            <span nowrap
              >止损%:
              {{
                Math.round(
                  ((scope.row.stop_lose_price - scope.row.price) /
                    scope.row.price) *
                    10000
                ) / 100
              }}%</span
            >
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="remark" label="备注"> </el-table-column>
      <el-table-column prop="category" label="分类">
        <template #default="scope">
          <template v-if="Array.isArray(scope.row.category)">
            <span v-for="(cat, index) in scope.row.category" :key="index">
              {{ cat }}{{ index < scope.row.category.length - 1 ? '，' : '' }}
            </span>
          </template>
          <template v-else>
            {{ scope.row.category }}
          </template>
        </template>
      </el-table-column>
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
import commonTool from '@/tool/CommonTool'
import _ from 'lodash'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { reactive } from 'vue'

export default {
  name: 'SignalList',
  props: {
    title: {
      type: String,
      default: '候选股信号'
    },
    category: {
      type: String,
      default: 'candidates'
    }
  },
  data () {
    return {}
  },
  setup (props) {
    const listQuery = reactive({
      size: 10,
      total: 0,
      current: 1
    })
    const { isLoading, data: signalList } = useQuery({
      queryKey: ['stockSignalList', props.category],
      queryFn: async () => {
        const signalList = await stockApi.getStockSignalList({
          page: 1,
          size: 1000,
          category: props.category
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
    jumpToKline (symbol, period) {
      const routeUrl = this.$router.resolve({
        path: '/kline-big',
        query: {
          symbol,
          period,
          endDate: commonTool.dateFormat('yyyy-MM-dd')
        }
      })
      window.open(routeUrl.href, '_blank')
    },
    handleSizeChange (currentSize) {
      this.listQuery.size = currentSize
      this.queryClient.invalidateQueries({ queryKey: ['stockSignalList', this.category] })
    },
    handlePageChange (currentPage) {
      this.listQuery.current = currentPage
      this.queryClient.invalidateQueries({ queryKey: ['stockSignalList', this.category] })
    }
  }
}
</script>
<style lang="stylus" scoped>
.signal-list-main :deep() {
  .el-table .el-table__cell {
    vertical-align: top
  }
}
</style>
