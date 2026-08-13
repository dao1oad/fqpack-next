<template>
  <WorkbenchPage class="stock-pool-page">
    <MyHeader />

    <div class="workbench-body stock-pool-body">
      <WorkbenchToolbar class="stock-pool-toolbar">
        <div class="workbench-toolbar__header">
          <div class="workbench-title-group">
            <div class="workbench-page-title">股票池</div>
            <div class="workbench-page-meta">
              <span>监控池主列表</span>
              <span>/</span>
              <span>右侧预选池与必选池并排常驻</span>
            </div>
          </div>

          <div class="workbench-toolbar__actions">
            <el-button @click="refreshStockList">刷新</el-button>
            <el-button
              type="primary"
              :loading="stockTdxSyncing"
              @click="syncStockPoolsFromTdx"
            >
              同步自选股
            </el-button>
          </div>
        </div>

        <WorkbenchSummaryRow class="stock-pool-summary">
          <StatusChip variant="muted">
            监控池 <strong>{{ listQuery.total }}</strong>
          </StatusChip>
          <StatusChip variant="info">预选池与必选池在右栏常驻</StatusChip>
          <StatusChip variant="warning">默认整批拉取后前端分页</StatusChip>
        </WorkbenchSummaryRow>
      </WorkbenchToolbar>

      <div class="stock-pool-grid">
        <WorkbenchLedgerPanel class="stock-pool-panel stock-pool-panel--main">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">监控股票池</div>
              <p class="workbench-panel__desc">以通达信自选股（ZXG.blk）为唯一来源，覆盖同步并排除持仓。</p>
            </div>
          </div>

          <div class="stock-pool-panel__table">
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
              <el-table-column prop="name" label="名字" />
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
              <el-table-column prop="datetime" label="时间" />
            </el-table>
          </div>

          <div class="stock-pool-panel__pager">
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
          </div>
        </WorkbenchLedgerPanel>

        <div class="stock-pool-side">
          <WorkbenchSidebarPanel class="stock-pool-panel stock-pool-panel--side">
            <StockPrePools @stock-refresh="refreshStockList" />
          </WorkbenchSidebarPanel>

          <WorkbenchSidebarPanel class="stock-pool-panel stock-pool-panel--side">
            <StockMustPools ref="stockMustPoolsRef" />
          </WorkbenchSidebarPanel>
        </div>
      </div>

    </div>
  </WorkbenchPage>
</template>

<script>
import { stockApi } from '@/api/stockApi'
import CommonTool from '@/tool/CommonTool'
import MyHeader from '../views/MyHeader.vue'
import _ from 'lodash'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { reactive } from 'vue'
import { pollingSlow } from '../lib/queryPolicies.mjs'
import StatusChip from '@/components/workbench/StatusChip.vue'
import StockPrePools from '@/components/StockPrePools.vue'
import StockMustPools from '@/components/StockMustPools.vue'
import WorkbenchLedgerPanel from '@/components/workbench/WorkbenchLedgerPanel.vue'
import WorkbenchPage from '@/components/workbench/WorkbenchPage.vue'
import WorkbenchSidebarPanel from '@/components/workbench/WorkbenchSidebarPanel.vue'
import WorkbenchSummaryRow from '@/components/workbench/WorkbenchSummaryRow.vue'
import WorkbenchToolbar from '@/components/workbench/WorkbenchToolbar.vue'

export default {
  name: 'StockPools',
  components: {
    MyHeader,
    StatusChip,
    StockPrePools,
    StockMustPools,
    WorkbenchLedgerPanel,
    WorkbenchPage,
    WorkbenchSidebarPanel,
    WorkbenchSummaryRow,
    WorkbenchToolbar,
  },
  data () {
    return {
      stockTdxSyncing: false,
    }
  },
  setup () {
    const listQuery = reactive({
      size: 10,
      total: 0,
      current: 1,
    })
    const { isLoading, data: stockList } = useQuery({
      queryKey: ['stockPoolList'],
      queryFn: async () => {
        const stockList = await stockApi.getStockPoolsList({
          page: 1,
          size: 1000,
        })
        listQuery.total = _.size(stockList)
        const start = (listQuery.current - 1) * listQuery.size
        const end = start + listQuery.size
        return _.slice(stockList, start, end)
      },
      ...pollingSlow,
    })
    const queryClient = useQueryClient()
    return { isLoading, stockList, listQuery, queryClient }
  },
  methods: {
    refreshStockList () {
      this.listQuery.current = 1
      this.queryClient.invalidateQueries({ queryKey: ['stockPoolList'] })
    },
    handleSizeChange (currentSize) {
      this.listQuery.size = currentSize
      this.queryClient.invalidateQueries({ queryKey: ['stockPoolList'] })
    },
    handlePageChange (currentPage) {
      this.listQuery.current = currentPage
      this.queryClient.invalidateQueries({ queryKey: ['stockPoolList'] })
    },
    jumpToKline (symbol) {
      const routeUrl = this.$router.resolve({
        path: '/kline-big',
        query: {
          symbol,
          period: '1m',
          endDate: CommonTool.dateFormat('yyyy-MM-dd'),
        },
      })
      window.open(routeUrl.href, '_blank')
    },
    syncStockPoolsFromTdx () {
      this.$confirm('将使用通达信“自选股”覆盖当前监控池，并自动排除持仓股。是否继续？', '同步自选股', {
        confirmButtonText: '继续',
        cancelButtonText: '取消',
        type: 'warning',
      }).then(async () => {
        this.stockTdxSyncing = true
        try {
          const result = await stockApi.syncStockPoolsFromTdx({ days: 30 })
          if (result && String(result.code ?? '0') !== '0') {
            throw new Error(result.msg || '同步自选股失败')
          }
          const summary = result?.data || {}
          this.refreshStockList()
          this.$message({
            message:
              '自选股已覆盖同步：同步 ' +
              (summary.synced_count ?? 0) +
              '，删除 ' +
              (summary.removed_count ?? 0) +
              '，持仓排除 ' +
              (summary.holding_excluded_count ?? summary.skipped_holding_count ?? 0) +
              '，无效 ' +
              (summary.invalid_count ?? summary.skipped_invalid_count ?? 0),
            type: 'success',
          })
        } catch (err) {
          this.$message({
            message: err?.message || '同步自选股失败',
            type: 'error',
          })
        } finally {
          this.stockTdxSyncing = false
        }
      }).catch(() => {})
    },
  },
}
</script>

<style lang="stylus" scoped>
.stock-pool-body
  gap 12px

.stock-pool-toolbar
  flex 0 0 auto

.stock-pool-grid
  display grid
  grid-template-columns minmax(0, 1.2fr) minmax(0, 1fr)
  gap 12px
  flex 1 1 auto
  min-height 0

.stock-pool-side
  display grid
  grid-template-rows minmax(0, 1fr) minmax(0, 1fr)
  gap 12px
  min-height 0

.stock-pool-panel
  min-height 0

.stock-pool-panel__table
  flex 1 1 auto
  min-height 0
  overflow auto

.stock-pool-panel__pager
  flex 0 0 auto
  margin-top 10px

.stock-pool-actions
  display flex
  gap 8px
  flex-wrap wrap

.stock-pool-panel :deep(.el-table .el-table__cell)
  vertical-align top

@media (max-width: 1440px)
  .stock-pool-body
    overflow auto

  .stock-pool-grid
    grid-template-columns 1fr
    height auto

  .stock-pool-side
    grid-template-rows repeat(2, minmax(320px, 1fr))
</style>
