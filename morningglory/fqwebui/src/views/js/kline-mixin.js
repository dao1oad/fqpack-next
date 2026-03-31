import { futureApi } from '@/api/futureApi'
import { stockApi } from '@/api/stockApi'
import KlineHeader from '../KlineHeader.vue'
import manba from 'manba'
import queryParamTool from '@/tool/queryParamTool'
import symbolTool from '@/tool/symbolTool'
import initEcharts from './initEcharts'
import chartTool from '@/tool/chartTool'
import echartsConfig from './echartsConfig'

// 导入图标资源（Vite 使用 ES Module）
import icon1min from '@/assets/img/icon_1min.png'
import icon3min from '@/assets/img/icon_3min.png'
import icon5min from '@/assets/img/icon_5min.png'
import icon15min from '@/assets/img/icon_15min.png'
import icon30min from '@/assets/img/icon_30min.png'
import icon1h from '@/assets/img/icon_1h.png'
import icon4h from '@/assets/img/icon_4h.png'
import icon1d from '@/assets/img/icon_1d.png'
import icon1w from '@/assets/img/icon_1w.png'
import iconRefresh from '@/assets/img/icon_refresh.svg'
import bigKline from '@/assets/img/big-kline.png'
import {
  futureAccount,
  globalFutureAccount,
  digitCoinAccount,
  maxAccountUseRate,
  stopRate,
  digitCoinLevel,
  globalFutureSymbol
} from '@/config/tradingConstants.mjs'

export default {
  components: {
    KlineHeader
  },
  data () {
    return {
      showPeriodList: false,
      dataTitle: '主标题',
      dataSubTitle: '副标题',
      periodIcons: [
        icon1min,
        icon3min,
        icon5min,
        icon15min,
        icon30min,
        icon1h,
        icon4h,
        icon1d,
        icon1w,
        iconRefresh,
        bigKline
      ],

      futureSymbolList: [],
      futureSymbolMap: {},
      // 不同期货公司提高的点数不一样 ,华安是在基础上加1%
      marginLevelCompany: 0.01,
      marginPrice: 0, // 每手需要的保证金

      currentMarginRate: null,
      marginLevel: 1,
      // 合约乘数
      contractMultiplier: 1,
      // 账户总额
      account: 0,
      // 期货账户总额
      futureAccount: futureAccount,
      globalFutureAccount: globalFutureAccount,
      // 数字货币账户总额
      digitCoinAccount: digitCoinAccount,
      // 开仓价格
      openPrice: null,
      // 止损价格
      stopPrice: null,
      // 开仓手数
      maxOrderCount: null,
      // 资金使用率
      accountUseRate: null,
      // 最大资金使用率
      maxAccountUseRate: maxAccountUseRate,
      // 止损系数
      stopRate: stopRate,
      // 数字货币手续费 20倍杠杆 双向 0.05%*2
      digitCoinFee: 0.001,
      // okex 开仓起始杠杆
      digitCoinLevel: digitCoinLevel,
      // 1手需要的保证金
      perOrderMargin: 0,
      // 1手止损金额
      perOrderStopMoney: 0,
      // 1手止损百分比
      perOrderStopRate: 0,
      // 总保证金
      totalOrderMargin: 0,
      // 总止损额
      totalOrderStopMoney: 0,

      // 动态止盈价格(动态止盈部分手数使剩下的止损也不亏钱)
      // dynamicWinPrice: null,
      // 动态止盈手数
      // dynamicWinCount: 0,
      // end仓位管理计算

      // 选中的品种
      selectedSymbol: '',
      // 输入的交割过的期货品种 或者 股票品种
      periodList: ['1m', '3m', '5m', '15m', '30m', '60m', '90m', '120m', '1d'],
      // 是否指显示当前持仓的开平动止
      isPosition: false,
      // 当前品种持仓信息
      currentPosition: null,
      positionStatus: 'holding',
      positionDirection: '',
      dynamicDirectionMap: { long: '多', short: '空', close: '平' },
      currentInfo: null,
      // 数字货币 和外盘 将180m 替换成1m
      isShow1Min: false,
      futureConfig: {},
      symbolInfo: null,
      show1MinSymbol: ['BTC'],
      globalFutureSymbol: globalFutureSymbol,
      //    快速计算开仓手数
      quickCalc: {
        openPrice: '',
        stopPrice: '',
        dynamicWinPrice: '',
        dynamicWinCount: '',
        count: 0,
        stopRate: 0,
        perOrderStopMoney: 0
      }
    }
  },
  mounted () {
    const { ...query } = this.$route.query
    if (this.view === 'klineBig' && !query.period) {
      query.period = this.periodList[0]
      this.$router.replace({ query })
    }
    Object.assign(this.query, query)
    // 不共用symbol对象, symbol是双向绑定的
    this.$refs.klineHeader.setELDatePicker(query.endDate)
    if (this.isPosition === 'true') {
      const { positionPeriod, positionDirection, positionStatus } = queryParamTool.getLocationQueryParams()
      this.positionPeriod = positionPeriod
      this.positionDirection = positionDirection
      this.positionStatus = positionStatus
      if (symbolTool.isStock(query.symbol)) {
        this.getStockPosition()
      } else {
        this.getFutruePosition()
      }
    }
    initEcharts(this)
    // 取出本地缓存
    const futureConfig = window.localStorage.getItem('futureConfig')
    // 本地缓存有合约配置数据
    if (futureConfig != null) {
      this.futureConfig = JSON.parse(futureConfig)
    } else {
      // 新设备 直接进入大图页面 先获取合约配置数据
      this.getFutureConfig()
    }
    // 快速选择主力合约
    const futureSymbolList = window.localStorage.getItem('symbolList')
    if (futureSymbolList != null) {
      this.futureSymbolList = JSON.parse(futureSymbolList)
    } else {
      // 新设备 直接进入大图页面 先获取合约配置数据
      this.getDominantSymbol()
    }
  },
  methods: {
    getDominantSymbol () {
      futureApi
        .getDominant()
        .then(res => {
          this.futureSymbolList = res
          window.localStorage.setItem(
            'symbolList',
            JSON.stringify(this.futureSymbolList)
          )
        })
        .catch(() => {
          this.futureSymbolList = []
        })
    },
    quickSwitchSymbol (symbol) {
      this.switchSymbol(symbol)
      this.processMargin()
    },
    quickSwitchDay (type) {
      const { ...query } = this.$route.query
      if (type === 'pre') {
        query.endDate = manba(query.endDate).add(-1, manba.DAY).format('YYYY-MM-DD')
      } else {
        query.endDate = manba(query.endDate).add(1, manba.DAY).format('YYYY-MM-DD')
      }
      Object.assign(this.query, query)
      this.$router.push({ query })
      this.$refs.klineHeader.setELDatePicker(query.endDate)
      this.myChart.showLoading(echartsConfig.loadingOption)
      this.queryClient.invalidateQueries({ queryKey: ['klineData'] })
    },
    getFutruePosition () {
      const query = this.$route.query
      futureApi
        .getPosition(
          query.symbol,
          this.positionPeriod,
          this.positionStatus,
          this.positionDirection
        )
        .then(res => {
          this.currentPosition = res
        })
        .catch(() => {
          this.currentPosition = null
        })
    },
    getStockPosition () {
      const period = 'all'
      const query = this.$route.query
      stockApi
        .getPosition(query.symbol, period, this.positionStatus)
        .then(res => {
          this.currentPosition = res
        })
        .catch(() => {
          this.currentPosition = null
        })
    },
    jumpToMultiPeriod () {
      const query = this.$route.query
      if (this.isPosition === 'true') {
        this.$router.push({
          path: '/multi-period',
          query: {
            symbol: query.symbol,
            isPosition: 'true',
            endDate: query.endDate,
            positionPeriod: this.positionPeriod,
            positionDirection: this.positionDirection,
            positionStatus: this.positionStatus
          }
        })
      } else {
        this.$router.push({
          path: '/multi-period',
          query: {
            symbol: query.symbol,
            endDate: query.endDate
          }
        })
        this.queryClient.invalidateQueries({ queryKey: ['klineData1Min'] })
        this.queryClient.invalidateQueries({ queryKey: ['klineData5Min'] })
        this.queryClient.invalidateQueries({ queryKey: ['klineData15Min'] })
        this.queryClient.invalidateQueries({ queryKey: ['klineData30Min'] })
        this.queryClient.invalidateQueries({ queryKey: ['klineData60Min'] })
        this.queryClient.invalidateQueries({ queryKey: ['klineData1D'] })
      }
    },
    jumpToKlineBig (period) {
      const query = this.$route.query
      if (this.isPosition === 'true') {
        if (period !== this.positionPeriod) {
          return
        }
        this.$router.push({
          path: '/kline-big',
          query: {
            symbol: query.symbol,
            period,
            isPosition: 'true',
            endDate: query.endDate,
            positionPeriod: this.positionPeriod,
            positionDirection: this.positionDirection,
            positionStatus: this.positionStatus
          }
        })
      } else {
        this.$router.push({
          path: '/kline-big',
          query: {
            symbol: query.symbol,
            period,
            endDate: query.endDate
          }
        })
        this.queryClient.invalidateQueries({ queryKey: ['klineData'] })
      }
    },

    jumpToControl (type) {
      if (type === 'futures') {
        this.$router.replace('/futures-control')
      } else {
        this.$router.replace('/stock-control')
      }
    },
    changeDate (val) {
      const { ...query } = this.$route.query
      query.endDate = val
      Object.assign(this.query, query)
      this.$router.push({ query })
      this.myChart.showLoading(echartsConfig.loadingOption)
      this.queryClient.invalidateQueries({ queryKey: ['klineData'] })
    },
    submitSymbol (val) {
      this.switchSymbol(val)
      this.processMargin()
    },
    processMargin () {
      const query = this.$route.query
      if (!query.symbol) {
        this.symbolInfo = null
        this.currentMarginRate = null
        this.marginLevel = 1
        this.contractMultiplier = 1
        return
      }
      // 获取当前品种的合约 保证金率
      if (query.symbol === 'BTC') {
        // BTC
        this.symbolInfo = this.futureConfig[query.symbol]
        this.currentMarginRate = this.symbolInfo.margin_rate
        this.marginLevel = 1 / this.currentMarginRate
        this.contractMultiplier = 1
      } else if (
        query.symbol.indexOf('sz') !== -1 ||
        query.symbol.indexOf('sh') !== -1
      ) {
        this.currentMarginRate = 1
        this.marginLevel = 1
        this.contractMultiplier = 1
      } else if (this.globalFutureSymbol.indexOf(query.symbol) !== -1) {
        // 外盘
        this.symbolInfo = this.futureConfig[query.symbol]
        this.currentMarginRate = this.symbolInfo.margin_rate
        this.marginLevel = Number((1 / this.currentMarginRate).toFixed(2))
        this.contractMultiplier = this.symbolInfo.contract_multiplier
      } else {
        // 内盘 期货简单代码   RB
        const simpleSymbol = query.symbol.replace(/[0-9]/g, '')
        this.symbolInfo = this.futureConfig[simpleSymbol]
        if (this.symbolInfo) {
          const margin_rate = this.symbolInfo.margin_rate
          this.currentMarginRate = margin_rate + this.marginLevelCompany
          this.marginLevel = Number((1 / this.currentMarginRate).toFixed(2))
          this.contractMultiplier = this.symbolInfo.contract_multiplier
        }
      }
    },
    getFutureConfig () {
      futureApi
        .getFutureConfig()
        .then(res => {
          this.futureConfig = res
          window.localStorage.setItem(
            'symbolConfig',
            JSON.stringify(this.futureConfig)
          )
          this.processMargin()
        })
        .catch(() => {
          this.futureConfig = {}
        })
    },
    switchPeriod (period) {
      const { ...query } = this.$route.query
      query.period = period
      Object.assign(this.query, query)
      this.$router.push({ query })
      this.myChart.showLoading(echartsConfig.loadingOption)
      this.queryClient.invalidateQueries({ queryKey: ['klineData'] })
    },
    switchSymbol (symbol) {
      const { ...query } = this.$route.query
      query.symbol = symbol
      Object.assign(this.query, query)
      this.$router.push({ query })
      if (query.period) {
        document.title = `${symbol}-${query.period}`
      } else {
        document.title = symbol
      }
      // 如果是大图，只请求一个周期的数据
      if (query.period) {
        this.myChart.showLoading(echartsConfig.loadingOption)
        this.queryClient.invalidateQueries({ queryKey: ['klineData'] })
      } else {
        chartTool.currentChartGet(this, '1m').showLoading(echartsConfig.loadingOption)
        this.queryClient.invalidateQueries({ queryKey: ['klineData1Min'] })
        chartTool.currentChartGet(this, '5m').showLoading(echartsConfig.loadingOption)
        this.queryClient.invalidateQueries({ queryKey: ['klineData5Min'] })
        chartTool.currentChartGet(this, '15m').showLoading(echartsConfig.loadingOption)
        this.queryClient.invalidateQueries({ queryKey: ['klineData15Min'] })
        chartTool.currentChartGet(this, '30m').showLoading(echartsConfig.loadingOption)
        this.queryClient.invalidateQueries({ queryKey: ['klineData30Min'] })
        chartTool.currentChartGet(this, '60m').showLoading(echartsConfig.loadingOption)
        this.queryClient.invalidateQueries({ queryKey: ['klineData60Min'] })
        chartTool.currentChartGet(this, '1d').showLoading(echartsConfig.loadingOption)
        this.queryClient.invalidateQueries({ queryKey: ['klineData1D'] })
      }
    },
    quickCalcMaxCount () {
      this.calcAccount(this.quickCalc.openPrice, this.quickCalc.stopPrice)

      // 计算动态止盈手数， 即剩下仓位被止损也不会亏钱
      // 动止手数 * （动止价-开仓价）* 合约乘数 = （开仓手数-动止手数）* 1手止损
      // 动止手数  = 开仓手数 * 1手止损  /( （动止价-开仓价）* 合约乘数 + 1手止损)
      // 如果填入了动止价
      if (this.quickCalc.dynamicWinPrice !== '') {
        this.quickCalc.dynamicWinCount = Math.ceil(
          (this.maxOrderCount * this.perOrderStopMoney) /
            (Math.abs(
              this.quickCalc.dynamicWinPrice - this.quickCalc.openPrice
            ) *
              this.contractMultiplier +
              this.perOrderStopMoney)
        )
      }
      this.quickCalc.count = this.maxOrderCount
      this.quickCalc.stopRate = this.perOrderStopRate
      this.quickCalc.perOrderStopMoney = Math.round(this.perOrderStopMoney, 0)
    },
    // 计算开仓手数
    calcAccount (openPrice, stopPrice, period) {
      const query = this.$route.query
      if (this.currentMarginRate == null) {
        // alert('请选择保证金系数，开仓价，止损价')
        return
      }
      if (query.symbol.indexOf('BTC') !== -1) {
        this.account = this.digitCoinAccount
        // 火币1张就是100usd  20倍杠杠 1张保证金是5usd
        // OKEX 1张 = 0.01BTC  20倍杠杆， 1张就是 0.01* BTC的现价
        // 单位usdt
        this.perOrderMargin = (0.01 * this.currentPrice) / 20
        this.perOrderStopRate = (
          (Math.abs(openPrice - stopPrice) / openPrice + this.digitCoinFee) *
          20
        ).toFixed(2)
        // 1手止损的百分比 需要加上手续费  0.05%  okex双向taker 就是 2%
        this.perOrderStopMoney = Number(
          (this.perOrderMargin * this.perOrderStopRate).toFixed(2)
        )
        this.maxAccountUseRate = 0.4
        this.stopRate = 0.1
      } else if (this.globalFutureSymbol.indexOf(query.symbol) !== -1) {
        // 外盘
        this.account = this.globalFutureAccount
        // 计算1手需要的保证金
        this.perOrderMargin = Math.floor(
          openPrice * this.contractMultiplier * this.currentMarginRate
        )
        this.perOrderStopMoney =
          Math.abs(openPrice - stopPrice) * this.contractMultiplier
        // 1手止损的百分比
        this.perOrderStopRate = (
          this.perOrderStopMoney / this.perOrderMargin
        ).toFixed(2)
        this.maxAccountUseRate = 0.25
        this.stopRate = 0.02
      } else {
        // 内盘
        this.account = this.futureAccount
        // 计算1手需要的保证金
        this.perOrderMargin = Math.floor(
          openPrice * this.contractMultiplier * this.currentMarginRate
        )
        this.perOrderStopMoney =
          Math.abs(openPrice - stopPrice) * this.contractMultiplier
        // 1手止损的百分比
        this.perOrderStopRate = (
          this.perOrderStopMoney / this.perOrderMargin
        ).toFixed(2)
        this.maxAccountUseRate = maxAccountUseRate
        this.stopRate = stopRate
      }

      // 计算最大能使用的资金
      const maxAccountUse = this.account * 10000 * this.maxAccountUseRate
      // 计算最大止损金额
      const maxStopMoney = this.account * 10000 * this.stopRate
      // 1手止损的金额

      // 根据止损算出的开仓手数(四舍五入)
      const maxOrderCount1 = Math.round(maxStopMoney / this.perOrderStopMoney)

      // 根据最大资金使用率算出的开仓手数(四舍五入)
      const maxOrderCount2 = Math.round(maxAccountUse / this.perOrderMargin)

      this.maxOrderCount =
        maxOrderCount1 > maxOrderCount2 ? maxOrderCount2 : maxOrderCount1
      // 总保证金
      this.totalOrderMargin = this.perOrderMargin * this.maxOrderCount

      // 总止损额
      this.totalOrderStopMoney = this.perOrderStopMoney * this.maxOrderCount

      // 计算当前资金使用率
      this.accountUseRate = (
        (this.maxOrderCount * this.perOrderMargin) /
        this.account /
        10000
      ).toFixed(2)
    }
  }
}
