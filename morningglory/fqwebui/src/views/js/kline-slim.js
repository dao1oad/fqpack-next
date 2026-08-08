import * as echarts from 'echarts'

import { futureApi } from '@/api/futureApi'
import { positionReviewApi } from '@/api/positionReviewApi'
import { stockApi } from '@/api/stockApi'
import { subjectManagementApi } from '@/api/subjectManagementApi'
import { clxDailySelectionApi } from '@/api/clxDailySelectionApi.js'

import echartsConfig from './echartsConfig'
import { createKlineSlimChartController, createKlineSlimViewportState } from './kline-slim-chart-controller.mjs'
import {
  CLX_SIGNAL_LEGEND_NAME,
  getOrderReviewChartConditions,
  setOrderReviewChartConditions,
} from './kline-slim-chart-renderer.mjs'
import {
  buildInitialKlineSlimPricePanelState,
  createKlineSlimPricePanelActions,
  loadSubjectPriceDetail as loadSubjectPriceDetailState,
  saveGuardianGuideEnabledState,
  savePriceGuides,
  saveGuardianPriceGuides,
  saveTakeprofitGuideEnabledState,
  saveTakeprofitPriceGuides,
} from './kline-slim-price-panel.mjs'
import {
  buildInitialKlineSlimSubjectPanelState,
  createKlineSlimSubjectPanelActions,
  restoreKlineSlimPositionLimitDefault,
} from './kline-slim-subject-panel.mjs'
import {
  getKlineSlimEmptyMessage,
} from './kline-slim-default-symbol.mjs'
import {
  buildSidebarSections,
  getReasonPanelMessage,
  getSidebarCode6,
  toggleSidebarExpandedKey
} from '../klineSlimSidebar.mjs'
import {
  SUPPORTED_CHANLUN_PERIODS,
  DEFAULT_MAIN_PERIOD,
  DEFAULT_VISIBLE_CHANLUN_PERIODS,
  buildPeriodLegendSelectionState,
  getVisibleChanlunPeriods,
  normalizeChanlunPeriod,
} from './kline-slim-chanlun-periods.mjs'
import {
  buildChartPriceGuides,
  buildEditablePriceGuides,
  buildPriceGuideLegendSelectionState,
  clampGuardianGuidePrice,
  clampTakeprofitGuidePrice,
  isTakeprofitLevelArmed,
  resolveGuardianGuideDraft,
  resolveTakeprofitGuideDrafts
} from './subject-price-guides.mjs'
import {
  buildClxHistoryRequestKey,
  buildInitialKlineSlimPageState,
  buildKlineSlimRouteSymbol,
  closeOtherPanels,
} from '../klineSlimPageState.mjs'
import klineSlimController from '../klineSlimController.mjs'
import {
  normalizeClxCatalog,
} from '../clxDailySelection.mjs'
import {
  buildKlineClxQuery,
  filterClxMarkers,
  getClxModelColor,
  normalizeClxSignalHistory,
  parseKlineClxQuery,
  resolveClxAssetType,
} from './kline-slim-clx.mjs'

const MAIN_PERIODS = SUPPORTED_CHANLUN_PERIODS
const DEFAULT_PERIOD = DEFAULT_MAIN_PERIOD
const DEFAULT_KLINE_SLIM_BAR_COUNT = 20000
const CHANLUN_SOURCE_LABELS = {
  realtime_cache_fullcalc: '实时 fullcalc',
  history_fullcalc: '历史 fullcalc',
  fallback_fullcalc: '实时回退 fullcalc'
}
const GUARDIAN_GUIDE_META = [
  { key: 'buy_1', label: 'BUY-1', capLabel: 'CAP-1', tierLabel: '第一档', shortLabel: 'B1', tone: 'blue', lineLabel: '蓝线' },
  { key: 'buy_2', label: 'BUY-2', capLabel: 'CAP-2', tierLabel: '第二档', shortLabel: 'B2', tone: 'red', lineLabel: '红线' },
  { key: 'buy_3', label: 'BUY-3', capLabel: 'CAP-3', tierLabel: '第三档', shortLabel: 'B3', tone: 'green', lineLabel: '绿线' }
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

function parseKlineTimeMs(value) {
  const text = String(value || '').trim()
  if (!text) return NaN
  if (/Z$|[+-]\d{2}:?\d{2}$/.test(text)) {
    return Date.parse(text)
  }
  const normalized = text.replace(' ', 'T').replace(/\//g, '-')
  const withTimezone = normalized.length === 10
    ? `${normalized}T00:00:00+08:00`
    : `${normalized}+08:00`
  return Date.parse(withTimezone)
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

function formatPriceGuideValueDisplay(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) {
    return '--'
  }
  return number.toFixed(3)
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

function resolveLatestClosePrice(mainData) {
  const closeList = Array.isArray(mainData?.close) ? mainData.close : []
  const lastClose = Number(closeList[closeList.length - 1])
  return Number.isFinite(lastClose) ? Number(lastClose.toFixed(3)) : null
}

function buildPriceGuideRenderVersion({
  chartPriceGuides,
  editablePriceGuides,
  priceGuideEditMode,
  priceGuideEditLocked
} = {}) {
  return JSON.stringify({
    lines: Array.isArray(chartPriceGuides?.lines)
      ? chartPriceGuides.lines.map((line) => ({
        id: line.id,
        price: line.price,
        active: line.active,
        manual_enabled: line.manual_enabled
      }))
      : [],
    editableLines: Array.isArray(editablePriceGuides?.lines)
      ? editablePriceGuides.lines.map((line) => ({
        id: line.id,
        price: line.price,
        active: line.active,
        manual_enabled: line.manual_enabled,
        placeholder: line.placeholder
      }))
      : [],
    priceGuideEditMode: Boolean(priceGuideEditMode),
    priceGuideEditLocked: Boolean(priceGuideEditLocked)
  })
}

function cloneSubjectPanelMustPoolDraft(draft = {}) {
  return {
    category: String(draft?.category || '').trim(),
    stop_loss_price: draft?.stop_loss_price ?? null,
    initial_lot_amount: draft?.initial_lot_amount ?? null,
    lot_amount: draft?.lot_amount ?? null
  }
}

function cloneSubjectPanelPositionLimitDraft(draft = {}) {
  const rawLimit = draft?.limit ?? draft?.effective_limit ?? draft?.override_limit ?? draft?.default_limit
  const parsedLimit = rawLimit === null || rawLimit === undefined || rawLimit === ''
    ? null
    : Number(rawLimit)
  return {
    limit: Number.isFinite(parsedLimit) ? parsedLimit : null
  }
}

function cloneSubjectPanelStoplossDrafts(rows = []) {
  return Object.fromEntries(
    (Array.isArray(rows) ? rows : []).map((row) => [
      row.entry_id,
      {
        stop_price: row?.stoploss?.stop_price ?? null,
        enabled: Boolean(row?.stoploss?.enabled)
      }
    ])
  )
}

function applySubjectPanelDetailState(state, detail) {
  state.subjectPanelDetail = detail
  state.lastSubjectSymbol = detail?.symbol || ''
  state.mustPoolDraft = cloneSubjectPanelMustPoolDraft(detail?.mustPool || {})
  state.positionLimitDraft = cloneSubjectPanelPositionLimitDraft(detail?.positionLimit || {})
  state.stoplossDrafts = cloneSubjectPanelStoplossDrafts(detail?.entries || [])
}

function resolvePanelErrorMessage(error, fallback = '保存失败') {
  return error?.response?.data?.error || error?.message || fallback
}

function hasSubjectPanelMustPoolChanges(detail, draft) {
  const baseline = cloneSubjectPanelMustPoolDraft(detail?.mustPool || {})
  return JSON.stringify(cloneSubjectPanelMustPoolDraft(draft)) !== JSON.stringify(baseline)
}

function hasSubjectPanelPositionLimitChanges(detail, draft) {
  const baseline = cloneSubjectPanelPositionLimitDraft(detail?.positionLimit || {})
  return JSON.stringify(cloneSubjectPanelPositionLimitDraft(draft)) !== JSON.stringify(baseline)
}

function buildSubjectPanelPositionLimitPayload(draft = {}) {
  const parsedLimit = Number(draft?.limit)
  return {
    limit: parsedLimit
  }
}

function formatWanAmountLabel(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) {
    return '--'
  }
  return `${(number / 10000).toFixed(2)} 万`
}

function formatIntegerLabel(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) {
    return '--'
  }
  return String(Math.trunc(number))
}

function formatAmountLabel(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) {
    return '--'
  }
  return Math.trunc(number).toLocaleString('zh-CN')
}

function formatWanQuantityLabel(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) {
    return '--'
  }
  return `${(number / 10000).toFixed(2)} 万股`
}

export default {
  name: 'kline-slim',
  data() {
    const pricePanelState = buildInitialKlineSlimPricePanelState()
    const pageState = buildInitialKlineSlimPageState({
      currentPeriod: DEFAULT_PERIOD,
    })
    const subjectPanelState = buildInitialKlineSlimSubjectPanelState()
    return {
      pricePanelActions: createKlineSlimPricePanelActions(subjectManagementApi),
      subjectPanelActions: createKlineSlimSubjectPanelActions(subjectManagementApi),
      chart: null,
      chartController: null,
      chartResizeObserver: null,
      chartViewport: createKlineSlimViewportState(),
      lastHandledChartRouteKey: '',
      symbolInput: '',
      endDateModel: '',
      currentPeriod: pageState.currentPeriod,
      mainData: null,
      chanlunRefreshTimer: null,
      renderFrameId: 0,
      routeToken: 0,
      mainLoading: false,
      mainRequestKey: '',
      mainRequestId: 0,
      mainAbortController: null,
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
      priceGuideEditMode: false,
      priceGuideDragDirty: false,
      showOrderReview: false,
      orderReviewChart: null,
      orderReviewLoading: false,
      orderReviewError: '',
      orderReviewRequestId: 0,
      orderReviewRequestKey: '',
      orderReviewLoadedKey: '',
      orderReviewVersion: 0,
      clxCatalog: normalizeClxCatalog({}),
      showClxWorkbench: pageState.showClxWorkbench,
      clxSignalHistory: null,
      clxHistoryLoading: false,
      clxHistoryError: '',
      clxHistoryRequestId: 0,
      clxHistoryRequestKey: '',
      clxHistoryDesiredKey: '',
      clxHistoryLoadedKey: '',
      clxHistoryAbortController: null,
      clxHistoryVersion: 0,
      clxHistoryBarCount: 250,
      clxAssetType: '',
      clxSelectedModelKeys: [],
      clxSelectedConditionKeys: [],
      clxMarkerMode: 'aggregate',
      clxSelectedMarkerId: '',
      clxLegendSelected: true,
      clxWorkbenchTab: 'controls',
      clxMonitorAdding: false,
      holdings: [],
      mustPools: [],
      stockPools: [],
      stockPoolsTdxSyncing: false,
      mustPoolTdxSyncing: false,
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
      showChanlunStructurePanel: pageState.showChanlunStructurePanel,
      chanlunStructureLoading: false,
      chanlunStructureError: '',
      chanlunStructureRefreshError: '',
      chanlunStructureData: null,
      subjectPanelState,
      ...pricePanelState
    }
  },
  computed: {
    routeSymbol() {
      return buildKlineSlimRouteSymbol(this.$route)
    },
    isClxScreeningMode() {
      const value = String(this.$route?.query?.clxScreening || '').trim().toLowerCase()
      return this.showClxWorkbench || ['1', 'true', 'open'].includes(value)
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
    clxHistoryContractValid() {
      if (!this.clxSignalHistory) return false
      return (
        this.clxSignalHistory.profileId === 'production_v1' &&
        Number(this.clxSignalHistory.switchOpt) === 1 &&
        this.clxSignalHistory.futureFunctionGuard === true
      )
    },
    clxFilteredMarkers() {
      return filterClxMarkers(this.clxSignalHistory?.markers || [], {
        modelKeys: this.clxSelectedModelKeys,
        conditionKeys: this.clxSelectedConditionKeys,
      })
    },
    clxTimelineGroups() {
      const groups = new Map()
      this.clxFilteredMarkers.forEach((marker) => {
        if (!groups.has(marker.triggerDate)) groups.set(marker.triggerDate, [])
        groups.get(marker.triggerDate).push(marker)
      })
      return Array.from(groups.entries())
        .map(([tradeDate, markers]) => ({
          tradeDate,
          markers,
          modelKeys: Array.from(new Set(markers.map((item) => item.modelKey))).sort(),
          count: markers.length,
        }))
        .sort((left, right) => right.tradeDate.localeCompare(left.tradeDate))
    },
    clxSelectedMarker() {
      return (this.clxSignalHistory?.markers || []).find((item) => item.id === this.clxSelectedMarkerId) || null
    },
    clxModelOptions() {
      if (this.clxCatalog.models.length) return this.clxCatalog.models
      return Array.from(new Set((this.clxSignalHistory?.markers || []).map((item) => item.modelKey)))
        .sort()
        .map((key) => ({ key, label: key, description: '' }))
    },
    clxConditionOptions() {
      if (this.clxCatalog.conditions.length) return this.clxCatalog.conditions
      return Array.from(new Set((this.clxSignalHistory?.markers || []).map((item) => item.conditionKey).filter(Boolean)))
        .sort()
        .map((key) => ({ key, label: key }))
    },
    clxHistoryState() {
      if (!this.showClxWorkbench) return null
      if (this.clxHistoryLoading) return { kind: 'loading', message: 'CLX 历史信号加载中' }
      if (this.clxHistoryError) return { kind: 'error', message: this.clxHistoryError }
      if (!this.clxFilteredMarkers.length) return { kind: 'empty', message: '当前可见范围没有 CLX 历史信号' }
      return null
    },
    guardianGuideRows() {
      const buyEnabled = Array.isArray(this.guardianDraft?.buy_enabled)
        ? this.guardianDraft.buy_enabled
        : [true, true, true]
      return GUARDIAN_GUIDE_META.map((item, index) => ({
        ...item,
        index,
        price: this.guardianDraft?.[item.key] ?? null,
        manual_enabled: buyEnabled[index] !== false,
        active: buyEnabled[index] !== false
      }))
    },
    guardianLastHitLabel() {
      const lastHitLevel = String(this.guardianState?.last_hit_level || '').trim()
      return lastHitLevel || '未命中'
    },
    positionLimitSummary() {
      return this.subjectPanelState.subjectPanelDetail?.positionLimit || {}
    },
    positionLimitAvailable() {
      return this.positionLimitSummary.available !== false
    },
    positionLimitSourceLabel() {
      return this.positionLimitSummary.using_override ? '单独设置' : '系统默认值'
    },
    positionLimitUnavailableReason() {
      return this.positionLimitSummary.error || '该标的不在仓位管理跟踪范围'
    },
    effectivePositionLimit() {
      const limit = Number(this.positionLimitSummary.effective_limit)
      return Number.isFinite(limit) && limit > 0 ? limit : null
    },
    guardianCapExceedsPositionLimit() {
      if (!this.effectivePositionLimit) {
        return false
      }
      return (this.guardianDraft?.max_position_amounts || [])
        .some((value) => Number(value) > this.effectivePositionLimit)
    },
    positionLimitUsageLabel() {
      const marketValue = Number(this.positionLimitSummary.market_value)
      if (!Number.isFinite(marketValue) || !this.effectivePositionLimit) {
        return '--'
      }
      return `${Math.max(0, marketValue / this.effectivePositionLimit * 100).toFixed(1)}%`
    },
    takeprofitGuideRows() {
      return TAKEPROFIT_GUIDE_META.map((item) => {
        const draftIndex = item.level - 1
        const draft = this.takeprofitDrafts?.[draftIndex] || {
          level: item.level,
          price: null,
          manual_enabled: true
        }
        const runtimeActive = isTakeprofitLevelArmed(this.takeprofitState, item.level)
        return {
          ...item,
          draftIndex,
          price: draft.price,
          manual_enabled: Boolean(draft.manual_enabled),
          runtime_active: runtimeActive,
          runtimeStateLabel: runtimeActive ? '已布防' : '未布防',
          armed: Boolean(draft.manual_enabled) && isTakeprofitLevelArmed(this.takeprofitState, item.level)
        }
      })
    },
    takeprofitRuntimeActiveCount() {
      return this.takeprofitGuideRows.filter((row) => row.runtime_active).length
    },
    lastMainClosePrice() {
      return resolveLatestClosePrice(this.mainData)
    },
    draftChartPriceGuides() {
      return buildChartPriceGuides({
        guardianDraft: this.guardianDraft,
        guardianState: this.guardianState,
        takeprofitDrafts: this.takeprofitDrafts,
        takeprofitState: this.takeprofitState,
        costBasisPrice: this.subjectPriceDetail?.costBasisPrice ?? null,
        entries: this.subjectPriceDetail?.openEntries ?? []
      })
    },
    editablePriceGuides() {
      return buildEditablePriceGuides({
        guardianDraft: this.guardianDraft,
        guardianState: this.guardianState,
        takeprofitDrafts: this.takeprofitDrafts,
        takeprofitState: this.takeprofitState,
        lastPrice: this.lastMainClosePrice
      })
    },
    priceGuideEditLocked() {
      return (
        !this.routeSymbol ||
        this.subjectDetailLoading ||
        this.savingPriceGuides ||
        this.savingGuardianPriceGuides ||
        this.savingTakeprofitGuides
      )
    },
    priceGuideRenderVersion() {
      return buildPriceGuideRenderVersion({
        chartPriceGuides: this.draftChartPriceGuides,
        editablePriceGuides: this.editablePriceGuides,
        priceGuideEditMode: this.priceGuideEditMode,
        priceGuideEditLocked: this.priceGuideEditLocked
      })
    },
    orderReviewChartState() {
      if (!this.showOrderReview) {
        return null
      }
      if (this.orderReviewError) {
        return {
          kind: 'error',
          message: this.orderReviewError,
        }
      }
      if (this.orderReviewLoading || !this.mainData) {
        return {
          kind: 'loading',
          message: '交易复盘加载中',
        }
      }
      if (!Array.isArray(this.orderReviewChart?.order_events) || !this.orderReviewChart.order_events.length) {
        return {
          kind: 'empty',
          message: '当前时间窗暂无订单复盘数据',
        }
      }
      return null
    },
    emptyMessage() {
      return getKlineSlimEmptyMessage({
        resolvingDefaultSymbol: this.resolvingDefaultSymbol,
        resolveError: this.defaultSymbolResolveError,
        clxScreening: this.isClxScreeningMode
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
      if (this.orderReviewError) {
        return this.orderReviewError
      }
      if (this.resolvingDefaultSymbol) {
        return '默认标的解析中'
      }
      if (this.lastError) {
        return this.lastError
      }
      return this.isRealtimeMode ? '轮询中' : '历史模式'
    },
    toolbarStatusChipVariant() {
      if (this.defaultSymbolResolveError || this.lastError || this.orderReviewError) {
        return 'danger'
      }
      if (this.resolvingDefaultSymbol) {
        return 'warning'
      }
      return this.isRealtimeMode ? 'success' : 'muted'
    },
    takeprofitRuntimeChipVariant() {
      return this.takeprofitRuntimeActiveCount > 0 ? 'success' : 'muted'
    },
  },
  watch: klineSlimController.watch,
  created: klineSlimController.created,
  mounted: klineSlimController.mounted,
  beforeUnmount: klineSlimController.beforeUnmount,
  methods: {
    ...klineSlimController.methods,
    applyClxRouteState(routeState = parseKlineClxQuery(this.$route.query)) {
      this.clxAssetType = resolveClxAssetType(this.routeSymbol, routeState.assetType)
      this.clxSelectedModelKeys = [...routeState.modelKeys]
      this.clxSelectedConditionKeys = [...routeState.conditionKeys]
      this.clxMarkerMode = routeState.markerMode
      this.showClxWorkbench = routeState.workbenchOpen
      if (this.showClxWorkbench) {
        closeOtherPanels(this, 'showClxWorkbench')
      }
    },
    async syncClxRouteState() {
      const routeState = parseKlineClxQuery(this.$route.query)
      await this.$router.replace({
        path: '/kline-slim',
        query: buildKlineClxQuery({
          ...this.$route.query,
          ...(this.showClxWorkbench ? { clxScreening: '1' } : {}),
        }, {
          scopeId: routeState.scopeId,
          assetType: this.clxAssetType,
          modelKeys: this.clxSelectedModelKeys,
          conditionKeys: this.clxSelectedConditionKeys,
          markerMode: this.clxMarkerMode,
          workbenchOpen: this.showClxWorkbench,
        }),
      })
    },
    async handleClxScreeningSelection({ row, scope } = {}) {
      const symbol = String(row?.symbol || '').trim()
      if (!symbol) return

      const routeState = parseKlineClxQuery(this.$route.query)
      const assetType = resolveClxAssetType(symbol, row?.assetType || row?.raw?.asset_type)
      const scopeId = String(scope?.scopeId || routeState.scopeId || '').trim()
      const tradeDate = String(scope?.tradeDate || '').trim()

      closeOtherPanels(this, 'showClxWorkbench')
      this.showClxWorkbench = true
      this.clxAssetType = assetType
      await this.$router.replace({
        path: '/kline-slim',
        query: buildKlineClxQuery({
          ...this.$route.query,
          symbol,
          period: this.currentPeriod || '1d',
          ...(tradeDate ? { endDate: tradeDate } : {}),
          clxScreening: '1',
        }, {
          scopeId,
          assetType,
          modelKeys: this.clxSelectedModelKeys,
          conditionKeys: this.clxSelectedConditionKeys,
          markerMode: this.clxMarkerMode,
          workbenchOpen: true,
        }),
      })
    },
    async loadClxCatalog() {
      if (this.clxCatalog.models.length) return this.clxCatalog
      try {
        this.clxCatalog = normalizeClxCatalog(await clxDailySelectionApi.getModelCatalog())
      } catch (error) {
        this.clxCatalog = normalizeClxCatalog({})
      }
      return this.clxCatalog
    },
    async toggleClxWorkbench() {
      if (!this.routeSymbol) return
      if (this.showClxWorkbench) {
        await this.closeClxWorkbench()
        return
      }
      closeOtherPanels(this, 'showClxWorkbench')
      this.showClxWorkbench = true
      await Promise.allSettled([this.loadClxCatalog(), this.loadClxHistory()])
      await this.syncClxRouteState()
      this.scheduleRender()
    },
    async closeClxWorkbench() {
      this.showClxWorkbench = false
      this.clxSelectedMarkerId = ''
      this.abortClxHistoryRequest()
      await this.syncClxRouteState()
      this.scheduleRender()
    },
    abortClxHistoryRequest() {
      this.clxHistoryAbortController?.abort?.()
      this.clxHistoryAbortController = null
      this.clxHistoryRequestId += 1
      this.clxHistoryRequestKey = ''
      this.clxHistoryDesiredKey = ''
      this.clxHistoryLoading = false
    },
    async loadClxHistory({ force = false } = {}) {
      if (!this.showClxWorkbench || !this.routeSymbol) {
        this.abortClxHistoryRequest()
        return null
      }
      const symbol = this.routeSymbol
      const assetType = this.clxAssetType || resolveClxAssetType(symbol)
      const endDate = this.endDateModel
      const barCount = this.clxHistoryBarCount
      const requestKey = buildClxHistoryRequestKey({ symbol, assetType, endDate, barCount })
      this.clxHistoryDesiredKey = requestKey
      if (!force && this.clxSignalHistory && this.clxHistoryLoadedKey === requestKey) {
        return this.clxSignalHistory
      }
      if (!force && this.clxHistoryLoading && this.clxHistoryRequestKey === requestKey) return null

      this.clxHistoryAbortController?.abort?.()
      if (this.clxHistoryLoadedKey !== requestKey) {
        this.clxSignalHistory = null
        this.clxHistoryLoadedKey = ''
      }
      const abortController = new AbortController()
      const requestId = ++this.clxHistoryRequestId
      this.clxHistoryAbortController = abortController
      this.clxHistoryRequestKey = requestKey
      this.clxHistoryLoading = true
      this.clxHistoryError = ''
      this.clxHistoryVersion += 1
      try {
        const payload = await clxDailySelectionApi.getSignalHistory({
          symbol,
          assetType,
          period: '1d',
          endDate,
          barCount,
          modelKeys: [],
          conditionKeys: [],
          includeRaw: true,
        }, { signal: abortController.signal })
        if (
          requestId !== this.clxHistoryRequestId ||
          requestKey !== this.clxHistoryRequestKey ||
          requestKey !== this.clxHistoryDesiredKey ||
          abortController.signal.aborted ||
          !this.showClxWorkbench
        ) return null
        const history = normalizeClxSignalHistory(payload)
        this.clxSignalHistory = history
        this.clxHistoryLoadedKey = requestKey
        if (history.profileId !== 'production_v1' || Number(history.switchOpt) !== 1) {
          this.clxHistoryError = 'CLX 历史合同不一致：仅绘制 production_v1 / switch_opt=1'
        } else if (history.futureFunctionGuard !== true) {
          this.clxHistoryError = 'CLX 历史未来函数检查未通过'
        }
        this.clxHistoryVersion += 1
        this.scheduleRender()
        return history
      } catch (error) {
        if (
          requestId !== this.clxHistoryRequestId ||
          requestKey !== this.clxHistoryDesiredKey ||
          abortController.signal.aborted
        ) return null
        this.clxSignalHistory = null
        this.clxHistoryLoadedKey = ''
        this.clxHistoryError = Number(error?.response?.status) === 404
          ? 'CLX 历史信号服务尚未部署'
          : 'CLX 历史信号加载失败'
        this.clxHistoryVersion += 1
        this.scheduleRender()
        return null
      } finally {
        if (requestId === this.clxHistoryRequestId) {
          this.clxHistoryLoading = false
          this.clxHistoryRequestKey = ''
          this.clxHistoryAbortController = null
        }
      }
    },
    async handleClxVisibilityChange() {
      if (this.clxSelectedModelKeys.length > 1 && this.clxSelectedModelKeys.includes('__NONE__')) {
        this.clxSelectedModelKeys = this.clxSelectedModelKeys.filter((key) => key !== '__NONE__')
      }
      if (this.clxSelectedMarkerId && !this.clxFilteredMarkers.some((item) => item.id === this.clxSelectedMarkerId)) {
        this.clxSelectedMarkerId = ''
      }
      this.scheduleRender()
      await this.syncClxRouteState()
    },
    async selectAllClxModels() {
      this.clxSelectedModelKeys = this.clxModelOptions.map((item) => item.key)
      await this.handleClxVisibilityChange()
    },
    async clearClxModels() {
      this.clxSelectedModelKeys = ['__NONE__']
      await this.handleClxVisibilityChange()
    },
    async selectTriggeredClxModels() {
      this.clxSelectedModelKeys = Array.from(new Set((this.clxSignalHistory?.markers || []).map((item) => item.modelKey))).sort()
      await this.handleClxVisibilityChange()
    },
    async handleClxHistoryBarCountChange(value) {
      this.clxHistoryBarCount = Number(value) || 250
      await this.loadClxHistory({ force: true })
    },
    handleClxChartMarkerSelect(group) {
      const marker = group?.markers?.[0]
      if (marker) this.selectClxMarker(marker, { focus: false })
    },
    selectClxMarker(marker, { focus = true } = {}) {
      if (!marker?.id) return
      this.clxSelectedMarkerId = marker.id
      this.clxWorkbenchTab = 'detail'
      this.scheduleRender()
      if (focus) {
        this.$nextTick(() => {
          window.requestAnimationFrame(() => this.chartController?.focusClxMarker?.(marker.id))
        })
      }
    },
    navigateClxMarker(offset) {
      const markers = this.clxFilteredMarkers
      if (!markers.length) return
      const currentIndex = Math.max(0, markers.findIndex((item) => item.id === this.clxSelectedMarkerId))
      const nextIndex = Math.max(0, Math.min(markers.length - 1, currentIndex + offset))
      this.selectClxMarker(markers[nextIndex])
    },
    getClxModelColor(modelKey) {
      return getClxModelColor(modelKey)
    },
    formatClxEvidenceValue(evidence) {
      if (!evidence || typeof evidence !== 'object') return String(evidence ?? '-')
      const value = evidence.value ?? evidence.actual ?? evidence.result ?? evidence.reference_value ??
        evidence.trigger ?? evidence.trigger_code ?? evidence.status
      return value && typeof value === 'object' ? JSON.stringify(value) : String(value ?? '-')
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
    async syncStockPoolsFromTdxSelfSelect() {
      if (this.stockPoolsTdxSyncing) {
        return
      }
      this.stockPoolsTdxSyncing = true
      try {
        const result = await stockApi.syncStockPoolsFromTdxSelfSelect({ days: 30 })
        if (result && String(result.code ?? '0') !== '0') {
          throw new Error(result.msg || 'sync_stock_pools_from_tdx_self_select failed')
        }
        await this.loadStockPools()
        const summary = result?.data || {}
        this.$message?.success?.(
          '自选股已覆盖同步：同步 ' +
            (summary.synced_count ?? summary.appended_count ?? 0) +
            '，移除旧标的 ' +
            (summary.removed_count || 0) +
            '，持仓去重 ' +
            (summary.skipped_holding_count || 0)
        )
      } catch (error) {
        this.$message?.error?.('同步自选股失败')
      } finally {
        this.stockPoolsTdxSyncing = false
      }
    },
    async syncMustPoolFromTdxSelfSelect() {
      if (this.mustPoolTdxSyncing) {
        return
      }
      this.mustPoolTdxSyncing = true
      try {
        const result = await stockApi.syncMustPoolFromTdxSelfSelect({ days: 30 })
        if (result && String(result.code ?? '0') !== '0') {
          throw new Error(result.msg || 'sync_must_pool_from_tdx_self_select failed')
        }
        await this.loadMustPools()
        const summary = result?.data || {}
        this.$message?.success?.(
          '待买分组已导入：新增 ' +
            (summary.synced_count ?? summary.appended_count ?? 0) +
            '，持仓去重 ' +
            (summary.skipped_holding_count || 0) +
            '，忽略无效 ' +
            (summary.skipped_invalid_count || 0)
        )
      } catch (error) {
        this.$message?.error?.('同步待买分组失败')
      } finally {
        this.mustPoolTdxSyncing = false
      }
    },
    async addCurrentSymbolToClx15Monitor() {
      const code6 = this.activeCode6 || getSidebarCode6({
        symbol: this.routeSymbol,
        code: this.routeSymbol
      })
      if (!code6) {
        this.$message?.warning?.('请先选择标的')
        return
      }
      this.clxMonitorAdding = true
      try {
        const result = await stockApi.addToStockPoolsByCode(code6, 30, {
          allowDirect: true,
          category: 'CLX15分钟监控',
          source: 'clx_signal_workbench',
          remark: 'clx15_monitor'
        })
        if (result && String(result.code ?? '0') !== '0') {
          throw new Error(result.msg || 'add_to_stock_pools_by_code failed')
        }
        await this.loadStockPools()
        this.$message?.success?.(`${code6} 已加入clx15分钟监控`)
      } catch (error) {
        this.$message?.error?.('加入clx15分钟监控失败')
      } finally {
        this.clxMonitorAdding = false
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
      this.chart.on('mouseover', this.handleOrderReviewChartHover)
      this.chartController = createKlineSlimChartController({
        chart: this.chart,
        onLegendChange: this.handleSlimLegendSelectionChange,
        onViewportChange: this.handleSlimViewportChange,
        onPriceGuideDrag: this.handlePriceGuideDrag,
        onPriceGuideDragEnd: this.handlePriceGuideDragEnd,
        onClxMarkerSelect: this.handleClxChartMarkerSelect
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
        this.lastRenderedVersion = ''
        this.scheduleRender()
        this.chartController?.syncCrosshair?.()
      }
    },
    resetSlimDataState() {
      this.abortMainDataRequest()
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
      this.resetOrderReviewState()
      this.resetClxHistoryState()
    },
    abortMainDataRequest() {
      this.mainRequestId += 1
      this.mainAbortController?.abort?.()
      this.mainAbortController = null
      this.mainRequestKey = ''
      this.mainLoading = false
    },
    resetOrderReviewState() {
      this.orderReviewRequestId += 1
      this.orderReviewChart = null
      this.orderReviewLoading = false
      this.orderReviewError = ''
      this.orderReviewRequestKey = ''
      this.orderReviewLoadedKey = ''
      this.orderReviewVersion += 1
    },
    resetClxHistoryState() {
      this.clxHistoryAbortController?.abort?.()
      this.clxHistoryAbortController = null
      this.clxHistoryRequestId += 1
      this.clxSignalHistory = null
      this.clxHistoryLoading = false
      this.clxHistoryError = ''
      this.clxHistoryRequestKey = ''
      this.clxHistoryDesiredKey = ''
      this.clxHistoryLoadedKey = ''
      this.clxSelectedMarkerId = ''
      this.clxHistoryVersion += 1
    },
    getOrderReviewChartKey() {
      if (!this.routeSymbol) return ''
      return [this.routeSymbol, this.currentPeriod].join('__')
    },
    async loadOrderReviewChart({ force = false } = {}) {
      if (!this.showOrderReview || !this.routeSymbol) {
        return null
      }
      const requestKey = this.getOrderReviewChartKey()
      if (!requestKey) return null
      if (!force && this.orderReviewChart && this.orderReviewLoadedKey === requestKey) {
        return this.orderReviewChart
      }
      if (
        this.orderReviewLoading &&
        !force &&
        this.orderReviewRequestKey === requestKey
      ) {
        return null
      }

      const routeToken = this.routeToken
      const requestId = ++this.orderReviewRequestId
      this.orderReviewLoading = true
      this.orderReviewRequestKey = requestKey
      this.orderReviewError = ''
      this.orderReviewChart = null
      this.orderReviewLoadedKey = ''
      this.orderReviewVersion += 1
      this.scheduleRender()
      try {
        const payload = await positionReviewApi.getSymbolChart(this.routeSymbol, {
          period: this.currentPeriod,
        })
        if (
          requestId !== this.orderReviewRequestId ||
          routeToken !== this.routeToken ||
          requestKey !== this.getOrderReviewChartKey()
        ) {
          return null
        }
        this.orderReviewChart = payload || null
        this.orderReviewLoadedKey = requestKey
        this.orderReviewVersion += 1
        this.scheduleRender()
        return this.orderReviewChart
      } catch (error) {
        if (
          requestId !== this.orderReviewRequestId ||
          routeToken !== this.routeToken ||
          requestKey !== this.getOrderReviewChartKey()
        ) {
          return null
        }
        this.orderReviewChart = null
        this.orderReviewLoadedKey = ''
        this.orderReviewError = Number(error?.response?.status) === 404
          ? '订单级复盘服务未部署'
          : '交易复盘加载失败'
        this.orderReviewVersion += 1
        this.scheduleRender()
        return null
      } finally {
        if (requestId === this.orderReviewRequestId) {
          this.orderReviewLoading = false
          this.orderReviewRequestKey = ''
        }
      }
    },
    async toggleOrderReviewMode() {
      if (!this.routeSymbol) return
      this.showOrderReview = !this.showOrderReview
      this.orderReviewError = ''
      this.orderReviewVersion += 1
      this.scheduleRender()
      if (this.showOrderReview) {
        await this.loadOrderReviewChart()
      }
    },
    async retryOrderReviewChart() {
      await this.loadOrderReviewChart({ force: true })
    },
    async handleOrderReviewChartHover(params) {
      if (String(params?.seriesId || '') !== 'order-review-chart-markers') {
        return
      }
      const event = params?.data?.event
      const eventId = String(event?.event_id || '').trim()
      if (!eventId || !this.showOrderReview) {
        return
      }
      if (getOrderReviewChartConditions(eventId) !== null) {
        return
      }
      try {
        const payload = await positionReviewApi.getEventConditions(eventId)
        setOrderReviewChartConditions(eventId, payload || null)
      } catch {
        setOrderReviewChartConditions(eventId, null)
      }
      this.chart?.dispatchAction?.({
        type: 'showTip',
        seriesIndex: params.seriesIndex,
        dataIndex: params.dataIndex,
        x: params?.event?.offsetX,
        y: params?.event?.offsetY,
      })
    },
    isSidebarItemActive(item) {
      return getSidebarCode6(item) === this.activeCode6
    },
    toggleSidebarSection(sectionKey) {
      this.expandedSidebarKey = toggleSidebarExpandedKey(this.expandedSidebarKey, sectionKey)
    },
    getSidebarDeleteKey(sectionKey, item) {
      const code6 = getSidebarCode6(item)
      return code6 ? `${sectionKey}:${code6}` : ''
    },
    isSidebarDeletePending(sectionKey, item) {
      const deleteKey = this.getSidebarDeleteKey(sectionKey, item)
      return deleteKey ? !!this.sidebarDeleting[deleteKey] : false
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
      this.priceGuideEditMode = false
      this.priceGuideDragDirty = false
    },
    async togglePriceGuidePanel() {
      if (!this.routeSymbol) {
        return
      }
      if (this.showPriceGuidePanel) {
        this.closePriceGuidePanel()
        return
      }
      closeOtherPanels(this, 'showPriceGuidePanel')
      this.showPriceGuidePanel = true
      const tasks = []
      if (!this.subjectPriceDetail && !this.subjectDetailLoading) {
        tasks.push(this.loadSubjectPriceDetail({ force: true }))
      }
      if (
        !this.subjectPanelState.subjectPanelDetail ||
        this.subjectPanelState.lastSubjectSymbol !== this.routeSymbol
      ) {
        tasks.push(this.loadSubjectPanelDetail({ force: true }))
      }
      if (tasks.length) {
        await Promise.all(tasks)
      }
    },
    async loadSubjectPanelDetail({ force = false, symbol } = {}) {
      const nextSymbol = (symbol || this.routeSymbol || '').trim()
      if (!nextSymbol) {
        return false
      }
      if (
        !force &&
        this.subjectPanelState.subjectPanelDetail &&
        this.subjectPanelState.lastSubjectSymbol === nextSymbol
      ) {
        return false
      }

      const requestToken = this.routeToken
      this.subjectPanelState.subjectDetailLoading = true
      try {
        const detail = await this.subjectPanelActions.loadSubjectDetail(nextSymbol)
        if (requestToken !== this.routeToken) {
          return false
        }
        applySubjectPanelDetailState(this.subjectPanelState, detail)
        this.subjectPanelState.pageError = ''
        return true
      } catch (error) {
        if (requestToken !== this.routeToken) {
          return false
        }
        this.subjectPanelState.pageError = resolvePanelErrorMessage(error, '标的设置加载失败')
        return false
      } finally {
        if (requestToken === this.routeToken) {
          this.subjectPanelState.subjectDetailLoading = false
        }
      }
    },
    async handleSaveSubjectConfigBundle() {
      if (!this.routeSymbol || !this.subjectPanelState.subjectPanelDetail) {
        return
      }

      const parsedLimit = Number(this.subjectPanelState.positionLimitDraft.limit)
      if (!Number.isFinite(parsedLimit) || parsedLimit <= 0) {
        this.$message?.warning?.('请先填写有效的单标的上限')
        return
      }

      const mustPoolChanged = hasSubjectPanelMustPoolChanges(
        this.subjectPanelState.subjectPanelDetail,
        this.subjectPanelState.mustPoolDraft
      )
      const positionLimitChanged = hasSubjectPanelPositionLimitChanges(
        this.subjectPanelState.subjectPanelDetail,
        this.subjectPanelState.positionLimitDraft
      )
      if (!mustPoolChanged && !positionLimitChanged) {
        return
      }

      this.subjectPanelState.savingSubjectConfigBundle = true
      let mustPoolSaved = false
      try {
        if (mustPoolChanged) {
          await this.subjectPanelActions.saveMustPool(
            this.routeSymbol,
            cloneSubjectPanelMustPoolDraft(this.subjectPanelState.mustPoolDraft)
          )
          mustPoolSaved = true
        }
        if (positionLimitChanged) {
          await this.subjectPanelActions.savePositionLimit(
            this.routeSymbol,
            buildSubjectPanelPositionLimitPayload(this.subjectPanelState.positionLimitDraft)
          )
        }
        await this.loadSubjectPanelDetail({ force: true })
        this.$message?.success?.(
          mustPoolChanged && positionLimitChanged
            ? '基础配置与单标的上限已保存'
            : mustPoolChanged
              ? '基础配置已保存'
              : '单标的上限已保存'
        )
      } catch (error) {
        if (mustPoolSaved) {
          await this.loadSubjectPanelDetail({ force: true })
          this.$message?.warning?.('基础配置已保存，单标的上限保存失败')
        }
        this.subjectPanelState.pageError = resolvePanelErrorMessage(error, '标的设置保存失败')
      } finally {
        this.subjectPanelState.savingSubjectConfigBundle = false
      }
    },
    async handleSaveSubjectPositionLimit() {
      if (!this.routeSymbol || !this.subjectPanelState.subjectPanelDetail || !this.positionLimitAvailable) {
        return
      }
      const parsedLimit = Number(this.subjectPanelState.positionLimitDraft.limit)
      if (!Number.isFinite(parsedLimit) || parsedLimit <= 0) {
        this.$message?.warning?.('请先填写有效的单标的总仓位上限')
        return
      }
      this.subjectPanelState.savingSubjectConfigBundle = true
      try {
        await this.subjectPanelActions.savePositionLimit(
          this.routeSymbol,
          buildSubjectPanelPositionLimitPayload(this.subjectPanelState.positionLimitDraft)
        )
        await this.loadSubjectPanelDetail({ force: true })
        this.$message?.success?.('单标的总仓位上限已保存')
      } catch (error) {
        this.subjectPanelState.pageError = resolvePanelErrorMessage(error, '总仓位上限保存失败')
      } finally {
        this.subjectPanelState.savingSubjectConfigBundle = false
      }
    },
    async handleRestoreSubjectPositionLimitDefault() {
      if (!this.routeSymbol || !this.subjectPanelState.subjectPanelDetail || !this.positionLimitAvailable) {
        return
      }
      this.subjectPanelState.savingSubjectConfigBundle = true
      try {
        await restoreKlineSlimPositionLimitDefault(this.subjectPanelState, {
          actions: this.subjectPanelActions,
          symbol: this.routeSymbol,
          refresh: () => this.loadSubjectPanelDetail({ force: true }),
        })
        this.$message?.success?.('已恢复系统默认总仓位上限')
      } catch (error) {
        this.subjectPanelState.pageError = resolvePanelErrorMessage(error, '恢复系统默认失败')
      } finally {
        this.subjectPanelState.savingSubjectConfigBundle = false
      }
    },
    async handleSaveSubjectStoploss(entryId) {
      if (!entryId) {
        return
      }
      const draft = this.subjectPanelState.stoplossDrafts?.[entryId] || {}
      if (draft.enabled) {
        const parsedPrice = Number(draft.stop_price)
        if (!Number.isFinite(parsedPrice) || parsedPrice <= 0) {
          this.$message?.warning?.(`开启止损前请先填写 ${entryId} 的 stop_price`)
          return
        }
      }

      this.subjectPanelState.savingStoploss = {
        ...this.subjectPanelState.savingStoploss,
        [entryId]: true
      }
      try {
        await this.subjectPanelActions.saveStoploss(entryId, draft)
        await this.loadSubjectPanelDetail({ force: true })
        this.$message?.success?.(`止损已更新 ${entryId}`)
      } catch (error) {
        this.subjectPanelState.pageError = resolvePanelErrorMessage(error, '止损保存失败')
      } finally {
        this.subjectPanelState.savingStoploss = {
          ...this.subjectPanelState.savingStoploss,
          [entryId]: false
        }
      }
    },
    resetChanlunStructureState() {
      this.showChanlunStructurePanel = false
      this.chanlunStructureLoading = false
      this.chanlunStructureError = ''
      this.chanlunStructureRefreshError = ''
      this.chanlunStructureData = null
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
      if (selected && Object.prototype.hasOwnProperty.call(selected, CLX_SIGNAL_LEGEND_NAME)) {
        this.clxLegendSelected = selected[CLX_SIGNAL_LEGEND_NAME] !== false
      }
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
      const request = {
        symbol: this.routeSymbol,
        period: this.currentPeriod,
        endDate: this.endDateModel || undefined,
        realtimeCache: this.isRealtimeMode,
        barCount: DEFAULT_KLINE_SLIM_BAR_COUNT
      }
      if (!request.symbol) {
        return
      }

      const requestKey = JSON.stringify([
        request.symbol,
        request.period,
        request.endDate || '',
        !!request.realtimeCache
      ])
      if (
        this.mainLoading &&
        this.mainRequestKey === requestKey &&
        this.mainAbortController &&
        !this.mainAbortController.signal.aborted
      ) {
        return
      }

      this.mainAbortController?.abort?.()
      const requestId = ++this.mainRequestId
      const controller = new AbortController()
      this.mainRequestKey = requestKey
      this.mainAbortController = controller
      this.mainLoading = true
      const isCurrentOwner = () => (
        requestId === this.mainRequestId &&
        requestKey === this.mainRequestKey &&
        controller === this.mainAbortController &&
        token === this.routeToken
      )
      try {
        const payload = await futureApi.stockData(request, {
          signal: controller.signal
        })
        if (!isCurrentOwner() || !payload) {
          return
        }
        const nextVersion = this.cacheChanlunPeriodPayload(request.period, payload)
        if (!nextVersion) {
          return
        }
        this.mainData = payload
        this.mainVersion = nextVersion
        this.lastMainBarLabel = payload.date[payload.date.length - 1]
        this.scheduleRender()
        if (
          this.showOrderReview &&
          this.getOrderReviewChartKey() !== this.orderReviewLoadedKey
        ) {
          this.loadOrderReviewChart()
        }
      } catch (error) {
        if (isCurrentOwner() && error?.name !== 'AbortError' && !controller.signal.aborted) {
          this.lastError = '主图刷新失败'
        }
      } finally {
        if (isCurrentOwner()) {
          this.mainLoading = false
          this.mainAbortController = null
        }
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
        afterRefresh: () => this.scheduleRender(),
        effectivePositionLimit: this.effectivePositionLimit
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
    async handleSavePriceGuides() {
      return savePriceGuides(this, {
        actions: this.pricePanelActions,
        symbol: this.routeSymbol,
        notify: this.$message,
        afterRefresh: () => this.scheduleRender(),
        effectivePositionLimit: this.effectivePositionLimit
      })
    },
    async handleGuardianGuideEnabledChange(index, enabled) {
      const currentBuyEnabled = Array.isArray(this.guardianDraft?.buy_enabled)
        ? this.guardianDraft.buy_enabled.slice(0, 3).map((item) => item !== false)
        : [true, true, true]
      const nextBuyEnabled = currentBuyEnabled.slice(0, 3)
      nextBuyEnabled[index] = enabled !== false
      const previousGuardianDraft = {
        ...this.guardianDraft,
        buy_enabled: currentBuyEnabled,
        enabled: currentBuyEnabled.some(Boolean)
      }

      this.guardianDraft = {
        ...this.guardianDraft,
        buy_enabled: nextBuyEnabled,
        enabled: nextBuyEnabled.some(Boolean)
      }

      try {
        return await saveGuardianGuideEnabledState(this, {
          actions: this.pricePanelActions,
          symbol: this.routeSymbol,
          notify: this.$message,
          afterRefresh: () => this.scheduleRender(),
          nextBuyEnabled,
          effectivePositionLimit: this.effectivePositionLimit
        })
      } catch (error) {
        this.guardianDraft = previousGuardianDraft
        throw error
      }
    },
    async handleTakeprofitGuideEnabledChange(level, enabled) {
      const previousDrafts = Array.isArray(this.takeprofitDrafts)
        ? this.takeprofitDrafts.map((row) => ({ ...row }))
        : []
      const nextManualEnabled = TAKEPROFIT_GUIDE_META.map((item) => {
        const draft = this.takeprofitDrafts?.[item.level - 1]
        return Boolean(draft?.manual_enabled)
      })
      nextManualEnabled[level - 1] = enabled !== false

      this.takeprofitDrafts = TAKEPROFIT_GUIDE_META.map((item) => {
        const draft = this.takeprofitDrafts?.[item.level - 1] || {
          level: item.level,
          price: null,
          manual_enabled: true
        }
        return {
          ...draft,
          level: item.level,
          manual_enabled: nextManualEnabled[item.level - 1] !== false
        }
      })

      try {
        return await saveTakeprofitGuideEnabledState(this, {
          actions: this.pricePanelActions,
          symbol: this.routeSymbol,
          notify: this.$message,
          afterRefresh: () => this.scheduleRender(),
          nextManualEnabled
        })
      } catch (error) {
        this.takeprofitDrafts = previousDrafts
        throw error
      }
    },
    async handleGuardianGuideEnabledAll(enabled) {
      const nextBuyEnabled = [enabled !== false, enabled !== false, enabled !== false]
      const previousGuardianDraft = {
        ...this.guardianDraft,
        buy_enabled: Array.isArray(this.guardianDraft?.buy_enabled)
          ? this.guardianDraft.buy_enabled.slice(0, 3).map((item) => item !== false)
          : [true, true, true],
        enabled: Boolean(this.guardianDraft?.enabled ?? true)
      }
      const previousGuardianState = {
        ...this.guardianState,
        buy_active: Array.isArray(this.guardianState?.buy_active)
          ? this.guardianState.buy_active.slice(0, 3).map((item) => item !== false)
          : [false, false, false]
      }

      this.guardianDraft = {
        ...this.guardianDraft,
        buy_enabled: nextBuyEnabled,
        enabled: nextBuyEnabled.some(Boolean)
      }
      this.guardianState = {
        ...this.guardianState,
        buy_active: nextBuyEnabled.slice(0, 3).map((item) => item !== false)
      }

      try {
        return await saveGuardianGuideEnabledState(this, {
          actions: this.pricePanelActions,
          symbol: this.routeSymbol,
          notify: this.$message,
          afterRefresh: () => this.scheduleRender(),
          nextBuyEnabled,
          syncRuntimeState: true,
          effectivePositionLimit: this.effectivePositionLimit
        })
      } catch (error) {
        this.guardianDraft = previousGuardianDraft
        this.guardianState = previousGuardianState
        throw error
      }
    },
    async handleTakeprofitGuideEnabledAll(enabled) {
      const previousDrafts = Array.isArray(this.takeprofitDrafts)
        ? this.takeprofitDrafts.map((row) => ({ ...row }))
        : []
      const previousTakeprofitState = {
        ...this.takeprofitState,
        armed_levels: {
          ...(this.takeprofitState?.armed_levels || {})
        }
      }
      const nextManualEnabled = [enabled !== false, enabled !== false, enabled !== false]

      this.takeprofitDrafts = TAKEPROFIT_GUIDE_META.map((item) => {
        const draft = this.takeprofitDrafts?.[item.level - 1] || {
          level: item.level,
          price: null,
          manual_enabled: true
        }
        return {
          ...draft,
          level: item.level,
          manual_enabled: nextManualEnabled[item.level - 1]
        }
      })
      this.takeprofitState = {
        ...this.takeprofitState,
        armed_levels: Object.fromEntries(
          TAKEPROFIT_GUIDE_META.map((item) => [item.level, nextManualEnabled[item.level - 1] !== false])
        )
      }

      try {
        return await saveTakeprofitGuideEnabledState(this, {
          actions: this.pricePanelActions,
          symbol: this.routeSymbol,
          notify: this.$message,
          afterRefresh: () => this.scheduleRender(),
          nextManualEnabled,
          syncRuntimeState: true
        })
      } catch (error) {
        this.takeprofitDrafts = previousDrafts
        this.takeprofitState = previousTakeprofitState
        throw error
      }
    },
    handlePriceGuideDrag({ line, price } = {}) {
      if (!line || !Number.isFinite(Number(price))) {
        return
      }

      if (line.group === 'guardian' && line.key) {
        const resolvedGuardianDraft = {
          ...this.guardianDraft,
          ...resolveGuardianGuideDraft({
            guardianDraft: this.guardianDraft,
            lastPrice: this.lastMainClosePrice
          })
        }
        const nextPrice = clampGuardianGuidePrice({
          key: line.key,
          nextPrice: price,
          draft: resolvedGuardianDraft
        })
        if (this.guardianDraft?.[line.key] === nextPrice) {
          return
        }
        this.guardianDraft = {
          ...this.guardianDraft,
          [line.key]: nextPrice
        }
        this.priceGuideDragDirty = true
        return
      }

      if (line.group === 'takeprofit') {
        const level = Number(line.level)
        if (!Number.isFinite(level) || level <= 0) {
          return
        }
        const resolvedDrafts = resolveTakeprofitGuideDrafts({
          takeprofitDrafts: this.takeprofitDrafts,
          lastPrice: this.lastMainClosePrice
        })
        const nextPrice = clampTakeprofitGuidePrice({
          level,
          nextPrice: price,
          drafts: resolvedDrafts
        })
        let changed = false
        const nextDrafts = this.takeprofitDrafts.map((row) => {
          if (Number(row?.level) !== level) {
            return row
          }
          if (row?.price === nextPrice) {
            return row
          }
          changed = true
          return {
            ...row,
            price: nextPrice
          }
        })
        if (!changed) {
          return
        }
        this.takeprofitDrafts = nextDrafts
        this.priceGuideDragDirty = true
      }
    },
    async handlePriceGuideDragEnd({ line } = {}) {
      if (!line || !this.routeSymbol || !this.priceGuideDragDirty) {
        this.priceGuideDragDirty = false
        return
      }

      this.priceGuideDragDirty = false
      if (line.group === 'guardian') {
        await saveGuardianPriceGuides(this, {
          actions: this.pricePanelActions,
          symbol: this.routeSymbol,
          notify: this.$message,
          notifySuccess: false,
          afterRefresh: () => this.scheduleRender()
        })
        return
      }
      if (line.group === 'takeprofit') {
        await saveTakeprofitPriceGuides(this, {
          actions: this.pricePanelActions,
          symbol: this.routeSymbol,
          notify: this.$message,
          notifySuccess: false,
          afterRefresh: () => this.scheduleRender()
        })
      }
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
    jumpToPositionReview() {
      if (!this.routeSymbol) {
        return
      }
      this.$router.push({
        path: '/position-review',
        query: {
          symbol: this.routeSymbol,
        },
      })
    },
    formatWanAmountValue(value) {
      return formatWanAmountLabel(value)
    },
    formatAmountValue(value) {
      return formatAmountLabel(value)
    },
    formatIntegerValue(value) {
      return formatIntegerLabel(value)
    },
    formatWanQuantityValue(value) {
      return formatWanQuantityLabel(value)
    },
    formatPriceGuideValue(value) {
      return formatPriceGuideValueDisplay(value)
    }
  }
}
