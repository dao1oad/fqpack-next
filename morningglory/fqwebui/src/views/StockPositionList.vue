<template>
  <div style="padding: 4px;">
    <el-divider content-position="center">持仓股列表</el-divider>
    <el-table
      v-loading="isLoading"
      :data="positionList"
      highlight-current-row
      style="width: 100%"
      size="small"
      fit
      :stripe="true"
      :border="true"
    >
      <el-table-column
        label="序号"
        width="50"
        type="index"
        :index="
          index => {
            return index + 1 + (listQuery.current - 1) * listQuery.size
          }
        "
      >
      </el-table-column>
      <el-table-column label="品种" prop="symbol" align="center">
        <template #default="{ row }">
          <el-link
            type="primary"
            underline="never"
            @click="handleJumpToKline(row.symbol, '1m')"
            >{{ row.symbol }}</el-link
          >
        </template>
      </el-table-column>
      <el-table-column prop="name" label="名称"></el-table-column>
      <el-table-column
        prop="quantity"
        label="数量"
      ></el-table-column>
      <el-table-column prop="amount" label="金额"></el-table-column>
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
      <div style="padding: 4px;">
        <el-button @click="openCurrentAll">打开本页全部</el-button>
      </div>
    </el-row>
  </div>
</template>

<script>
import CommonTool from '@/tool/CommonTool'
import { stockApi } from '@/api/stockApi'
import _ from 'lodash'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { reactive } from 'vue'

export default {
  name: 'PositionList',
  props: {},
  data () {
    return {}
  },
  setup () {
    const listQuery = reactive({
      size: 10,
      total: 0,
      current: 1
    })
    const { isLoading, data: positionList } = useQuery({
      queryKey: ['stockPositionList'],
      queryFn: async () => {
        const positionList = await stockApi.getPositionList({ page: 1, size: 1000 })
        listQuery.total = _.size(positionList)
        const start = (listQuery.current - 1) * listQuery.size
        const end = start + listQuery.size
        return _.slice(positionList, start, end)
      },
      refetchInterval: 30000,
      staleTime: 5000
    })
    const queryClient = useQueryClient()
    return { isLoading, positionList, listQuery, queryClient }
  },
  methods: {
    handleSizeChange (currentSize) {
      this.listQuery.size = currentSize
      this.queryClient.invalidateQueries({ queryKey: ['stockPositionList'] })
    },
    handlePageChange (currentPage) {
      this.listQuery.current = currentPage
      this.queryClient.invalidateQueries({ queryKey: ['stockPositionList'] })
    },
    handleJumpToKline (symbol, period) {
      const routeUrl = this.$router.resolve({
        path: '/kline-big',
        query: {
          symbol,
          period,
          endDate: CommonTool.dateFormat('yyyy-MM-dd')
        }
      })
      window.open(routeUrl.href, '_blank')
    },
    openCurrentAll () {
      for (let i = 0; i < this.positionList.length; i++) {
        const routeUrl = this.$router.resolve({
          path: '/kline-big',
          query: {
            symbol: this.positionList[i].symbol,
            period: '1m',
            endDate: CommonTool.dateFormat('yyyy-MM-dd')
          }
        })
        window.open(routeUrl.href, '_blank')
      }
    },

  }
}
</script>
<style lang="stylus">
.stock-position-list-main {
  .form-input {
    width: 200px !important;
  }

  .form-input-short {
    width: 100px !important;
  }

  .long-textarea {
    width: 350px;
  }

  .query-position-form {
    margin-bottom: 10px;
  }
}
</style>
