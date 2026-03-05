<template>
  <div class="stock-pool-main">
    <MyHeader></MyHeader>
    <el-row>
      <el-col :span="12">
        <el-divider content-position="center">监控股票池</el-divider>
        <div style="margin-bottom: 10px; text-align: right;">
          <el-button type="primary" @click="showAddStockDialog">添加股票</el-button>
        </div>
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
          <el-table-column prop="datetime" label="时间"> </el-table-column>
          <el-table-column label="操作">
            <template #default="scope">
              <el-button @click="addToStockMustPoolsByCode(scope.row)">添加到必选</el-button>
              <el-button @click="deleteFromStockPoolsByCode(scope.row)">删除</el-button>
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
      </el-col>
      <el-col :span="12">
        <!-- 候选股 -->
        <StockPrePools @stock-refresh="refreshStockList"/>
      </el-col>
    </el-row>
    <el-row>
      <el-col :span="12">
        <!-- 必选 -->
        <StockMustPools ref="stockMustPoolsRef"/>
      </el-col>
    </el-row>
    <el-dialog title="增加必选股票" v-model="dialogFormVisible">
      <el-form :model="form" size="large">
        <el-form-item label="股票号" :label-width="formLabelWidth">
          <el-input v-model="form.code" :readonly="true"></el-input>
        </el-form-item>
        <el-form-item label="止损价格" :label-width="formLabelWidth">
          <el-input-number v-model="form.stop_loss_price" :precision="2" :step="0.01"></el-input-number>
        </el-form-item>
        <el-form-item label="首次买入金额" :label-width="formLabelWidth">
          <el-input-number v-model="form.initial_lot_amount" :precision="2" :step="1"></el-input-number>
        </el-form-item>
        <el-form-item label="每次买入金额" :label-width="formLabelWidth">
          <el-input-number v-model="form.lot_amount" :precision="2" :step="1"></el-input-number>
        </el-form-item>
        <el-form-item label="是否永久" :label-width="formLabelWidth">
          <el-switch v-model="form.forever" active-text="是" inactive-text="否"></el-switch>
        </el-form-item>
      </el-form>
      <template v-slot:footer>
        <div  class="dialog-footer">
          <el-button @click="dialogFormVisible = false">取 消</el-button>
          <el-button type="primary" @click="confirmAddMust">确 定</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 添加股票到监控池对话框 -->
    <el-dialog title="添加股票到监控池" v-model="addStockDialogVisible">
      <el-form :model="addStockForm" size="large">
        <el-form-item label="股票代码" :label-width="formLabelWidth">
          <el-input v-model="addStockForm.code" placeholder="请输入股票代码，如：000001"></el-input>
        </el-form-item>
        <el-form-item label="分类" :label-width="formLabelWidth">
          <el-input v-model="addStockForm.category" placeholder="请输入分类，如：自定义"/>
        </el-form-item>
        <el-form-item label="止损价格" :label-width="formLabelWidth">
          <el-input-number v-model="addStockForm.stop_loss_price" :precision="2" :step="0.01"></el-input-number>
        </el-form-item>
      </el-form>
      <template v-slot:footer>
        <div class="dialog-footer">
          <el-button @click="addStockDialogVisible = false">取 消</el-button>
          <el-button type="primary" @click="confirmAddStock">确 定</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import { stockApi } from '@/api/stockApi'
import CommonTool from '@/tool/CommonTool'
import MyHeader from '../views/MyHeader.vue'
import _ from 'lodash'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { reactive } from 'vue'
import StockPrePools from '@/components/StockPrePools.vue'
import StockMustPools from '@/components/StockMustPools.vue'

export default {
  name: 'StockPools',
  components: {
    MyHeader,
    StockPrePools,
    StockMustPools
  },
  data () {
    return {
      form: {
        code: null,
        stop_loss_price: null,
        initial_lot_amount: null,
        lot_amount: null,
        forever: false
      },
      addStockForm: {
        code: null,
        category: 'Custom',
        stop_loss_price: null
      },
      formLabelWidth: '120px',
      dialogFormVisible: false,
      addStockDialogVisible: false
    }
  },
  setup () {
    const listQuery = reactive({
      size: 10,
      total: 0,
      current: 1
    })
    const { isLoading, data: stockList } = useQuery({
      queryKey: ['stockPoolList'],
      queryFn: async () => {
        const stockList = await stockApi.getStockPoolsList({
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
    showAddStockDialog () {
      this.addStockForm.code = null
      this.addStockForm.stop_loss_price = null
      this.addStockDialogVisible = true
    },
    confirmAddStock () {
      if (!this.addStockForm.code) {
        this.$message({
          message: '请输入股票代码',
          type: 'warning'
        })
        return
      }
      if (!this.addStockForm.stop_loss_price) {
        this.$message({
          message: '请输入止损价格',
          type: 'warning'
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
              type: 'success'
            })
          } else {
            this.$message({
              message: '添加失败',
              type: 'error'
            })
          }
        })
        .catch(() => {
          this.$message({
            message: '添加失败',
            type: 'error'
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
    addToStockMustPoolsByCode (row) {
      this.form.code = row.code
      this.form.stop_loss_price = row.stop_loss_price
      this.form.initial_lot_amount = null
      this.form.lot_amount = null
      this.form.forever = false
      this.dialogFormVisible = true
    },
    confirmAddMust () {
      stockApi.addToStockMustPoolsByCode(this.form.code, this.form.stop_loss_price, this.form.initial_lot_amount, this.form.lot_amount, this.form.forever)
        .then(res => {
          if (res.code === '0') {
            this.dialogFormVisible = false
            this.$refs.stockMustPoolsRef.refreshStockMustPoolList()
            this.$message({
              message: '添加成功',
              type: 'success'
            })
          } else {
            this.$message({
              message: '添加失败',
              type: 'error'
            })
          }
        })
        .catch(() => {
          this.$message({
            message: '添加失败',
            type: 'error'
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
              type: 'success'
            })
          } else {
            this.$message({
              message: '删除失败',
              type: 'error'
            })
          }
        })
        .catch(() => {
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
