<template>
  <div class="stock-pool-subview">
      <el-divider content-position="center">预选股票池</el-divider>
      <el-row class="stock-pool-subview__menu">
        <el-menu :default-active="currentCategory" @select="handleCategoryChange" mode="horizontal">
          <el-menu-item v-for="cat in categoryList" :key="cat" :index="cat">
            {{ cat }}
          </el-menu-item>
        </el-menu>
      </el-row>
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
                <el-button @click="showAddDialog(scope.row)">加入监控池</el-button>
                <el-button @click="deleteFromStockPrePoolsByCode(scope.row)">删除</el-button>
              </template>
          </el-table-column>
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

      <!-- 添加监控池弹窗 -->
      <el-dialog
        v-model="dialogVisible"
        title="加入监控池"
        width="30%"
        :close-on-click-modal="false"
      >
        <el-form :model="monitorForm" label-width="80px">
          <el-form-item label="股票代码">
            <el-input v-model="monitorForm.code" placeholder="请输入股票代码" readonly />
          </el-form-item>
          <el-form-item label="监控天数">
            <el-input-number v-model="monitorForm.days" :min="1" :max="365" />
          </el-form-item>
        </el-form>
        <template #footer>
          <span class="dialog-footer">
            <el-button @click="dialogVisible = false">取消</el-button>
            <el-button type="primary" @click="confirmAddToPool">确认添加</el-button>
          </span>
        </template>
      </el-dialog>
  </div>
</template>

<script>
/* eslint-disable */
import { stockApi } from '@/api/stockApi'
import CommonTool from '@/tool/CommonTool'
import _ from 'lodash'

export default {
  name: 'StockPrePools',
  data() {
    return {
      categoryList: null,
      currentCategory: null,
      stockList: [],
      isLoading: false,
      listQuery: {
        size: 10,
        total: 0,
        current: 1
      },
      dialogVisible: false,
      monitorForm: {
        code: null,
        days: 30
      }
    }
  },
  async created() {
    await this.getStockPrePoolsCategory()
    this.fetchStockList()
  },
  methods: {
    handleSizeChange(currentSize) {
      this.listQuery.size = currentSize
      this.fetchStockList()
    },
    handlePageChange(currentPage) {
      this.listQuery.current = currentPage
      this.fetchStockList()
    },
    async getStockPrePoolsCategory() {
      try {
        var response = await stockApi.getStockPrePoolsCategory()
        console.log(response)
        if (response.data && response.code == '0') {
          this.categoryList = response.data
          if (this.categoryList && this.categoryList.length > 0) {
            this.currentCategory = this.categoryList[0]
          }
        }
      } catch (error) {
        console.error('获取分类列表失败:', error)
        this.$message.error('获取分类列表失败')
      }
    },

    async fetchStockList() {
      this.isLoading = true
      try {
        var response = await stockApi.getStockPrePoolsList({
          page: 1,
          size: 1000,
          category: this.currentCategory
        })

        if (response) {
          var stockList = response
          this.listQuery.total = _.size(stockList)
          var start = (this.listQuery.current - 1) * this.listQuery.size
          var end = start + this.listQuery.size
          this.stockList = _.slice(stockList, start, end)
        }
      } catch (error) {
        console.error('获取股票列表失败:', error)
        this.$message.error('获取股票列表失败')
      } finally {
        this.isLoading = false
      }
    },

    handleCategoryChange(category) {
      this.listQuery.current = 1
      this.currentCategory = category
      this.fetchStockList()
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
    showAddDialog(stock) {
      this.monitorForm.code = stock.code;
      this.monitorForm.days = 30; // 默认30天
      this.dialogVisible = true;
    },

    confirmAddToPool() {
      stockApi.addToStockPoolsByCode(this.monitorForm.code, this.monitorForm.days)
      .then(res => {
        if (res.code === '0') {
          this.$message({
            message: '加入监控池成功',
            type: 'success'
          });
          this.dialogVisible = false;
          this.$emit('stock-refresh');
        } else {
          this.$message({
            message: '加入监控池失败',
            type: 'error'
          });
        }
      })
      .catch(err => {
        this.$message({
          message: '加入监控池失败',
          type: 'error'
        });
      });
    },
    deleteFromStockPrePoolsByCode(stock){
      stockApi.deleteFromStockPrePoolsByCode(stock.code)
      .then(res => {
        if (res.code === '0') {
          this.$message({
            message: '删除成功',
            type: 'success'
          })
          this.listQuery.current = 1
          this.fetchStockList()
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

  },
}
</script>
<style lang="stylus" scoped>
.stock-pool-subview
  display flex
  flex-direction column
  min-height 0
  height 100%

.stock-pool-subview__menu
  flex 0 0 auto
  margin-bottom 10px

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
