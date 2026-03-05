<template>
  <div>
    <MyHeader></MyHeader>
    <el-row>
      <el-col :span="12">
        <!-- 持仓股 -->
        <StockPositionList />
        <SignalList title="候选股信号" category="candidates" />
      </el-col>
      <el-col :span="12">
        <!-- 持仓股信号 -->
        <SignalList title="持仓股信号" category="holdings" />
      </el-col>
    </el-row>
  </div>
</template>

<script>
import { stockApi } from '@/api/stockApi'
import CommonTool from '@/tool/CommonTool'
import MyHeader from '@/views/MyHeader.vue'
import StockPositionList from '@/views/StockPositionList.vue'
import SignalList from '@/views/SignalList.vue'

export default {
  name: 'stock-control',
  components: {
    MyHeader,
    StockPositionList,
    SignalList
  },
  data () {
    return {
      loading: true,
      signalList: [],
      periodList: ['3m', '5m', '15m', '30m', '60m'],
      beichiList: {},
      percentage: 80
    }
  },
  mounted () {
    const page = this.getParams('page') || '1'
    this.getSignalList(page)
    setInterval(() => this.getSignalList(page), 60000)
  },
  beforeUnmount () {},
  methods: {
    jumpToControl (type) {
      if (type === 'futures') {
        this.$router.replace('/futures-control')
      } else {
        this.$router.replace('/stock-control')
      }
    },
    filterTags (value, row) {
      return row.tags === value
    },
    filterPeriod (value, row) {
      return row.period === value
    },
    filterRemark (value, row) {
      return row.remark === value
    },
    getSignalList (page) {
      stockApi
        .getStockSignalList(page)
        .then(res => {
          this.signalList = res
          this.loading = false
        })
        .catch(error => {
          this.loading = false
          console.log('获取股票信号列表失败:', error)
        })
        .finally(() => {})
    },
    jumpToKline (symbol, period) {
      // 总控页面不关闭，开启新页面
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
    getParams (name) {
      let res = ''
      const categoryStr = window.location.href.split('?')[1] || ''
      if (categoryStr.length > 1) {
        const arr = categoryStr.split('&')
        for (let i = 0, len = arr.length; i < len; i++) {
          const pair = arr[i]
          const key = pair.split('=')[0]
          const value = pair.split('=')[1]

          if (key === name) {
            res = value
            console.log('coinName', res)
            break
          }
        }
      }
      return res
    }
  }
}
</script>
<style lang="stylus" scoped>
@import '../style/stock-control.styl';
</style>
