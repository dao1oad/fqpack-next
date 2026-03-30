import { getGanttStockReasons } from '@/api/ganttApi'
import { stockApi } from '@/api/stockApi'

import echartsConfig from './js/echartsConfig'
import { createKlineSlimViewportState } from './js/kline-slim-chart-controller.mjs'
import { buildKlineSlimChartScene } from './js/kline-slim-chart-renderer.mjs'
import {
  buildResolvedKlineSlimQuery,
  canApplyResolvedKlineSlimRoute,
  pickFirstHoldingSymbol,
  shouldResolveDefaultSymbol
} from './js/kline-slim-default-symbol.mjs'
import {
  clearSubjectPriceDetailState,
  resetSubjectPriceDetailState,
} from './js/kline-slim-price-panel.mjs'
import { buildInitialKlineSlimSubjectPanelState } from './js/kline-slim-subject-panel.mjs'
import {
  SUPPORTED_CHANLUN_PERIODS,
  DEFAULT_MAIN_PERIOD,
  buildPeriodLegendSelectionState,
  getRealtimeRefreshPeriods,
  getVisibleChanlunPeriods,
  normalizeChanlunPeriod
} from './js/kline-slim-chanlun-periods.mjs'
import {
  getSidebarDeleteBehavior,
  getSidebarCode6,
  normalizeReasonItems
} from './klineSlimSidebar.mjs'
import { closeOtherPanels } from './klineSlimPageState.mjs'

const DEFAULT_PERIOD = DEFAULT_MAIN_PERIOD
const MAIN_PERIODS = SUPPORTED_CHANLUN_PERIODS
const CHANLUN_POLL_MS = 15000

function getRoutePeriod(route) {
  return normalizeChanlunPeriod(route?.query?.period || DEFAULT_PERIOD)
}

function resetSubjectPanelState(state, { preserveOpen = false } = {}) {
  const nextState = buildInitialKlineSlimSubjectPanelState()
  Object.assign(state, nextState)
  state.showSubjectPanel = preserveOpen
}

export const klineSlimController = {
  watch: {
    '$route.fullPath': {
      immediate: true,
      handler() {
        this.handleRouteChange()
      }
    },
    priceGuideRenderVersion() {
      this.scheduleRender()
    }
  },
  created() {
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
    handleVisibilityChange() {
      if (document.visibilityState === 'visible') {
        this.handleRouteChange()
        return
      }
      this.stopPolling()
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
      this.priceGuideEditMode = false
      this.priceGuideDragDirty = false
      this.symbolInput = this.routeSymbol
      this.endDateModel = this.$route.query.endDate || ''
      this.resetChanlunStructureState()
      if (!this.routeSymbol) {
        this.closeSubjectPanel()
        resetSubjectPanelState(this.subjectPanelState)
      }

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
      const shouldClearSubjectPanel = this.subjectPanelState.lastSubjectSymbol && this.subjectPanelState.lastSubjectSymbol !== this.routeSymbol
      if (shouldClearPricePanel) {
        clearSubjectPriceDetailState(this)
      }
      if (shouldClearSubjectPanel) {
        resetSubjectPanelState(this.subjectPanelState, { preserveOpen: this.showSubjectPanel })
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
      if (this.showSubjectPanel) {
        this.loadSubjectPanelDetail({
          force: shouldClearSubjectPanel || this.subjectPanelState.lastSubjectSymbol !== this.routeSymbol || !this.subjectPanelState.subjectPanelDetail
        })
      }
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
    async togglePriceGuideEditMode() {
      if (!this.routeSymbol) {
        return
      }
      if (this.priceGuideEditMode) {
        this.closePriceGuidePanel()
        return
      }
      closeOtherPanels(this, 'showPriceGuidePanel')
      this.showPriceGuidePanel = true
      this.priceGuideEditMode = true
      this.priceGuideDragDirty = false
      if (!this.subjectPriceDetail && !this.subjectDetailLoading) {
        await this.loadSubjectPriceDetail({ force: true })
      }
    },
    async toggleSubjectPanel() {
      if (!this.routeSymbol) {
        return
      }
      if (this.showSubjectPanel) {
        this.closeSubjectPanel()
        return
      }
      closeOtherPanels(this, 'showSubjectPanel')
      this.showSubjectPanel = true
      this.subjectPanelState.showSubjectPanel = true
      if (!this.subjectPanelState.subjectPanelDetail || this.subjectPanelState.lastSubjectSymbol !== this.routeSymbol) {
        await this.loadSubjectPanelDetail({ force: true })
      }
    },
    async toggleChanlunStructurePanel() {
      if (!this.routeSymbol) {
        return
      }
      if (this.showChanlunStructurePanel) {
        this.closeChanlunStructurePanel()
        return
      }
      closeOtherPanels(this, 'showChanlunStructurePanel')
      await this.openChanlunStructurePanel()
    },
    stopPolling() {
      if (this.chanlunRefreshTimer) {
        window.clearInterval(this.chanlunRefreshTimer)
        this.chanlunRefreshTimer = null
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
          .concat(this.priceGuideRenderVersion || '')
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
          priceGuides: this.draftChartPriceGuides,
          editablePriceGuides: this.editablePriceGuides,
          priceGuideEditMode: this.priceGuideEditMode,
          priceGuideEditLocked: this.priceGuideEditLocked
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
    resetChartViewport() {
      this.chartViewport = createKlineSlimViewportState()
      this.resetViewportOnNextRender = true
      this.scheduleRender()
    }
  }
}

export default klineSlimController
