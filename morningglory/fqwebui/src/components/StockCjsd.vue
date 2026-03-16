<template>
  <div class="stock-cjsd-shell">
    <MyHeader></MyHeader>
    <div class="stock-cjsd-body">
      <section class="stock-cjsd-panel">
        <el-divider content-position="center">超级赛道</el-divider>
        <div class="stock-cjsd-panel__table">
          <el-table v-loading="isLoading" :data="cjsdList" size="small" fit :stripe="true" :border="true">
      <el-table-column prop="date" label="日期" width="100"> </el-table-column>
      <el-table-column prop="cjsd_1" label="超级赛道1">
        <template #default="scope">
          <el-table :data="scope.row.cjsd_1.codes">
            <el-table-column prop="name" :label="scope.row.cjsd_1.name">
              <template #default="scope">
                <el-link
                  type="primary"
                  :underline="false"
                  @click="jumpToKline(scope.row.code)"
                >
                  {{ scope.row.code }}<br/>{{ scope.row.name }}
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
              <template #default="scope">
                <el-link
                  type="primary"
                  :underline="false"
                  @click="jumpToKline(scope.row.code)"
                >
                  {{ scope.row.code }}<br/>{{ scope.row.name }}
                </el-link>
              </template>
            </el-table-column>
          </el-table></template
        >
      </el-table-column>
      <el-table-column prop="cjsd_3" label="超级赛道3">
        <template #default="scope">
          <el-table :data="scope.row.cjsd_3.codes">
            <el-table-column prop="name" :label="scope.row.cjsd_3.name">
              <template #default="scope">
                <el-link
                  type="primary"
                  :underline="false"
                  @click="jumpToKline(scope.row.code)"
                >
                  {{ scope.row.code }}<br/>{{ scope.row.name }}
                </el-link>
              </template>
            </el-table-column>
          </el-table></template
        >
      </el-table-column>
      <el-table-column prop="cjsd_4" label="超级赛道4">
        <template #default="scope">
          <el-table :data="scope.row.cjsd_4.codes">
            <el-table-column prop="name" :label="scope.row.cjsd_4.name">
              <template #default="scope">
                <el-link
                  type="primary"
                  :underline="false"
                  @click="jumpToKline(scope.row.code)"
                >
                  {{ scope.row.code }}<br/>{{ scope.row.name }}
                </el-link>
              </template>
            </el-table-column>
          </el-table></template
        >
      </el-table-column>
      <el-table-column prop="cjsd_5" label="超级赛道5">
        <template #default="scope">
          <el-table :data="scope.row.cjsd_5.codes">
            <el-table-column prop="name" :label="scope.row.cjsd_5.name">
              <template #default="scope">
                <el-link
                  type="primary"
                  :underline="false"
                  @click="jumpToKline(scope.row.code)"
                >
                  {{ scope.row.code }}<br/>{{ scope.row.name }}
                </el-link>
              </template>
            </el-table-column>
          </el-table></template
        >
      </el-table-column>
      <el-table-column prop="cjsd_6" label="超级赛道6">
        <template #default="scope">
          <el-table :data="scope.row.cjsd_6.codes">
            <el-table-column prop="name" :label="scope.row.cjsd_6.name">
              <template #default="scope">
                <el-link
                  type="primary"
                  :underline="false"
                  @click="jumpToKline(scope.row.code)"
                >
                  {{ scope.row.code }}<br/>{{ scope.row.name }}
                </el-link>
              </template>
            </el-table-column>
          </el-table></template
        >
      </el-table-column>
      <el-table-column prop="cjsd_7" label="超级赛道7">
        <template #default="scope">
          <el-table :data="scope.row.cjsd_7.codes">
            <el-table-column prop="name" :label="scope.row.cjsd_7.name">
              <template #default="scope">
                <el-link
                  type="primary"
                  :underline="false"
                  @click="jumpToKline(scope.row.code)"
                >
                  {{ scope.row.code }}<br/>{{ scope.row.name }}
                </el-link>
              </template>
            </el-table-column>
          </el-table></template
        >
      </el-table-column>
      <el-table-column prop="cjsd_8" label="超级赛道8">
        <template #default="scope">
          <el-table :data="scope.row.cjsd_8.codes">
            <el-table-column prop="name" :label="scope.row.cjsd_8.name">
              <template #default="scope">
                <el-link
                  type="primary"
                  :underline="false"
                  @click="jumpToKline(scope.row.code)"
                >
                  {{ scope.row.code }}<br/>{{ scope.row.name }}
                </el-link>
              </template>
            </el-table-column>
          </el-table></template
        >
      </el-table-column>
      <el-table-column prop="cjsd_9" label="超级赛道9">
        <template #default="scope">
          <el-table :data="scope.row.cjsd_9.codes">
            <el-table-column prop="name" :label="scope.row.cjsd_9.name">
              <template #default="scope">
                <el-link
                  type="primary"
                  :underline="false"
                  @click="jumpToKline(scope.row.code)"
                >
                  {{ scope.row.code }}<br/>{{ scope.row.name }}
                </el-link>
              </template>
            </el-table-column>
          </el-table></template
        >
      </el-table-column>
      <el-table-column prop="cjsd_10" label="超级赛道10">
        <template #default="scope">
          <el-table :data="scope.row.cjsd_10.codes">
            <el-table-column prop="name" :label="scope.row.cjsd_10.name">
              <template #default="scope">
                <el-link
                  type="primary"
                  :underline="false"
                  @click="jumpToKline(scope.row.code)"
                >
                  {{ scope.row.code }}<br/>{{ scope.row.name }}
                </el-link>
              </template>
            </el-table-column>
          </el-table></template
        >
      </el-table-column>
          </el-table>
        </div>
        <el-row class="stock-cjsd-panel__pager">
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
        </el-row>
      </section>
    </div>
  </div>
</template>

<script>
import { stockApi } from '@/api/stockApi'
import CommonTool from '@/tool/CommonTool'
import MyHeader from '../views/MyHeader.vue'
import _ from 'lodash'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { reactive } from 'vue'

export default {
  name: 'StockPools',
  components: {
    MyHeader
  },
  data () {
    return {}
  },
  setup () {
    const listQuery = reactive({
      size: 10,
      total: 0,
      current: 1
    })
    const { isLoading, data: cjsdList } = useQuery({
      queryKey: ['cjsdList'],
      queryFn: async () => {
        const cjsdList = await stockApi.getCjsdList({
          page: 1,
          size: 1000
        })
        listQuery.total = _.size(cjsdList)
        const start = (listQuery.current - 1) * listQuery.size
        const end = start + listQuery.size
        return _.slice(cjsdList, start, end)
      },
      refetchInterval: 600000,
      staleTime: 5000
    })
    const queryClient = useQueryClient()
    return { isLoading, cjsdList, listQuery, queryClient }
  },
  methods: {
    handleSizeChange (currentSize) {
      this.listQuery.size = currentSize
      this.queryClient.invalidateQueries({ queryKey: ['cjsdList'] })
    },
    handlePageChange (currentPage) {
      this.listQuery.current = currentPage
      this.queryClient.invalidateQueries({ queryKey: ['cjsdList'] })
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
    }
  }
}
</script>
<style lang="stylus" scoped>
.stock-cjsd-shell
  display flex
  flex-direction column
  height 100vh
  height 100dvh
  overflow hidden
  background #f5f7fa

.stock-cjsd-body
  flex 1 1 auto
  min-height 0
  overflow hidden
  padding 12px 16px 16px

.stock-cjsd-panel
  display flex
  flex-direction column
  min-height 0
  height 100%
  overflow hidden
  padding 0 12px 12px
  border 1px solid #ebeef5
  border-radius 8px
  background #fff

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
