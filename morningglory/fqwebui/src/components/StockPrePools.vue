<template>
  <div class="stock-pool-subview">
      <div class="workbench-panel__header stock-pool-subview__header">
        <div class="workbench-title-group">
          <div class="workbench-panel__title">预选股票池</div>
          <p class="workbench-panel__desc">由 CLX 正式结果自动生成，只读展示。</p>
        </div>
      </div>
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
          <el-table-column prop="datetime" label="时间"> </el-table-column>
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
  },
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

.stock-pool-subview__menu
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
