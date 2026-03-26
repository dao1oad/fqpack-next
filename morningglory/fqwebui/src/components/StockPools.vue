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
            <el-button type="primary" @click="showAddStockDialog">添加股票</el-button>
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
              <p class="workbench-panel__desc">维护当前监控池股票，支持跳转大图、删除和加入必选池。</p>
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
              <el-table-column prop="stop_loss_price" label="止损价格" />
              <el-table-column prop="datetime" label="时间" />
              <el-table-column label="操作" width="180">
                <template #default="scope">
                  <div class="stock-pool-actions">
                    <el-button @click="addToStockMustPoolsByCode(scope.row)">添加到必选</el-button>
                    <el-button @click="deleteFromStockPoolsByCode(scope.row)">删除</el-button>
                  </div>
                </template>
              </el-table-column>
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

      <el-dialog title="增加必选股票" v-model="dialogFormVisible">
        <el-form :model="form" size="large">
          <el-form-item label="股票号" :label-width="formLabelWidth">
            <el-input v-model="form.code" :readonly="true" />
          </el-form-item>
          <el-form-item label="止损价格" :label-width="formLabelWidth">
            <el-input-number v-model="form.stop_loss_price" :precision="2" :step="0.01" />
          </el-form-item>
          <el-form-item label="首次买入金额" :label-width="formLabelWidth">
            <el-input-number v-model="form.initial_lot_amount" :precision="2" :step="1" />
          </el-form-item>
          <el-form-item label="每次买入金额" :label-width="formLabelWidth">
            <el-input-number v-model="form.lot_amount" :precision="2" :step="1" />
          </el-form-item>
        </el-form>
        <template #footer>
          <div class="dialog-footer">
            <el-button @click="dialogFormVisible = false">取 消</el-button>
            <el-button type="primary" @click="confirmAddMust">确 定</el-button>
          </div>
        </template>
      </el-dialog>

      <el-dialog title="添加股票到监控池" v-model="addStockDialogVisible">
        <el-form :model="addStockForm" size="large">
          <el-form-item label="股票代码" :label-width="formLabelWidth">
            <el-input v-model="addStockForm.code" placeholder="请输入股票代码，如：000001" />
          </el-form-item>
          <el-form-item label="分类" :label-width="formLabelWidth">
            <el-input v-model="addStockForm.category" placeholder="请输入分类，如：自定义" />
          </el-form-item>
          <el-form-item label="止损价格" :label-width="formLabelWidth">
            <el-input-number v-model="addStockForm.stop_loss_price" :precision="2" :step="0.01" />
          </el-form-item>
        </el-form>
        <template #footer>
          <div class="dialog-footer">
            <el-button @click="addStockDialogVisible = false">取 消</el-button>
            <el-button type="primary" @click="confirmAddStock">确 定</el-button>
          </div>
        </template>
      </el-dialog>
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
      form: {
        code: null,
        stop_loss_price: null,
        initial_lot_amount: null,
        lot_amount: null,
      },
      addStockForm: {
        code: null,
        category: 'Custom',
        stop_loss_price: null,
      },
      formLabelWidth: '120px',
      dialogFormVisible: false,
      addStockDialogVisible: false,
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
      refetchInterval: 600000,
      staleTime: 5000,
    })
    const queryClient = useQueryClient()
    return { isLoading, stockList, listQuery, queryClient }
  },
  methods: {
    showAddStockDialog () {
      this.addStockForm.code = null
      this.addStockForm.stop_loss_price = null
      this.addStockDialogVisible = true
    },
    confirmAddStock () {
      if (!this.addStockForm.code) {
        this.$message({
          message: '请输入股票代码',
          type: 'warning',
        })
        return
      }
      if (!this.addStockForm.stop_loss_price) {
        this.$message({
          message: '请输入止损价格',
          type: 'warning',
        })
        return
      }

      stockApi.addToStockPoolsByStock(this.addStockForm)
        .then(res => {
          if (res.code === '0') {
            this.addStockDialogVisible = false
            this.refreshStockList()
            this.$message({
              message: '添加成功',
              type: 'success',
            })
          } else {
            this.$message({
              message: '添加失败',
              type: 'error',
            })
          }
        })
        .catch(() => {
          this.$message({
            message: '添加失败',
            type: 'error',
          })
        })
    },
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
    addToStockMustPoolsByCode (row) {
      this.form.code = row.code
      this.form.stop_loss_price = row.stop_loss_price
      this.form.initial_lot_amount = null
      this.form.lot_amount = null
      this.dialogFormVisible = true
    },
    confirmAddMust () {
      stockApi.addToStockMustPoolsByCode(this.form.code, this.form.stop_loss_price, this.form.initial_lot_amount, this.form.lot_amount)
        .then(res => {
          if (res.code === '0') {
            this.dialogFormVisible = false
            this.$refs.stockMustPoolsRef.refreshStockMustPoolList()
            this.$message({
              message: '添加成功',
              type: 'success',
            })
          } else {
            this.$message({
              message: '添加失败',
              type: 'error',
            })
          }
        })
        .catch(() => {
          this.$message({
            message: '添加失败',
            type: 'error',
          })
        })
    },
    deleteFromStockPoolsByCode (stock) {
      stockApi.deleteFromStockPoolsByCode(stock.code)
        .then(res => {
          if (res.code === '0') {
            this.listQuery.current = 1
            this.queryClient.invalidateQueries({ queryKey: ['stockPoolList'] })
            this.$message({
              message: '删除成功',
              type: 'success',
            })
          } else {
            this.$message({
              message: '删除失败',
              type: 'error',
            })
          }
        })
        .catch(() => {
          this.$message({
            message: '删除失败',
            type: 'error',
          })
        })
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
