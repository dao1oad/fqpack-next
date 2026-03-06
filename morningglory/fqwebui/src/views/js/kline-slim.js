import * as echarts from 'echarts'

import { futureApi } from '@/api/futureApi'

import drawSlim from './draw-slim'
import echartsConfig from './echartsConfig'

const MAIN_PERIODS = ['1m', '5m', '15m', '30m']
const DEFAULT_PERIOD = '5m'
const OVERLAY_PERIOD = '30m'
const MAIN_POLL_MS = 5000
const OVERLAY_POLL_MS = 15000

function buildVersion(data) {
  if (!data || !Array.isArray(data.date)) {
    return ''
  }
  const dateList = data.date
  const lastDate = dateList.length ? dateList[dateList.length - 1] : ''
  const updatedAt = data._bar_time ?? data.updated_at ?? data.dt ?? ''
  return `${dateList.length}_${lastDate}_${updatedAt}`
}

function getRoutePeriod(route) {
  const period = route?.query?.period || DEFAULT_PERIOD
  return MAIN_PERIODS.includes(period) ? period : DEFAULT_PERIOD
}

export default {
  name: 'kline-slim',
  data() {
    return {
      chart: null,
      symbolInput: '',
      endDateModel: '',
      currentPeriod: DEFAULT_PERIOD,
      overlayPeriod: OVERLAY_PERIOD,
      mainData: null,
      overlayData: null,
      mainTimer: null,
      overlayTimer: null,
      renderFrameId: 0,
      routeToken: 0,
      mainLoading: false,
      overlayLoading: false,
      mainVersion: '',
      overlayVersion: '',
      lastRenderedVersion: '',
      lastMainBarLabel: '--',
      lastOverlayBarLabel: '--',
      lastError: '',
      resetChartStateOnNextRender: true,
      periodList: MAIN_PERIODS
    }
  },
  computed: {
    routeSymbol() {
      return (this.$route.query.symbol || '').trim()
    },
    isRealtimeMode() {
      return !this.endDateModel
    },
    statusText() {
      if (this.lastError) {
        return this.lastError
      }
      return this.isRealtimeMode ? '轮询中' : '历史模式'
    }
  },
  watch: {
    '$route.fullPath': {
      immediate: true,
      handler() {
        this.handleRouteChange()
      }
    }
  },
  mounted() {
    this.initChart()
    this.scheduleRender()
    document.addEventListener('visibilitychange', this.handleVisibilityChange)
    window.addEventListener('resize', this.handleResize)
  },
  beforeUnmount() {
    document.removeEventListener('visibilitychange', this.handleVisibilityChange)
    window.removeEventListener('resize', this.handleResize)
    this.stopPolling()
    if (this.renderFrameId) {
      window.cancelAnimationFrame(this.renderFrameId)
      this.renderFrameId = 0
    }
    if (this.chart) {
      this.chart.dispose()
      this.chart = null
    }
  },
  methods: {
    initChart() {
      const chartDom = this.$refs.chartHost
      if (!chartDom || this.chart) {
        return
      }
      this.chart = echarts.init(chartDom, 'dark')
      this.chart.showLoading(echartsConfig.loadingOption)
    },
    handleResize() {
      if (this.chart) {
        this.chart.resize()
      }
    },
    handleVisibilityChange() {
      if (document.visibilityState === 'visible') {
        this.handleRouteChange()
        return
      }
      this.stopPolling()
    },
    handleRouteChange() {
      this.currentPeriod = getRoutePeriod(this.$route)
      this.symbolInput = this.routeSymbol
      this.endDateModel = this.$route.query.endDate || ''

      if (!this.$route.query.period) {
        this.$router.replace({
          path: '/kline-slim',
          query: {
            ...this.$route.query,
            period: DEFAULT_PERIOD
          }
        })
        return
      }

      this.routeToken += 1
      this.lastError = ''
      this.lastRenderedVersion = ''
      this.mainVersion = ''
      this.overlayVersion = ''
      this.mainData = null
      this.overlayData = null
      this.lastMainBarLabel = '--'
      this.lastOverlayBarLabel = '--'
      this.resetChartStateOnNextRender = true
      this.stopPolling()

      if (this.chart && this.routeSymbol) {
        this.chart.showLoading(echartsConfig.loadingOption)
      }

      if (!this.routeSymbol) {
        if (this.chart) {
          this.chart.clear()
          this.chart.hideLoading()
        }
        return
      }

      this.fetchMainData(this.routeToken)
      this.fetchOverlayData(this.routeToken)
      if (this.isRealtimeMode && document.visibilityState === 'visible') {
        this.mainTimer = window.setInterval(
          () => this.fetchMainData(this.routeToken),
          MAIN_POLL_MS
        )
        this.overlayTimer = window.setInterval(
          () => this.fetchOverlayData(this.routeToken),
          OVERLAY_POLL_MS
        )
      }
    },
    stopPolling() {
      if (this.mainTimer) {
        window.clearInterval(this.mainTimer)
        this.mainTimer = null
      }
      if (this.overlayTimer) {
        window.clearInterval(this.overlayTimer)
        this.overlayTimer = null
      }
    },
    async fetchMainData(token) {
      if (this.mainLoading || !this.routeSymbol) {
        return
      }
      this.mainLoading = true
      try {
        const payload = await futureApi.stockData({
          symbol: this.routeSymbol,
          period: this.currentPeriod,
          endDate: this.endDateModel || undefined
        })
        if (token !== this.routeToken || !payload) {
          return
        }
        const nextVersion = buildVersion(payload)
        if (!nextVersion) {
          return
        }
        this.mainData = payload
        this.mainVersion = nextVersion
        this.lastMainBarLabel = payload.date[payload.date.length - 1]
        this.scheduleRender()
      } catch (error) {
        if (token === this.routeToken) {
          this.lastError = '主图刷新失败'
        }
      } finally {
        this.mainLoading = false
      }
    },
    async fetchOverlayData(token) {
      if (
        this.overlayLoading ||
        !this.routeSymbol ||
        this.currentPeriod === this.overlayPeriod
      ) {
        if (this.currentPeriod === this.overlayPeriod) {
          this.overlayData = null
          this.overlayVersion = ''
          this.lastOverlayBarLabel = '--'
          this.scheduleRender()
        }
        return
      }
      this.overlayLoading = true
      try {
        const payload = await futureApi.stockData({
          symbol: this.routeSymbol,
          period: this.overlayPeriod,
          endDate: this.endDateModel || undefined
        })
        if (token !== this.routeToken || !payload) {
          return
        }
        const nextVersion = buildVersion(payload)
        if (!nextVersion) {
          return
        }
        this.overlayData = payload
        this.overlayVersion = nextVersion
        this.lastOverlayBarLabel = payload.date[payload.date.length - 1]
        this.scheduleRender()
      } catch (error) {
        if (token === this.routeToken) {
          this.lastError = '叠加结构刷新失败'
        }
      } finally {
        this.overlayLoading = false
      }
    },
    scheduleRender() {
      if (!this.chart || !this.mainData) {
        return
      }
      if (this.renderFrameId) {
        window.cancelAnimationFrame(this.renderFrameId)
      }

      this.renderFrameId = window.requestAnimationFrame(() => {
        this.renderFrameId = 0
        const combinedVersion = `${this.mainVersion}__${this.overlayVersion}`
        if (
          combinedVersion === this.lastRenderedVersion &&
          !this.resetChartStateOnNextRender
        ) {
          return
        }

        const nextVersion = drawSlim(this.chart, this.mainData, this.currentPeriod, {
          overlayPeriod: this.overlayPeriod,
          extraChanlunMap: this.overlayData
            ? { [this.overlayPeriod]: this.overlayData }
            : {},
          keepState: !this.resetChartStateOnNextRender
        })
        this.lastRenderedVersion = nextVersion || combinedVersion
        this.resetChartStateOnNextRender = false
      })
    },
    applySymbol() {
      const symbol = (this.symbolInput || '').trim()
      if (!symbol) {
        return
      }
      this.$router.replace({
        path: '/kline-slim',
        query: {
          ...this.$route.query,
          symbol,
          period: this.currentPeriod
        }
      })
    },
    applyEndDate(value) {
      const nextQuery = {
        ...this.$route.query,
        symbol: this.routeSymbol,
        period: this.currentPeriod
      }
      if (value) {
        nextQuery.endDate = value
      } else {
        delete nextQuery.endDate
      }
      this.$router.replace({
        path: '/kline-slim',
        query: nextQuery
      })
    },
    switchPeriod(period) {
      if (!MAIN_PERIODS.includes(period)) {
        return
      }
      this.$router.replace({
        path: '/kline-slim',
        query: {
          ...this.$route.query,
          symbol: this.routeSymbol,
          period
        }
      })
    },
    reloadNow() {
      if (!this.routeSymbol) {
        return
      }
      this.fetchMainData(this.routeToken)
      this.fetchOverlayData(this.routeToken)
    },
    jumpToControl() {
      this.$router.replace('/stock-control')
    },
    jumpToBigChart() {
      if (!this.routeSymbol) {
        return
      }
      this.$router.push({
        path: '/kline-big',
        query: {
          symbol: this.routeSymbol,
          period: this.currentPeriod,
          ...(this.endDateModel ? { endDate: this.endDateModel } : {})
        }
      })
    }
  }
}
