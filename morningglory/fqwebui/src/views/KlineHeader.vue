<template>
  <div class="kline-header-main">
    <div class="input-form">
      <el-space>
        <el-button
          type="primary"
          @click="jumpToControl('futures')"
          size="small"
          class="primary-button"
          >期货</el-button
        >
        <el-button
          type="danger"
          @click="jumpToControl('stock')"
          size="small"
          class="primary-button"
          >股票</el-button
        >
        <el-button
          type="success"
          @click="jumpToMultiPeriod"
          size="small"
          v-if="showPeriodList"
          class="primary-button"
          >多周期</el-button
        >
      </el-space>
      <el-space>
        <el-date-picker
          v-model="internalEndDate"
          type="date"
          placeholder="选择日期"
          format="YYYY 年 MM 月 DD 日"
          value-format="YYYY-MM-DD"
          size="small"
          @change="changeDate"
          class="ml-5 mr-5"
        >
        </el-date-picker>
      </el-space>
      <el-space>
        <el-button
          type="primary"
          class="primary-button"
          @click="quickSwitchDay('pre')"
          size="small"
          >前一天</el-button
        >
        <el-button
          type="primary"
          class="primary-button"
          @click="quickSwitchDay('next')"
          size="small"
          >后一天</el-button
        >
      </el-space>
      <el-space>
        <el-input
          v-model="internalInputSymbol"
          placeholder="请输入代码"
          size="small"
          class="search-symbol-input ml-5 mr-5"
          @change="submitSymbol"
        />
      </el-space>
      <el-space v-if="showPeriodList">
        <el-button
          type="primary"
          class="primary-button"
          v-for="period in periodList"
          :key="period"
          size="small"
          @click="switchPeriod(period)"
          >{{ period }}</el-button
        >
      </el-space>
      <el-space class="grid-button-container">
        <el-button type="primary" class="primary-button" size="small" @click="handleGrid">网格</el-button>
      </el-space>
    </div>

    <!-- 网格参数弹窗 -->
    <el-dialog
      v-model="gridDialogVisible"
      title="网格参数设置"
      width="45%"
      custom-class="grid-param-dialog"
    >
      <el-form :model="gridParams" label-width="120px">
        <el-form-item label="持仓信息">
          <div class="stock-info-content">
            股票代码：<span class="stock-code-display">{{ gridParams.code }}</span> |
            总持仓数量：<span class="total-display">{{ total_quantity }}</span> |
            总持仓金额：<span class="total-display">{{ total_amount.toFixed(2) }}</span>
          </div>
        </el-form-item>
        <el-form-item label="上限价格">
          <el-input v-model="gridParams.ceiling_price" type="number" :precision="2" :step="0.01"></el-input>
        </el-form-item>
        <el-form-item label="下限价格">
          <el-input v-model="gridParams.floor_price" type="number" :precision="2" :step="0.01"></el-input>
        </el-form-item>
        <el-form-item label="网格数量">
          <el-input v-model="gridParams.grid_num" type="number" :precision="0" :step="1" :min="1" :max="Math.floor(this.total_quantity / 100)"></el-input>
        </el-form-item>
        <el-form-item>
          <el-button type="success" @click="calculateGrid" :loading="isCalculating" :disabled="isCalculating">计算</el-button>
        </el-form-item>
      </el-form>

      <!-- 网格计算结果 -->
      <div v-if="gridResult" class="grid-result">
        <h3>网格交易计划</h3>
        <el-divider></el-divider>

        <h4>网格列表</h4>
        <el-table :data="gridResult.grid_list" border>
          <el-table-column label="价格" width="120">
            <template #default="scope">
              <el-input v-model="scope.row.price" type="number" size="small" :step="0.01" @input="recalculateGrid(scope.$index)"></el-input>
            </template>
          </el-table-column>
          <el-table-column label="数量" width="120">
            <template #default="scope">
              <el-input v-model="scope.row.quantity" type="number" size="small" :step="100" @input="recalculateGrid(scope.$index)"></el-input>
            </template>
          </el-table-column>
          <el-table-column label="金额" width="120">
            <template #default="scope">
              <span>{{ scope.row.amount }}</span>
            </template>
          </el-table-column>
          <el-table-column label="金额调整系数" width="150">
            <template #default="scope">
              <span>{{ scope.row.amount_adjust }}</span>
            </template>
          </el-table-column>
          <el-table-column label="价格差异" width="120">
            <template #default="scope">
              <span>{{ scope.row.price_diff }}</span>
            </template>
          </el-table-column>
          <el-table-column label="价格百分比" width="120">
            <template #default="scope">
              <span>{{ scope.row.price_percent }}</span>
            </template>
          </el-table-column>
        </el-table>

        <h4 class="mt-3">总计</h4>
        <el-form :model="gridResult.total" label-width="100px" inline>
          <el-form-item label="总数量">
            <span class="total-display">{{ gridResult.total.quantity }}</span>
          </el-form-item>
          <el-form-item label="总金额">
            <span class="total-display">{{ gridResult.total.amount }}</span>
          </el-form-item>
        </el-form>
      </div>

      <template #footer>
        <span class="dialog-footer">
          <el-button v-if="gridResult" @click="handleCancel" :disabled="isCalculating">取消</el-button>
          <el-button v-if="gridResult" type="primary" @click="submitGridParams" :disabled="isCalculating">提交</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>
<script>
import { stockApi } from '@/api/stockApi'
import { useQueryClient } from '@tanstack/vue-query'

export default {
  name: 'KlineHeader',
  setup() {
    const queryClient = useQueryClient()

    return {
      queryClient
    }
  },
  data () {
    return {
      internalEndDate: this.endDate,
      internalInputSymbol: this.inputSymbol,
      gridDialogVisible: false,
      gridParams: {
        ceiling_price: 0,
        floor_price: 0,
        grid_num: 0,
        code: ''
      },
      gridResult: null,
      isCalculating: false,
      total_quantity: 0,
      total_amount: 0,
    }
  },
  emits: ['update:endDate', 'update:inputSymbol'],
  props: {
    showPeriodList: {
      type: Boolean,
      default: false
    },
    quickCalc: {
      type: Object,
      default: null
    },
    submitSymbol: {
      type: Function,
      default: null
    },
    quickCalcMaxCount: {
      type: Function,
      default: null
    },
    quickSwitchDay: {
      type: Function,
      default: null
    },
    switchPeriod: {
      type: Function,
      default: null
    },
    jumpToControl: {
      type: Function,
      default: null
    },
    changeDate: {
      type: Function,
      default: null
    },
    jumpToMultiPeriod: {
      type: Function,
      default: null
    },
    quickSwitchSymbol: {
      type: Function,
      default: null
    },
    periodList: {
      type: Array,
      default: null
    },
    inputSymbol: {
      type: String,
      default: ''
    },
    endDate: {
      type: String,
      default: ''
    },
    futureSymbolList: {
      type: Array,
      default: null
    }
  },
  watch: {
    endDate (newVal) {
      this.internalEndDate = newVal
    },
    inputSymbol (newVal) {
      this.internalInputSymbol = newVal
    }
  },
  methods: {
    setELDatePicker (endDate) {
      this.internalEndDate = endDate
    },
    handleCancel () {
      if (this.gridResult) {
        this.$confirm('已生成网格计划，确定要取消吗？', '提示', {
          confirmButtonText: '确定',
          cancelButtonText: '取消',
          type: 'warning'
        }).then(() => {
          this.gridDialogVisible = false
        }).catch(() => {
          // do nothing on cancel
        })
      } else {
        this.gridDialogVisible = false
      }
    },
    async handleGrid () {
      const code = this.inputSymbol ? this.inputSymbol.substring(2) : ''
      if (!code) {
        this.$message.warning('请输入股票代码')
        return
      }

      try {
        const res = await stockApi.get_stock_hold_position(this.inputSymbol.slice(-6))
        if (res && res.code === 0 && res.data) {
          this.total_quantity = res.data.quantity || 0
          this.total_amount = Math.abs(res.data.amount || 0)
        }
      } catch (error) {
        console.error('获取持仓信息失败:', error)
        this.$message.error('获取持仓信息失败，将使用默认值')
      }

      try {
        const res = await stockApi.query_stock_fills(this.inputSymbol)
        const entryLedger = res?.data?.entry_ledger || res?.data?.stock_fills

        if (entryLedger && entryLedger.length > 0) {
          const prices = entryLedger.map(fill => fill.price)
          this.gridParams = {
            ceiling_price: Math.max(...prices),
            floor_price: Math.min(...prices),
            grid_num: entryLedger.length,
            code
          }
        } else {
          // 如果没有持仓信息，使用默认值
          this.gridParams = {
            ceiling_price: 0,
            floor_price: 0,
            grid_num: 10,
            code
          }
          this.$message.info('没有查询到持仓信息，使用默认值。')
        }
      } catch (error) {
        console.error('查询持仓信息失败', error)
        this.$message.error('获取持仓信息失败，将使用默认值')
        // 发生错误时，也使用默认值
        this.gridParams = {
          ceiling_price: 0,
          floor_price: 0,
          grid_num: 10,
          code
        }
      } finally {
        this.gridResult = null
        this.gridDialogVisible = true
      }
    },
    submitGridParams () {
      if (!this.gridResult) {
        this.$message({
          message: '网格计划不能为空',
          type: 'warning'
        })
        return
      }
      // 这里可以添加网格参数提交到后端的逻辑
      // 例如调用API保存网格参数
      stockApi.resetStockFills(this.gridResult)
        .then(res => {
        // 关闭弹窗
          this.gridDialogVisible = false
          this.$message({
            message: '网格计划设置成功',
            type: 'success'
          })
          // 使用 setup 中返回的 queryClient 来失效查询缓存
          this.queryClient.invalidateQueries({ queryKey: ['klineData'] })
        })
        .catch(err => {
          console.error('网格计划设置失败', err)
          let errorMessage = '网格计划设置失败: '
          if (err.response && err.response.data && err.response.data.error) {
            errorMessage += err.response.data.error
          } else if (err.message) {
            errorMessage += err.message
          } else {
            errorMessage += '未知错误'
          }
          this.$message({
            message: errorMessage,
            type: 'error'
          })
        })
    },
    recalculateGrid(index) {
      if (!this.gridResult || !this.gridResult.grid_list || !this.gridResult.grid_list[index]) {
        return
      }
      if (index >= 0 && index <= this.gridResult.grid_list.length - 1) {
        if (this.gridResult.grid_list[index + 1]) {
          if (this.gridResult.grid_list[index].price < this.gridResult.grid_list[index + 1].price) {
            this.gridResult.grid_list[index].price = this.gridResult.grid_list[index + 1].price
          }
        }
        if (index > 0) {
          if (this.gridResult.grid_list[index].price > this.gridResult.grid_list[index - 1].price) {
            this.gridResult.grid_list[index].price = this.gridResult.grid_list[index - 1].price
          }
        }
      }
      let totalQuantity = 0
      let totalAmount = 0
      this.gridResult.grid_list.forEach(row => {
        let quantity = parseInt(row.quantity)
        let price = parseFloat(row.price)
        row.quantity = quantity
        row.price = price
        let amount = quantity * price
        row.amount = amount
        totalQuantity += quantity
        totalAmount += amount
      })
      let amount_adjust = (this.total_amount / totalAmount).toFixed(6)
      this.gridResult.grid_list.forEach(row => {
        row.amount_adjust = amount_adjust
      })
      this.gridResult.total = {
        quantity: totalQuantity,
        amount: (totalAmount * amount_adjust).toFixed(6)
      }
      for (let i = 0; i < this.gridResult.grid_list.length - 1; i++) {
        this.gridResult.grid_list[i].price_diff = (this.gridResult.grid_list[i].price - this.gridResult.grid_list[i+1].price).toFixed(6)
        this.gridResult.grid_list[i].price_percent = ((this.gridResult.grid_list[i].price / this.gridResult.grid_list[i+1].price - 1) * 100).toFixed(6)
      }
    },
    calculateGrid () {
      // 验证价格数据
      const ceilingPrice = parseFloat(this.gridParams.ceiling_price)
      const floorPrice = parseFloat(this.gridParams.floor_price)

      // 检查价格是否为有效数字
      if (isNaN(ceilingPrice) || ceilingPrice <= 0) {
        this.$message({
          message: '上限价格必须是大于0的有效数字',
          type: 'warning'
        })
        return
      }

      if (isNaN(floorPrice) || floorPrice <= 0) {
        this.$message({
          message: '下限价格必须是大于0的有效数字',
          type: 'warning'
        })
        return
      }

      // 检查上限价格是否大于下限价格
      if (ceilingPrice <= floorPrice) {
        this.$message({
          message: '上限价格必须大于下限价格',
          type: 'warning'
        })
        return
      }

      // 验证网格数量范围
      const minGridNum = 1
      const maxGridNum = Math.floor(this.total_quantity / 100)

      if (this.gridParams.grid_num < minGridNum) {
        this.$message({
          message: `网格数量不能小于 ${minGridNum}`,
          type: 'warning'
        })
        return
      }

      if (this.gridParams.grid_num > maxGridNum) {
        this.$message({
          message: `网格数量不能大于 ${maxGridNum}`,
          type: 'warning'
        })
        return
      }

      // 设置计算中状态
      this.isCalculating = true

      stockApi.planGridTrade(this.gridParams)
        .then(res => {
          this.gridResult = res
          this.isCalculating = false
        })
        .catch(err => {
          console.error('计算网格失败', err)
          this.$message({
            message: '计算网格失败',
            type: 'error'
          })
          this.isCalculating = false
        })
    }
  }
}
</script>
<style lang="stylus">
@import "../style/kline-header.styl";

.kline-header-main
  display flex
  align-items center
.input-form
  display flex
  align-items center
  width 100%
  gap 10px
.grid-button-container
  margin-left auto
  margin-right 10px
.grid-result {
  margin-top: 20px;

  h3 {
    font-size: 18px;
    margin-bottom: 10px;
  }

  h4 {
    font-size: 16px;
    margin: 15px 0 10px 0;
  }

  .mt-3 {
    margin-top: 15px;
  }

  .grid-actions {
    margin: 10px 0;
    display: flex;
    justify-content: flex-end;
  }

  .el-input-number {
    width: 100%;
  }

  .el-table {
    --el-bg-color: #12161c;
    --el-table-bg-color: #12161c;
    margin-bottom: 15px;
  }

  .el-input--small {
    width: 100%;
  }
}

.el-dialog {
  --el-text-color-primary: white;
  --el-dialog-bg-color: #12161c;
}

.grid-param-dialog {
  .el-dialog__header {
    background: #12161c;
    border-bottom: 1px solid rgba(127, 127, 122, .2);
  }

  .el-dialog__headerbtn .el-dialog__close {
    color: white;
    &:hover {
      color: #409eff;
    }
  }

  .el-dialog__body {
    background: #12161c;
    color: white;
  }

  .el-dialog__footer {
    background: #12161c;
    border-top: 1px solid rgba(127, 127, 122, .2);

  }

  .el-form-item__label {
    color: white !important;
  }

  .el-input__wrapper {
    background-color: #12161c !important;
    box-shadow: none !important;
    border: 1px solid rgba(127, 127, 122, .2) !important;
  }
  .el-input__inner {
    background-color: transparent !important;
    color: white !important;
  }

  .el-input.is-disabled .el-input__wrapper {
    background-color: #12161c !important;
  }
  .el-input.is-disabled .el-input__inner {
    background-color: #12161c !important;
    color: #666 !important;
  }

  h3, h4 {
    color: white;
  }

  .el-divider--horizontal {
    border-top: 1px solid rgba(127, 127, 122, .2);
  }

  .stock-code-display {
    color: #409eff;
    font-weight: bold;
    font-size: 14px;
  }

  .total-display {
    color: white;
    font-weight: 500;
    font-size: 14px;
  }

  .stock-info-content {
    padding: 8px 11px;
    background-color: #12161c;
    border: 1px solid rgba(127, 127, 122, .2);
    border-radius: 4px;
    color: #ccc;
    font-size: 14px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-height: 32px;
    box-sizing: border-box;
    display: flex;
    align-items: center;
  }
}
</style>
