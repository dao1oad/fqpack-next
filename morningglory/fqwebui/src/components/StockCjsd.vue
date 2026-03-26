<template>
  <WorkbenchPage class="stock-cjsd-page">
    <MyHeader />

    <div class="workbench-body stock-cjsd-body">
      <WorkbenchToolbar class="stock-cjsd-toolbar">
        <div class="workbench-toolbar__header">
          <div class="workbench-title-group">
            <div class="workbench-page-title">超级赛道</div>
            <div class="workbench-page-meta">
              <span>按日期回看</span>
              <span>/</span>
              <span>十个赛道并排对照</span>
            </div>
          </div>

          <div class="workbench-toolbar__actions">
            <el-button @click="refreshList">刷新</el-button>
          </div>
        </div>

        <WorkbenchSummaryRow class="stock-cjsd-summary">
          <StatusChip variant="muted">
            记录数 <strong>{{ listQuery.total }}</strong>
          </StatusChip>
          <StatusChip variant="info">点击个股可跳转 K 线大图</StatusChip>
          <StatusChip variant="warning">默认保留十个赛道并排结构</StatusChip>
        </WorkbenchSummaryRow>
      </WorkbenchToolbar>

      <WorkbenchLedgerPanel class="stock-cjsd-panel">
        <div class="workbench-panel__header">
          <div class="workbench-title-group">
            <div class="workbench-panel__title">超级赛道回看</div>
            <p class="workbench-panel__desc">按交易日回看各赛道及其包含的股票，支持从赛道表中直接跳转行情图。</p>
          </div>
        </div>

        <div class="stock-cjsd-panel__table">
          <el-table v-loading="isLoading" :data="cjsdList" size="small" fit :stripe="true" :border="true">
            <el-table-column prop="date" label="日期" width="100" />
            <el-table-column prop="cjsd_1" label="超级赛道1">
              <template #default="scope">
                <el-table :data="scope.row.cjsd_1.codes">
                  <el-table-column prop="name" :label="scope.row.cjsd_1.name">
                    <template #default="stockScope">
                      <el-link
                        type="primary"
                        underline="never"
                        @click="jumpToKline(stockScope.row.code)"
                      >
                        {{ stockScope.row.code }}<br />{{ stockScope.row.name }}
                      </el-link>
                    </template>
                  </el-table-column>
                </el-table>
              </template>
            </el-table-column>
            <el-table-column prop="cjsd_2" label="超级赛道2">
              <template #default="scope">
                <el-table :data="scope.row.cjsd_2.codes">
                  <el-table-column prop="name" :label="scope.row.cjsd_2.name">
                    <template #default="stockScope">
                      <el-link
                        type="primary"
                        underline="never"
                        @click="jumpToKline(stockScope.row.code)"
                      >
                        {{ stockScope.row.code }}<br />{{ stockScope.row.name }}
                      </el-link>
                    </template>
                  </el-table-column>
                </el-table>
              </template>
            </el-table-column>
            <el-table-column prop="cjsd_3" label="超级赛道3">
              <template #default="scope">
                <el-table :data="scope.row.cjsd_3.codes">
                  <el-table-column prop="name" :label="scope.row.cjsd_3.name">
                    <template #default="stockScope">
                      <el-link
                        type="primary"
                        underline="never"
                        @click="jumpToKline(stockScope.row.code)"
                      >
                        {{ stockScope.row.code }}<br />{{ stockScope.row.name }}
                      </el-link>
                    </template>
                  </el-table-column>
                </el-table>
              </template>
            </el-table-column>
            <el-table-column prop="cjsd_4" label="超级赛道4">
              <template #default="scope">
                <el-table :data="scope.row.cjsd_4.codes">
                  <el-table-column prop="name" :label="scope.row.cjsd_4.name">
                    <template #default="stockScope">
                      <el-link
                        type="primary"
                        underline="never"
                        @click="jumpToKline(stockScope.row.code)"
                      >
                        {{ stockScope.row.code }}<br />{{ stockScope.row.name }}
                      </el-link>
                    </template>
                  </el-table-column>
                </el-table>
              </template>
            </el-table-column>
            <el-table-column prop="cjsd_5" label="超级赛道5">
              <template #default="scope">
                <el-table :data="scope.row.cjsd_5.codes">
                  <el-table-column prop="name" :label="scope.row.cjsd_5.name">
                    <template #default="stockScope">
                      <el-link
                        type="primary"
                        underline="never"
                        @click="jumpToKline(stockScope.row.code)"
                      >
                        {{ stockScope.row.code }}<br />{{ stockScope.row.name }}
                      </el-link>
                    </template>
                  </el-table-column>
                </el-table>
              </template>
            </el-table-column>
            <el-table-column prop="cjsd_6" label="超级赛道6">
              <template #default="scope">
                <el-table :data="scope.row.cjsd_6.codes">
                  <el-table-column prop="name" :label="scope.row.cjsd_6.name">
                    <template #default="stockScope">
                      <el-link
                        type="primary"
                        underline="never"
                        @click="jumpToKline(stockScope.row.code)"
                      >
                        {{ stockScope.row.code }}<br />{{ stockScope.row.name }}
                      </el-link>
                    </template>
                  </el-table-column>
                </el-table>
              </template>
            </el-table-column>
            <el-table-column prop="cjsd_7" label="超级赛道7">
              <template #default="scope">
                <el-table :data="scope.row.cjsd_7.codes">
                  <el-table-column prop="name" :label="scope.row.cjsd_7.name">
                    <template #default="stockScope">
                      <el-link
                        type="primary"
                        underline="never"
                        @click="jumpToKline(stockScope.row.code)"
                      >
                        {{ stockScope.row.code }}<br />{{ stockScope.row.name }}
                      </el-link>
                    </template>
                  </el-table-column>
                </el-table>
              </template>
            </el-table-column>
            <el-table-column prop="cjsd_8" label="超级赛道8">
              <template #default="scope">
                <el-table :data="scope.row.cjsd_8.codes">
                  <el-table-column prop="name" :label="scope.row.cjsd_8.name">
                    <template #default="stockScope">
                      <el-link
                        type="primary"
                        underline="never"
                        @click="jumpToKline(stockScope.row.code)"
                      >
                        {{ stockScope.row.code }}<br />{{ stockScope.row.name }}
                      </el-link>
                    </template>
                  </el-table-column>
                </el-table>
              </template>
            </el-table-column>
            <el-table-column prop="cjsd_9" label="超级赛道9">
              <template #default="scope">
                <el-table :data="scope.row.cjsd_9.codes">
                  <el-table-column prop="name" :label="scope.row.cjsd_9.name">
                    <template #default="stockScope">
                      <el-link
                        type="primary"
                        underline="never"
                        @click="jumpToKline(stockScope.row.code)"
                      >
                        {{ stockScope.row.code }}<br />{{ stockScope.row.name }}
                      </el-link>
                    </template>
                  </el-table-column>
                </el-table>
              </template>
            </el-table-column>
            <el-table-column prop="cjsd_10" label="超级赛道10">
              <template #default="scope">
                <el-table :data="scope.row.cjsd_10.codes">
                  <el-table-column prop="name" :label="scope.row.cjsd_10.name">
                    <template #default="stockScope">
                      <el-link
                        type="primary"
                        underline="never"
                        @click="jumpToKline(stockScope.row.code)"
                      >
                        {{ stockScope.row.code }}<br />{{ stockScope.row.name }}
                      </el-link>
                    </template>
                  </el-table-column>
                </el-table>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div class="stock-cjsd-panel__pager">
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
        </div>
      </WorkbenchLedgerPanel>
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
import WorkbenchLedgerPanel from '@/components/workbench/WorkbenchLedgerPanel.vue'
import WorkbenchPage from '@/components/workbench/WorkbenchPage.vue'
import WorkbenchSummaryRow from '@/components/workbench/WorkbenchSummaryRow.vue'
import WorkbenchToolbar from '@/components/workbench/WorkbenchToolbar.vue'

export default {
  name: 'StockCjsd',
  components: {
    MyHeader,
    StatusChip,
    WorkbenchLedgerPanel,
    WorkbenchPage,
    WorkbenchSummaryRow,
    WorkbenchToolbar,
  },
  setup () {
    const listQuery = reactive({
      size: 10,
      total: 0,
      current: 1,
    })
    const { isLoading, data: cjsdList } = useQuery({
      queryKey: ['cjsdList'],
      queryFn: async () => {
        const cjsdList = await stockApi.getCjsdList({
          page: 1,
          size: 1000,
        })
        listQuery.total = _.size(cjsdList)
        const start = (listQuery.current - 1) * listQuery.size
        const end = start + listQuery.size
        return _.slice(cjsdList, start, end)
      },
      refetchInterval: 600000,
      staleTime: 5000,
    })
    const queryClient = useQueryClient()
    return { isLoading, cjsdList, listQuery, queryClient }
  },
  methods: {
    refreshList () {
      this.listQuery.current = 1
      this.queryClient.invalidateQueries({ queryKey: ['cjsdList'] })
    },
    handleSizeChange (currentSize) {
      this.listQuery.size = currentSize
      this.queryClient.invalidateQueries({ queryKey: ['cjsdList'] })
    },
    handlePageChange (currentPage) {
      this.listQuery.current = currentPage
      this.queryClient.invalidateQueries({ queryKey: ['cjsdList'] })
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
  },
}
</script>

<style lang="stylus" scoped>
.stock-cjsd-body
  gap 12px

.stock-cjsd-toolbar
  flex 0 0 auto

.stock-cjsd-panel
  flex 1 1 auto
  min-height 0

.stock-cjsd-panel__table
  flex 1 1 auto
  min-height 0
  overflow auto

.stock-cjsd-panel__pager
  margin-top 10px
  flex 0 0 auto

.stock-cjsd-panel :deep(.el-table .el-table__cell)
  vertical-align top
</style>
