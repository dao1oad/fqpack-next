import * as echarts from 'echarts'

import { futureApi } from '@/api/futureApi'
import { getGanttStockReasons } from '@/api/ganttApi'
import { stockApi } from '@/api/stockApi'
import { subjectManagementApi } from '@/api/subjectManagementApi'

import echartsConfig from './echartsConfig'
import { createKlineSlimChartController, createKlineSlimViewportState } from './kline-slim-chart-controller.mjs'
import { buildKlineSlimChartScene } from './kline-slim-chart-renderer.mjs'
import {
  buildInitialKlineSlimPricePanelState,
  clearSubjectPriceDetailState,
  createKlineSlimPricePanelActions,
  loadSubjectPriceDetail as loadSubjectPriceDetailState,
  resetSubjectPriceDetailState,
  saveGuardianPriceGuides,
  saveTakeprofitPriceGuides,
} from './kline-slim-price-panel.mjs'
import {
  buildResolvedKlineSlimQuery,
  canApplyResolvedKlineSlimRoute,
  getKlineSlimEmptyMessage,
  pickFirstHoldingSymbol,
  shouldResolveDefaultSymbol
} from './kline-slim-default-symbol.mjs'
import {
  buildSidebarSections,
  getSidebarDeleteBehavior,
  getReasonPanelMessage,
  getSidebarCode6,
  normalizeReasonItems,
  toggleSidebarExpandedKey
} from './kline-slim-sidebar.mjs'
import {
  SUPPORTED_CHANLUN_PERIODS,
  DEFAULT_MAIN_PERIOD,
  DEFAULT_VISIBLE_CHANLUN_PERIODS,
  buildPeriodLegendSelectionState,
  getVisibleChanlunPeriods,
  getRealtimeRefreshPeriods,
  normalizeChanlunPeriod
} from './kline-slim-chanlun-periods.mjs'
import { buildPriceGuideLegendSelectionState } from './subject-price-guides.mjs'

const MAIN_PERIODS = SUPPORTED_CHANLUN_PERIODS
const DEFAULT_PERIOD = DEFAULT_MAIN_PERIOD
const CHANLUN_POLL_MS = 15000
const DEFAULT_KLINE_SLIM_BAR_COUNT = 20000
const CHANLUN_SOURCE_LABELS = {
  realtime_cache_fullcalc: '实时 fullcalc',
  history_fullcalc: '历史 fullcalc',
  fallback_fullcalc: '实时回退 fullcalc'
}
const GUARDIAN_GUIDE_META = [
  { key: 'buy_1', label: 'BUY-1', shortLabel: 'B1', tone: 'blue', lineLabel: '蓝线' },
  { key: 'buy_2', label: 'BUY-2', shortLabel: 'B2', tone: 'red', lineLabel: '红线' },
  { key: 'buy_3', label: 'BUY-3', shortLabel: 'B3', tone: 'green', lineLabel: '绿线' }
]
const TAKEPROFIT_GUIDE_META = [
  { level: 1, label: 'L1', tone: 'blue', lineLabel: '蓝线' },
  { level: 2, label: 'L2', tone: 'red', lineLabel: '红线' },
  { level: 3, label: 'L3', tone: 'green', lineLabel: '绿线' }
]

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
  return normalizeChanlunPeriod(route?.query?.period || DEFAULT_PERIOD)
}

function formatDirectionLabel(value) {
  if (value === 'up') {
    return '上'
  }
  if (value === 'down') {
    return '下'
  }
  return '--'
}

function formatPriceValue(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) {
    return '--'
  }
  return number.toFixed(2)
}

function formatPercentValue(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) {
    return '--'
  }
  return `${number.toFixed(2)}%`
}

function buildChanlunTimePriceValue(item, timeKey, priceKey) {
  const time = item?.[timeKey] || '--'
  const price = formatPriceValue(item?.[priceKey])
  return `${time} (${price})`
}

function computeChanlunBiBarCount(item) {
  const start = Number(item?.start_idx)
  const end = Number(item?.end_idx)
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) {
    return '--'
  }
  return String(end - start + 1)
}

function buildChanlunSummaryItems({ item, fields }) {
  if (!item) {
    return null
  }
  return fields.map((field) => ({
    label: field.label,
    value: field.value
  }))
}

function isTakeprofitArmedLevel(state, level) {
  const armedLevels = state?.armed_levels || {}
  return armedLevels[String(level)] !== false && armedLevels[level] !== false
}

export default {
  name: 'kline-slim',
  data() {
    return {
      chart: null,
      chartController: null,
      chartViewport: createKlineSlimViewportState(),
      symbolInput: '',
      endDateModel: '',
      currentPeriod: DEFAULT_PERIOD,
      mainData: null,
      chanlunRefreshTimer: null,
      renderFrameId: 0,
      routeToken: 0,
      mainLoading: false,
      mainVersion: '',
      chanlunVersionMap: {},
      lastRenderedVersion: '',
      lastMainBarLabel: '--',
      lastError: '',
      resolvingDefaultSymbol: false,
      defaultSymbolResolveError: '',
      resetViewportOnNextRender: true,
      periodList: MAIN_PERIODS,
      chanlunMultiData: {},
      visibleChanlunPeriods: [...DEFAULT_VISIBLE_CHANLUN_PERIODS],
      loadedChanlunPeriods: [],
      chanlunPeriodLoading: {},
      periodLegendSelected: buildPeriodLegendSelectionState({
        currentPeriod: DEFAULT_PERIOD
      }),
      priceGuideLegendSelected: buildPriceGuideLegendSelectionState(),
      holdings: [],
      mustPools: [],
      stockPools: [],
      prePools: [],
      sidebarLoading: {
        holding: false,
        must_pool: false,
        stock_pools: false,
        stock_pre_pools: false
      },
      sidebarErrors: {
        holding: '',
        must_pool: '',
        stock_pools: '',
        stock_pre_pools: ''
      },
      expandedSidebarKey: 'holding',
      sidebarDeleting: {},
      reasonCache: {},
      reasonLoading: {},
      reasonError: {},
      showChanlunStructurePanel: false,
      chanlunStructureLoading: false,
      chanlunStructureError: '',
      chanlunStructureRefreshError: '',
      chanlunStructureData: null,
      ...buildInitialKlineSlimPricePanelState()
    }
  },
  computed: {
    routeSymbol() {
      return (this.$route.query.symbol || '').trim()
    },
    activeCode6() {
      return getSidebarCode6({ symbol: this.routeSymbol, code: this.routeSymbol })
    },
    isRealtimeMode() {
      return !this.endDateModel
    },
    sidebarSections() {
      return buildSidebarSections({
        holdings: this.holdings,
        mustPools: this.mustPools,
        stockPools: this.stockPools,
        prePools: this.prePools,
        expandedKey: this.expandedSidebarKey
      }).map((section) => ({
        ...section,
        loading: !!this.sidebarLoading[section.key],
        error: this.sidebarErrors[section.key] || ''
      }))
    },
    guardianGuideRows() {
      const buyActive = Array.isArray(this.guardianState?.buy_active)
        ? this.guardianState.buy_active
        : [true, true, true]
      const buyEnabled = Array.isArray(this.guardianDraft?.buy_enabled)
        ? this.guardianDraft.buy_enabled
        : [true, true, true]
      return GUARDIAN_GUIDE_META.map((item, index) => ({
        ...item,
        index,
        price: this.guardianDraft?.[item.key] ?? null,
        manual_enabled: buyEnabled[index] !== false,
        active: buyEnabled[index] !== false && buyActive[index] !== false
      }))
    },
    takeprofitGuideRows() {
      return TAKEPROFIT_GUIDE_META.map((item) => {
        const draftIndex = item.level - 1
        const draft = this.takeprofitDrafts?.[draftIndex] || {
          level: item.level,
          price: null,
          manual_enabled: true
        }
        return {
          ...item,
          draftIndex,
          price: draft.price,
          manual_enabled: Boolean(draft.manual_enabled),
          armed: Boolean(draft.manual_enabled) && isTakeprofitArmedLevel(this.takeprofitState, item.level)
        }
      })
    },
    emptyMessage() {
      return getKlineSlimEmptyMessage({
        resolvingDefaultSymbol: this.resolvingDefaultSymbol,
        resolveError: this.defaultSymbolResolveError
      })
    },
    chanlunStructure() {
      if (!this.chanlunStructureData || typeof this.chanlunStructureData !== 'object') {
        return {}
      }
      return this.chanlunStructureData.structure || {}
    },
    chanlunStructureAsof() {
      return this.chanlunStructureData?.asof || ''
    },
    chanlunStructureMessage() {
      return this.chanlunStructureData?.message || ''
    },
    chanlunStructureSourceLabel() {
      const source = this.chanlunStructureData?.source || ''
      return CHANLUN_SOURCE_LABELS[source] || source || '--'
    },
    chanlunHigherSegment() {
      return this.chanlunStructure.higher_segment || null
    },
    chanlunHigherSegmentSummary() {
      return buildChanlunSummaryItems({
        item: this.chanlunHigherSegment,
        fields: [
          { label: '方向', value: formatDirectionLabel(this.chanlunHigherSegment?.direction) },
          { label: '价格比例', value: formatPercentValue(this.chanlunHigherSegment?.price_change_pct) },
          { label: '包含段数', value: this.chanlunHigherSegment?.contained_duan_count ?? '--' },
          { label: '中枢数', value: this.chanlunHigherSegment?.pivot_count ?? '--' },
          { label: '起始', value: buildChanlunTimePriceValue(this.chanlunHigherSegment, 'start_time', 'start_price') },
          { label: '终点', value: buildChanlunTimePriceValue(this.chanlunHigherSegment, 'end_time', 'end_price') }
        ]
      })
    },
    chanlunSegment() {
      return this.chanlunStructure.segment || null
    },
    chanlunSegmentSummary() {
      return buildChanlunSummaryItems({
        item: this.chanlunSegment,
        fields: [
          { label: '方向', value: formatDirectionLabel(this.chanlunSegment?.direction) },
          { label: '价格比例', value: formatPercentValue(this.chanlunSegment?.price_change_pct) },
          { label: '包含笔数', value: this.chanlunSegment?.contained_bi_count ?? '--' },
          { label: '中枢数', value: this.chanlunSegment?.pivot_count ?? '--' },
          { label: '起始', value: buildChanlunTimePriceValue(this.chanlunSegment, 'start_time', 'start_price') },
          { label: '终点', value: buildChanlunTimePriceValue(this.chanlunSegment, 'end_time', 'end_price') }
        ]
      })
    },
    chanlunBi() {
      return this.chanlunStructure.bi || null
    },
    chanlunBiSummary() {
      return buildChanlunSummaryItems({
        item: this.chanlunBi,
        fields: [
          { label: '方向', value: formatDirectionLabel(this.chanlunBi?.direction) },
          { label: '价格比例', value: formatPercentValue(this.chanlunBi?.price_change_pct) },
          { label: 'K线数', value: computeChanlunBiBarCount(this.chanlunBi) },
          { label: '起始', value: buildChanlunTimePriceValue(this.chanlunBi, 'start_time', 'start_price') },
          { label: '终点', value: buildChanlunTimePriceValue(this.chanlunBi, 'end_time', 'end_price') }
        ]
      })
    },
    statusText() {
      if (this.defaultSymbolResolveError) {
        return this.defaultSymbolResolveError
      }
      if (this.resolvingDefaultSymbol) {
        return '默认标的解析中'
      }
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
  created() {
    this.pricePanelActions = createKlineSlimPricePanelActions(subjectManagementApi)
    this.loadSidebarData()
  },
  mounted() {
    this.initChart()
    this.publishBrowserTestHooks()
    this.scheduleRender()
    document.addEventListener('visibilitychange', this.handleVisibilityChange)
    window.addEventListener('resize', this.handleResize)
  },
  beforeUnmount() {
    this.routeToken += 1
    this.resolvingDefaultSymbol = false
    document.removeEventListener('visibilitychange', this.handleVisibilityChange)
    window.removeEventListener('resize', this.handleResize)
    this.stopPolling()
    if (this.renderFrameId) {
      window.cancelAnimationFrame(this.renderFrameId)
      this.renderFrameId = 0
    }
    if (this.chartController) {
      this.chartController.dispose()
      this.chartController = null
    }
    if (this.chart) {
      this.clearBrowserTestHooks()
      this.chart.dispose()
      this.chart = null
    }
    this.clearBrowserTestHooks()
  },
  methods: {
    async loadSidebarData() {
      await Promise.allSettled([
        this.loadHoldingList(),
        this.loadMustPools(),
        this.loadStockPools(),
        this.loadPrePools()
      ])
    },
    async loadHoldingList() {
      this.sidebarLoading.holding = true
      this.sidebarErrors.holding = ''
      try {
        const items = await stockApi.getHoldingPositionList()
        this.holdings = Array.isArray(items) ? items : []
      } catch (error) {
        this.holdings = []
        this.sidebarErrors.holding = '加载失败'
      } finally {
        this.sidebarLoading.holding = false
      }
    },
    async loadMustPools() {
      this.sidebarLoading.must_pool = true
      this.sidebarErrors.must_pool = ''
      try {
        const items = await stockApi.getStockMustPoolsList({ page: 1, size: 1000 })
        this.mustPools = Array.isArray(items) ? items : []
      } catch (error) {
        this.mustPools = []
        this.sidebarErrors.must_pool = '加载失败'
      } finally {
        this.sidebarLoading.must_pool = false
      }
    },
    async loadStockPools() {
      this.sidebarLoading.stock_pools = true
      this.sidebarErrors.stock_pools = ''
      try {
        const items = await stockApi.getStockPoolsList({ page: 1, size: 1000 })
        this.stockPools = Array.isArray(items) ? items : []
      } catch (error) {
        this.stockPools = []
        this.sidebarErrors.stock_pools = '加载失败'
      } finally {
        this.sidebarLoading.stock_pools = false
      }
    },
    async loadPrePools() {
      this.sidebarLoading.stock_pre_pools = true
      this.sidebarErrors.stock_pre_pools = ''
      try {
        const items = await stockApi.getStockPrePoolsList({ page: 1, size: 1000 })
        this.prePools = Array.isArray(items) ? items : []
      } catch (error) {
        this.prePools = []
        this.sidebarErrors.stock_pre_pools = '加载失败'
      } finally {
        this.sidebarLoading.stock_pre_pools = false
      }
    },
    initChart() {
      const chartDom = this.$refs.chartHost
      if (!chartDom || this.chart) {
        return
      }
      this.chart = echarts.init(chartDom, 'dark')
      this.chartController = createKlineSlimChartController({
        chart: this.chart,
        onLegendChange: this.handleSlimLegendSelectionChange,
        onViewportChange: this.handleSlimViewportChange
      })
      this.publishBrowserTestHooks()
      this.chart.showLoading(echartsConfig.loadingOption)
    },
    publishBrowserTestHooks() {
      if (!window.navigator?.webdriver) {
        return
      }
      window.__klineSlimVm = this
      window.__klineSlimChart = this.chart || null
      window.__klineSlimChartController = this.chartController || null
    },
    clearBrowserTestHooks() {
      if (!window.navigator?.webdriver) {
        return
      }
      if (window.__klineSlimVm === this) {
        window.__klineSlimVm = null
      }
      if (window.__klineSlimChart === this.chart || window.__klineSlimVm === null) {
        window.__klineSlimChart = null
      }
      if (window.__klineSlimChartController === this.chartController || window.__klineSlimVm === null) {
        window.__klineSlimChartController = null
      }
    },
    handleResize() {
      if (this.chart) {
        this.chart.resize()
        this.chartController?.syncCrosshair?.()
      }
    },
    handleVisibilityChange() {
      if (document.visibilityState === 'visible') {
        this.handleRouteChange()
        return
      }
      this.stopPolling()
    },
    resetSlimDataState() {
      this.lastError = ''
      this.lastRenderedVersion = ''
      this.mainVersion = ''
      this.chanlunVersionMap = {}
      this.mainData = null
      this.chanlunMultiData = {}
      this.loadedChanlunPeriods = []
      this.chanlunPeriodLoading = {}
      this.visibleChanlunPeriods = getVisibleChanlunPeriods({
        currentPeriod: this.currentPeriod,
        selected: this.periodLegendSelected
      })
      this.lastMainBarLabel = '--'
      this.chartViewport = createKlineSlimViewportState()
      this.resetViewportOnNextRender = true
    },
    handleRouteChange() {
      this.currentPeriod = getRoutePeriod(this.$route)
      this.periodLegendSelected = buildPeriodLegendSelectionState({
        currentPeriod: this.currentPeriod,
        previousSelected: this.periodLegendSelected
      })
      this.visibleChanlunPeriods = getVisibleChanlunPeriods({
        currentPeriod: this.currentPeriod,
        selected: this.periodLegendSelected
      })
      this.symbolInput = this.routeSymbol
      this.endDateModel = this.$route.query.endDate || ''
      this.resetChanlunStructureState()

      if (!this.routeSymbol && shouldResolveDefaultSymbol(this.$route.query)) {
        this.routeToken += 1
        this.defaultSymbolResolveError = ''
        this.resetSlimDataState()
        this.stopPolling()
        this.resolvingDefaultSymbol = true

        if (this.chartController) {
          this.chartController.clear()
        } else if (this.chart) {
          this.chart.clear()
          this.chart.hideLoading()
        }

        this.resolveDefaultSymbol(this.routeToken)
        return
      }

      this.resolvingDefaultSymbol = false
      this.defaultSymbolResolveError = ''

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
      this.resetSlimDataState()
      this.stopPolling()
      const shouldClearPricePanel = this.lastSubjectDetailSymbol && this.lastSubjectDetailSymbol !== this.routeSymbol
      if (shouldClearPricePanel) {
        clearSubjectPriceDetailState(this)
      }

      if (this.chart && this.routeSymbol) {
        this.chart.showLoading(echartsConfig.loadingOption)
      }

      if (!this.routeSymbol) {
        resetSubjectPriceDetailState(this)
        if (this.chartController) {
          this.chartController.clear()
        } else if (this.chart) {
          this.chart.clear()
          this.chart.hideLoading()
        }
        return
      }

      this.loadSubjectPriceDetail({
        force: shouldClearPricePanel || this.lastSubjectDetailSymbol !== this.routeSymbol || !this.subjectPriceDetail
      })
      this.refreshVisibleChanlunPeriods(this.routeToken)
      if (this.isRealtimeMode && document.visibilityState === 'visible') {
        this.chanlunRefreshTimer = window.setInterval(
          () => this.refreshVisibleChanlunPeriods(this.routeToken),
          CHANLUN_POLL_MS
        )
      }
    },
    async resolveDefaultSymbol(token) {
      try {
        const positions = await stockApi.getHoldingPositionList()
        if (
          !canApplyResolvedKlineSlimRoute({
            token,
            routeToken: this.routeToken,
            routePath: this.$route?.path
          })
        ) {
          return
        }

        const symbol = pickFirstHoldingSymbol(positions)
        this.resolvingDefaultSymbol = false
        if (!symbol) {
          return
        }

        if (
          !canApplyResolvedKlineSlimRoute({
            token,
            routeToken: this.routeToken,
            routePath: this.$route?.path
          })
        ) {
          return
        }

        this.$router.replace({
          path: '/kline-slim',
          query: buildResolvedKlineSlimQuery({
            currentQuery: this.$route.query,
            symbol,
            period: this.currentPeriod
          })
        })
      } catch (error) {
        if (token !== this.routeToken) {
          return
        }
        this.resolvingDefaultSymbol = false
        this.defaultSymbolResolveError = '默认持仓解析失败'
      }
    },
    isSidebarItemActive(item) {
      return getSidebarCode6(item) === this.activeCode6
    },
    toggleSidebarSection(sectionKey) {
      this.expandedSidebarKey = toggleSidebarExpandedKey(this.expandedSidebarKey, sectionKey)
    },
    selectSidebarItem(item) {
      const symbol = (item && item.symbol) || ''
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
    getSidebarDeleteKey(sectionKey, item) {
      const code6 = getSidebarCode6(item)
      return code6 ? `${sectionKey}:${code6}` : ''
    },
    isSidebarDeletePending(sectionKey, item) {
      const deleteKey = this.getSidebarDeleteKey(sectionKey, item)
      return deleteKey ? !!this.sidebarDeleting[deleteKey] : false
    },
    async loadSidebarSectionByKey(sectionKey) {
      switch (sectionKey) {
        case 'holding':
          await this.loadHoldingList()
          break
        case 'must_pool':
          await this.loadMustPools()
          break
        case 'stock_pools':
          await this.loadStockPools()
          break
        case 'stock_pre_pools':
          await this.loadPrePools()
          break
        default:
          break
      }
    },
    async refreshSidebarSections(sectionKeys = []) {
      const uniqueKeys = Array.from(new Set(sectionKeys.filter(Boolean)))
      await Promise.allSettled(uniqueKeys.map((sectionKey) => this.loadSidebarSectionByKey(sectionKey)))
    },
    async deleteSidebarItem(sectionKey, item) {
      const behavior = getSidebarDeleteBehavior(sectionKey)
      const code6 = getSidebarCode6(item)
      if (!behavior || !code6) {
        return
      }

      const deleteKey = this.getSidebarDeleteKey(sectionKey, item)
      this.sidebarDeleting = { ...this.sidebarDeleting, [deleteKey]: true }
      try {
        const method = stockApi[behavior.method]
        if (typeof method !== 'function') {
          throw new Error(`missing stockApi method: ${behavior.method}`)
        }
        await method.call(stockApi, code6)
        await this.refreshSidebarSections(behavior.refreshKeys)
      } catch (error) {
        if (typeof this.$message?.error === 'function') {
          this.$message.error('删除失败')
        }
      } finally {
        this.sidebarDeleting = { ...this.sidebarDeleting, [deleteKey]: false }
      }
    },
    async handleReasonPopoverShow(item) {
      const code6 = getSidebarCode6(item)
      if (!code6 || this.reasonCache[code6] || this.reasonLoading[code6]) {
        return
      }

      this.reasonLoading = { ...this.reasonLoading, [code6]: true }
      this.reasonError = { ...this.reasonError, [code6]: '' }
      try {
        const payload = await getGanttStockReasons({ code6, provider: 'all', limit: 0 })
        this.reasonCache = {
          ...this.reasonCache,
          [code6]: normalizeReasonItems(payload)
        }
      } catch (error) {
        this.reasonError = { ...this.reasonError, [code6]: '加载失败' }
      } finally {
        this.reasonLoading = { ...this.reasonLoading, [code6]: false }
      }
    },
    getReasonItems(item) {
      const code6 = getSidebarCode6(item)
      return this.reasonCache[code6] || []
    },
    getReasonMessage(item) {
      const code6 = getSidebarCode6(item)
      return getReasonPanelMessage({
        loading: !!this.reasonLoading[code6],
        error: this.reasonError[code6] || '',
        items: this.reasonCache[code6] || []
      })
    },
    closePriceGuidePanel() {
      this.showPriceGuidePanel = false
    },
    async togglePriceGuidePanel() {
      if (!this.routeSymbol) {
        return
      }
      if (this.showPriceGuidePanel) {
        this.closePriceGuidePanel()
        return
      }
      this.closeChanlunStructurePanel()
      this.showPriceGuidePanel = true
      if (!this.subjectPriceDetail && !this.subjectDetailLoading) {
        await this.loadSubjectPriceDetail({ force: true })
      }
    },
    resetChanlunStructureState() {
      this.showChanlunStructurePanel = false
      this.chanlunStructureLoading = false
      this.chanlunStructureError = ''
      this.chanlunStructureRefreshError = ''
      this.chanlunStructureData = null
    },
    async toggleChanlunStructurePanel() {
      if (!this.routeSymbol) {
        return
      }
      if (this.showChanlunStructurePanel) {
        this.closeChanlunStructurePanel()
        return
      }
      this.closePriceGuidePanel()
      await this.openChanlunStructurePanel()
    },
    async openChanlunStructurePanel() {
      if (!this.routeSymbol) {
        return
      }
      this.showChanlunStructurePanel = true
      if (this.chanlunStructureData || this.chanlunStructureLoading) {
        return
      }
      await this.loadChanlunStructure({ preserveData: false })
    },
    closeChanlunStructurePanel() {
      this.showChanlunStructurePanel = false
      this.chanlunStructureRefreshError = ''
    },
    async refreshChanlunStructure() {
      if (!this.showChanlunStructurePanel) {
        return
      }
      await this.loadChanlunStructure({ preserveData: true })
    },
    async retryChanlunStructure() {
      await this.loadChanlunStructure({ preserveData: false })
    },
    async loadChanlunStructure({ preserveData = true } = {}) {
      if (this.chanlunStructureLoading || !this.routeSymbol) {
        return
      }

      const requestToken = this.routeToken
      const hasPreviousData = preserveData && !!this.chanlunStructureData
      this.chanlunStructureLoading = true
      this.chanlunStructureError = ''
      this.chanlunStructureRefreshError = ''
      if (!preserveData) {
        this.chanlunStructureData = null
      }

      try {
        const payload = await futureApi.stockChanlunStructure({
          symbol: this.routeSymbol,
          period: this.currentPeriod,
          endDate: this.endDateModel || undefined
        })
        if (requestToken !== this.routeToken || !payload) {
          return
        }
        this.chanlunStructureData = payload
      } catch (error) {
        if (requestToken !== this.routeToken) {
          return
        }
        if (hasPreviousData) {
          this.chanlunStructureRefreshError = '刷新失败，保留上次结果'
          return
        }
        this.chanlunStructureData = null
        this.chanlunStructureError = '缠论结构加载失败'
      } finally {
        if (requestToken === this.routeToken) {
          this.chanlunStructureLoading = false
        }
      }
    },
    stopPolling() {
      if (this.chanlunRefreshTimer) {
        window.clearInterval(this.chanlunRefreshTimer)
        this.chanlunRefreshTimer = null
      }
    },
    handleSlimViewportChange(viewport) {
      this.chartViewport = viewport
      this.publishBrowserTestHooks()
    },
    handleSlimLegendSelectionChange(selected) {
      this.periodLegendSelected = buildPeriodLegendSelectionState({
        currentPeriod: this.currentPeriod,
        previousSelected: selected
      })
      this.priceGuideLegendSelected = buildPriceGuideLegendSelectionState(selected)
      this.visibleChanlunPeriods = getVisibleChanlunPeriods({
        currentPeriod: this.currentPeriod,
        selected: this.periodLegendSelected
      })
      this.refreshVisibleChanlunPeriods(this.routeToken)
      this.scheduleRender()
    },
    cacheChanlunPeriodPayload(period, payload) {
      const nextVersion = buildVersion(payload)
      if (!nextVersion) {
        return ''
      }

      this.chanlunMultiData = {
        ...this.chanlunMultiData,
        [period]: payload
      }
      this.chanlunVersionMap = {
        ...this.chanlunVersionMap,
        [period]: nextVersion
      }
      if (!this.loadedChanlunPeriods.includes(period)) {
        this.loadedChanlunPeriods = [...this.loadedChanlunPeriods, period]
      }
      return nextVersion
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
          endDate: this.endDateModel || undefined,
          realtimeCache: this.isRealtimeMode,
          barCount: DEFAULT_KLINE_SLIM_BAR_COUNT
        })
        if (token !== this.routeToken || !payload) {
          return
        }
        const nextVersion = this.cacheChanlunPeriodPayload(this.currentPeriod, payload)
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
    async loadSubjectPriceDetail(options = {}) {
      const updated = await loadSubjectPriceDetailState(this, {
        actions: this.pricePanelActions,
        symbol: options.symbol || this.routeSymbol,
        force: !!options.force
      })
      if (updated) {
        this.scheduleRender()
      }
      return updated
    },
    async handleSaveGuardianPriceGuides() {
      return saveGuardianPriceGuides(this, {
        actions: this.pricePanelActions,
        symbol: this.routeSymbol,
        notify: this.$message,
        afterRefresh: () => this.scheduleRender()
      })
    },
    async handleSaveTakeprofitPriceGuides() {
      return saveTakeprofitPriceGuides(this, {
        actions: this.pricePanelActions,
        symbol: this.routeSymbol,
        notify: this.$message,
        afterRefresh: () => this.scheduleRender()
      })
    },
    async ensureChanlunPeriodLoaded(period, token = this.routeToken, options = {}) {
      const resolvedPeriod = normalizeChanlunPeriod(period)
      const { force = false } = options

      if (!this.routeSymbol) {
        return
      }
      if (resolvedPeriod === this.currentPeriod) {
        if (force || !this.mainData) {
          await this.fetchMainData(token)
        }
        return
      }
      if (this.chanlunPeriodLoading[resolvedPeriod]) {
        return
      }
      if (!force && this.chanlunMultiData[resolvedPeriod]) {
        return
      }

      this.chanlunPeriodLoading = {
        ...this.chanlunPeriodLoading,
        [resolvedPeriod]: true
      }
      try {
        const payload = await futureApi.stockData({
          symbol: this.routeSymbol,
          period: resolvedPeriod,
          endDate: this.endDateModel || undefined,
          realtimeCache: this.isRealtimeMode,
          barCount: DEFAULT_KLINE_SLIM_BAR_COUNT
        })
        if (token !== this.routeToken || !payload) {
          return
        }
        const nextVersion = this.cacheChanlunPeriodPayload(resolvedPeriod, payload)
        if (!nextVersion) {
          return
        }
        this.scheduleRender()
      } catch (error) {
        if (token === this.routeToken) {
          this.lastError = '叠加结构刷新失败'
        }
      } finally {
        this.chanlunPeriodLoading = {
          ...this.chanlunPeriodLoading,
          [resolvedPeriod]: false
        }
      }
    },
    async refreshVisibleChanlunPeriods(token = this.routeToken) {
      const refreshPeriods = getRealtimeRefreshPeriods({
        currentPeriod: this.currentPeriod,
        visiblePeriods: this.visibleChanlunPeriods
      })

      await Promise.allSettled(
        refreshPeriods.map((period) =>
          this.ensureChanlunPeriodLoaded(period, token, {
            force: this.isRealtimeMode
          })
        )
      )
    },
    scheduleRender() {
      if (!this.chart || !this.chartController || !this.mainData) {
        return
      }
      if (this.renderFrameId) {
        window.cancelAnimationFrame(this.renderFrameId)
      }

      this.renderFrameId = window.requestAnimationFrame(() => {
        this.renderFrameId = 0
        const extraPeriods = this.visibleChanlunPeriods
        const renderVersion = [this.currentPeriod]
          .concat(extraPeriods)
          .map((period) => this.chanlunVersionMap[period] || '')
          .concat(JSON.stringify(this.periodLegendSelected))
          .concat(JSON.stringify(this.priceGuideLegendSelected))
          .concat(this.priceGuideVersion || '')
          .join('__')
        if (
          renderVersion === this.lastRenderedVersion &&
          !this.resetViewportOnNextRender
        ) {
          return
        }

        const scene = buildKlineSlimChartScene({
          mainData: this.mainData,
          currentPeriod: this.currentPeriod,
          sceneId: [this.routeSymbol || 'unknown', this.currentPeriod, this.endDateModel || 'realtime'].join('__'),
          extraChanlunMap: Object.fromEntries(
            extraPeriods
              .map((period) => [period, this.chanlunMultiData[period]])
              .filter(([, payload]) => !!payload)
          ),
          visiblePeriods: extraPeriods,
          legendSelected: {
            ...this.periodLegendSelected,
            ...this.priceGuideLegendSelected
          },
          priceGuides: this.subjectPriceDetail?.chartPriceGuides || null
        })
        if (!scene) {
          return
        }

        this.chartController.applyScene(scene, {
          resetViewport: this.resetViewportOnNextRender
        })
        this.chartViewport = this.chartController.getViewport()
        this.publishBrowserTestHooks()
        this.lastRenderedVersion = renderVersion
        this.resetViewportOnNextRender = false
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
      this.refreshVisibleChanlunPeriods(this.routeToken)
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
    },
    formatPriceGuideValue(value) {
      return formatPriceValue(value)
    }
  }
}
