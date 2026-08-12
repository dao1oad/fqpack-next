<template>
  <div class="stock-pool-subview">
      <div class="workbench-panel__header stock-pool-subview__header">
        <div class="workbench-title-group">
          <div class="workbench-panel__title">必选股票池</div>
          <p class="workbench-panel__desc">以通达信待买组（DM.blk）为唯一来源，覆盖同步并排除持仓。</p>
        </div>
        <div>
          <el-button
            size="small"
            type="warning"
            :loading="mustTdxSyncing"
            @click="syncMustPoolFromTdx"
          >
            同步待买组
          </el-button>
        </div>
      </div>
      <div class="stock-pool-subview__table">
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
            underline="hover"
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
        </el-table>
      </div>
      <el-row class="stock-pool-subview__pager">
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
import { stockApi } from '@/api/stockApi'
import CommonTool from '@/tool/CommonTool'
import _ from 'lodash'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { reactive } from 'vue'
import { pollingSlow } from '../lib/queryPolicies.mjs'

export default {
  name: 'StockMustPools',
  data () {
    return {
      mustTdxSyncing: false,
    }
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
      ...pollingSlow
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
    syncMustPoolFromTdx () {
      this.$confirm('将使用通达信“待买组”覆盖当前待买池，并自动排除持仓股；新代码自动使用系统默认参数。是否继续？', '同步待买组', {
        confirmButtonText: '继续',
        cancelButtonText: '取消',
        type: 'warning',
      }).then(async () => {
        this.mustTdxSyncing = true
        try {
          const result = await stockApi.syncMustPoolFromTdx({ days: 30 })
          if (result && String(result.code ?? '0') !== '0') {
            throw new Error(result.msg || '同步待买组失败')
          }
          const summary = result?.data || {}
          this.refreshStockMustPoolList()
          let message =
            '待买组已覆盖同步：同步 ' +
            (summary.synced_count ?? 0) +
            '，删除 ' +
            (summary.removed_count ?? 0) +
            '，持仓排除 ' +
            (summary.holding_excluded_count ?? summary.skipped_holding_count ?? 0) +
            '，无效 ' +
            (summary.invalid_count ?? summary.skipped_invalid_count ?? 0)
          if (summary.failed_count > 0) {
            message +=
              '，失败 ' +
              summary.failed_count +
              '（默认参数不可用）'
          }
          this.$message({
            message,
            type: 'success'
          })
        } catch (err) {
          // #589：空分组业务态（400 + code=empty_group）→ 显式确认后 allow_empty 清空。
          const errorCode = err?.response?.data?.code || err?.code
          if (errorCode === 'empty_group') {
            this.$confirm('待买分组为空，确认后清空 must_pool，是否继续？', '同步待买组', {
              confirmButtonText: '清空',
              cancelButtonText: '取消',
              type: 'warning',
            }).then(async () => {
              this.mustTdxSyncing = true
              try {
                const result = await stockApi.syncMustPoolFromTdx({
                  days: 30,
                  allowEmpty: true
                })
                if (result && String(result.code ?? '0') !== '0') {
                  throw new Error(result.msg || '同步待买组失败')
                }
                this.refreshStockMustPoolList()
                this.$message({
                  message: '待买分组为空，must_pool 已清空',
                  type: 'success'
                })
              } catch (retryErr) {
                this.$message({
                  message: retryErr?.message || '同步待买组失败',
                  type: 'error'
                })
              } finally {
                this.mustTdxSyncing = false
              }
            }).catch(() => {})
            return
          }
          this.$message({
            message: err?.message || '同步待买组失败',
            type: 'error'
          })
        } finally {
          this.mustTdxSyncing = false
        }
      }).catch(() => {})
    }
  }
}
</script>
<style lang="stylus" scoped>
.stock-pool-subview
  display flex
  flex-direction column
  gap 10px
  min-height 0
  height 100%

.stock-pool-subview__header
  flex 0 0 auto

.stock-pool-subview__table
  flex 1 1 auto
  min-height 0
  overflow auto

.stock-pool-subview__pager
  margin-top 10px
  flex 0 0 auto

.stock-pool-subview :deep(.el-table .el-table__cell)
  vertical-align top
</style>
