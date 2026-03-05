<template>
  <div >
      <el-divider content-position="center">必选股票池</el-divider>
      <el-table
        v-loading="isLoading"
        :data="stockList"
        size="small"
        :stripe="true"
        :border="true"
      >
        <el-table-column prop="symbol" label="代码" width="100">
          <template #default="scope">
            <el-link
              type="primary"
              :underline="true"
              @click="jumpToKline(scope.row.symbol)"
            >
              {{ scope.row.symbol }}
            </el-link>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名字"> </el-table-column>
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
        <el-table-column prop="stop_loss_price" label="止损价格"> </el-table-column>
        <el-table-column prop="lot_amount" label="单次买入金额"> </el-table-column>
        <el-table-column prop="created_at" label="时间"> </el-table-column>
        <el-table-column label="操作">
            <template #default="scope">
              <el-button @click="deleteFromStockMustPoolsByCode(scope.row)">删除</el-button>
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
          :page-sizes="[20, 50, 100]"
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
          class="mt-5"
        />
      </el-row>
  </div>
</template>

<script>
/* eslint-disable */
import { stockApi } from '@/api/stockApi'
import CommonTool from '@/tool/CommonTool'
import _ from 'lodash'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { reactive } from 'vue'

export default {
  name: 'StockMustPools',
  data () {
    return {}
  },
  setup () {
    const listQuery = reactive({
      size: 10,
      total: 0,
      current: 1
    })
    const { isLoading, data: stockList } = useQuery({
      queryKey: ['stockMustPoolList'],
      queryFn: async () => {
        const stockList = await stockApi.getStockMustPoolsList({
          page: 1,
          size: 1000
        })
        listQuery.total = _.size(stockList)
        const start = (listQuery.current - 1) * listQuery.size
        const end = start + listQuery.size
        return _.slice(stockList, start, end)
      },
      refetchInterval: 600000,
      staleTime: 5000
    })
    const queryClient = useQueryClient()
    return { isLoading, stockList, listQuery, queryClient }
  },
  methods: {
    refreshStockMustPoolList () {
      this.listQuery.current = 1
      this.queryClient.invalidateQueries({ queryKey: ['stockMustPoolList'] })
    },
    handleSizeChange (currentSize) {
      this.listQuery.size = currentSize
      this.queryClient.invalidateQueries({ queryKey: ['stockMustPoolList'] })
    },
    handlePageChange (currentPage) {
      this.listQuery.current = currentPage
      this.queryClient.invalidateQueries({ queryKey: ['stockMustPoolList'] })
    },
    jumpToKline (symbol) {
      // 总控页面不关闭，开启新页面
      const routeUrl = this.$router.resolve({
        path: '/kline-big',
        query: {
          symbol,
          period: '1m',
          endDate: CommonTool.dateFormat('yyyy-MM-dd')
        }
      })
      window.open(routeUrl.href, '_blank')
    },
    deleteFromStockMustPoolsByCode(stock){
      stockApi.deleteFromStockMustPoolsByCode(stock.code)
      .then(res => {
        if (res.code === '0') {
          this.$message({
            message: '删除成功',
            type: 'success'
          })
          this.listQuery.current = 1
          this.queryClient.invalidateQueries({ queryKey: ['stockMustPoolList'] })
        }else{
          this.$message({
            message: '删除失败',
            type: 'error'
          })
        }
      })
      .catch(err => {
        this.$message({
          message: '删除失败',
          type: 'error'
        })
      })
    }
  }
}
</script>
<style lang="stylus" scoped>
.stock-pool-main :deep() {
  .el-table .el-table__cell {
    vertical-align: top
  }
}
</style>
