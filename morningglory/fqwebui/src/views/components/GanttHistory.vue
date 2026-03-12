<template>
  <div class="gantt-history" v-loading="loading">
    <div class="gantt-toolbar">
      <div class="toolbar-left">
        <el-button
          v-if="isStocksMode"
          text
          class="back-btn"
          @click="emitBack"
        >
          返回板块趋势
        </el-button>
        <span class="toolbar-title">{{ displayTitle }}</span>
      </div>

      <div class="toolbar-right">
        <el-button size="small" @click="restoreViewport">回到最新/顶部</el-button>
        <div class="window-switch">
          <button
            v-for="day in dayOptions"
            :key="day"
            type="button"
            class="window-button"
            :class="{ active: internalWindowDays === day }"
            @click="changeWindowDays(day)"
          >
            {{ day }}日
          </button>
        </div>
        <div class="color-legend">
          <div
            v-for="legend in legendItems"
            :key="legend.key"
            class="legend-item"
          >
            <span class="legend-dot" :style="{ background: legend.color }"></span>
            <span class="legend-label">{{ legend.label }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="gantt-layout">
      <aside
        v-if="showSidebar"
        class="gantt-sidebar"
        :style="{ paddingTop: `${GRID_TOP}px`, paddingBottom: `${GRID_BOTTOM}px` }"
      >
        <div class="sidebar-list">
          <a
            v-for="item in sidebarItems"
            :key="String(item.id)"
            class="sidebar-link"
            :class="{ active: isHoveredPlate(item.id) }"
            :style="{ height: `${sidebarRowHeight}px` }"
            :href="getPlateUrl(item.id)"
            target="_blank"
            rel="noopener noreferrer"
            :title="item.name"
          >
            {{ item.name }}
          </a>
        </div>
      </aside>

      <div class="gantt-chart-wrap">
        <div v-if="showEmpty" class="empty-wrap">
          <el-empty description="暂无数据" />
        </div>
        <div v-else ref="chartRef" class="gantt-chart"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { getGanttPlates, getGanttStocks } from '@/api/ganttApi'
import {
  getResetViewportWindow,
  processSeriesWithStreaks,
  streakPalettes
} from '@/views/js/gantt-history-chart.mjs'

const dayOptions = [7, 15, 30, 45, 60, 90]
const legendItems = [
  { key: 'first', label: '首次连板', color: streakPalettes[1][4] },
  { key: 'second', label: '第二次连板', color: streakPalettes[2][4] },
  { key: 'third', label: '第三次连板', color: streakPalettes[3][4] },
  { key: 'fourth', label: '第四次连板+', color: streakPalettes[4][4] }
]
const GRID_TOP = 16
const GRID_RIGHT = 36
const GRID_BOTTOM = 36
const GRID_LEFT_PLATE = 24
const GRID_LEFT_STOCK = 180
const ZOOM_SLIDER_SIZE = 18
const DEFAULT_SIDEBAR_ROW_HEIGHT = 40

const props = defineProps({
  provider: {
    type: String,
    default: 'xgb'
  },
  mode: {
    type: String,
    default: 'plates'
  },
  plateKey: {
    type: String,
    default: ''
  },
  plateName: {
    type: String,
    default: ''
  },
  windowDays: {
    type: Number,
    default: 30
  },
  title: {
    type: String,
    default: '板块趋势'
  }
})

const emit = defineEmits(['update:windowDays', 'drill-down', 'back'])

const chartRef = ref(null)
const loading = ref(false)
const internalWindowDays = ref(props.windowDays || 30)
const dates = ref([])
const yAxisItems = ref([])
const seriesData = ref([])
const plateReasonMap = ref({})
const hoveredPlateKey = ref('')
const hoveredDate = ref('')
const sidebarItems = ref([])
const sidebarRowHeight = ref(DEFAULT_SIDEBAR_ROW_HEIGHT)

let chartInstance = null
let resizeObserver = null
let latestRequestId = 0
let sidebarSyncFrameId = 0
let stockPanState = null
let stockPanFrameId = 0

const isStocksMode = computed(() => props.mode === 'stocks')
const showSidebar = computed(() => props.mode === 'plates')
const showEmpty = computed(() => {
  return !loading.value && (!dates.value.length || !yAxisItems.value.length)
})
const displayTitle = computed(() => {
  if (!isStocksMode.value) return props.title
  return props.plateName || props.plateKey || props.title
})

const normalizeWindowDays = (value, fallback = 30) => {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback
  return Math.min(90, Math.max(1, Math.floor(parsed)))
}

const normalizeApiPayload = (response) => {
  if (
    response &&
    typeof response === 'object' &&
    (
      Object.prototype.hasOwnProperty.call(response, 'status') ||
      Object.prototype.hasOwnProperty.call(response, 'headers') ||
      Object.prototype.hasOwnProperty.call(response, 'config')
    )
  ) {
    return response.data || {}
  }
  return response || {}
}

const ensureChartInstance = () => {
  if (!chartRef.value) return false
  const current = echarts.getInstanceByDom(chartRef.value)
  if (current) chartInstance = current
  if (!chartInstance || chartInstance.isDisposed?.()) {
    chartInstance = echarts.init(chartRef.value)
  }
  return true
}

const attachResizeObserver = () => {
  if (!chartRef.value) return
  if (!resizeObserver) {
    resizeObserver = new ResizeObserver(() => {
      chartInstance?.resize()
      scheduleSidebarSync()
    })
  }
  resizeObserver.disconnect()
  resizeObserver.observe(chartRef.value)
  chartRef.value.removeEventListener('mousedown', handleStockPanMouseDown, true)
  chartRef.value.addEventListener('mousedown', handleStockPanMouseDown, true)
}

const disposeChart = () => {
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
}

const clearHoverState = () => {
  hoveredPlateKey.value = ''
  hoveredDate.value = ''
}

const clearSidebarViewport = () => {
  sidebarItems.value = []
  sidebarRowHeight.value = DEFAULT_SIDEBAR_ROW_HEIGHT
}

const changeWindowDays = (value) => {
  const next = normalizeWindowDays(value, internalWindowDays.value)
  if (next === internalWindowDays.value) return
  internalWindowDays.value = next
  emit('update:windowDays', next)
  loadData()
}

const emitBack = () => {
  emit('back')
}

const isHoveredPlate = (plateKey) => {
  return String(plateKey || '') === String(hoveredPlateKey.value || '')
}

const getActiveDate = () => {
  if (hoveredDate.value) return hoveredDate.value
  const currentDates = dates.value || []
  return currentDates[currentDates.length - 1] || ''
}

const getPlateUrl = (plateKey) => {
  const normalizedPlateKey = String(plateKey || '').trim()
  if (!normalizedPlateKey) return 'javascript:void(0)'
  if (props.provider === 'jygs') {
    const dateStr = getActiveDate()
    if (!dateStr) return 'javascript:void(0)'
    return `https://www.jiuyangongshe.com/action/${dateStr}`
  }
  return `https://xuangutong.com.cn/theme/${normalizedPlateKey}`
}

const getColorValueIndex = () => {
  return showSidebar.value ? 6 : 5
}

const getStreakIndexes = () => {
  const colorIndex = getColorValueIndex()
  return {
    streakOrderIndex: colorIndex + 1,
    streakDayIndex: colorIndex + 2
  }
}

const getStreakText = (item) => {
  const { streakOrderIndex, streakDayIndex } = getStreakIndexes()
  const streakOrder = Number(item?.[streakOrderIndex] || 0)
  const streakDay = Number(item?.[streakDayIndex] || 0)
  if (!streakOrder || !streakDay) return '连板信息缺失'
  return `第${streakOrder}次连板 · 第${streakDay}天`
}

const resolvePlateReasonText = (dateIndex, yIndex) => {
  const dateStr = (dates.value || [])[dateIndex]
  const item = (yAxisItems.value || [])[yIndex]
  if (!dateStr || !item) return ''
  return plateReasonMap.value?.[`${dateStr}|${item.id}`]?.reason_text || ''
}

const formatHotStockList = (values) => {
  const items = Array.isArray(values) ? values : []
  const visible = items
    .slice(0, 10)
    .map((item) => {
      if (typeof item === 'string') return item
      const name = String(item?.name || '').trim()
      const symbol = String(item?.symbol || '').trim()
      if (name && symbol) return `${name}(${symbol})`
      return name || symbol
    })
    .filter(Boolean)
  if (!visible.length) return '暂无热门标的'
  return items.length > visible.length
    ? `${visible.join('、')} 等${items.length}只`
    : visible.join('、')
}

const plateTooltipFormatter = (item) => {
  const dateStr = dates.value[item[0]]
  const plate = yAxisItems.value[item[1]]
  if (!dateStr || !plate) return ''
  const stockCodes = Array.isArray(item[5]) ? item[5] : []
  const reasonText = resolvePlateReasonText(item[0], item[1]) || '暂无板块理由'
  const stockLine = formatHotStockList(stockCodes)
  return [
    `<div style="font-weight:600;margin-bottom:6px;">${dateStr} ${plate.name}</div>`,
    `<div>${getStreakText(item)}</div>`,
    `<div>排名：${item[2]}</div>`,
    `<div>热门标的数：${item[3]}</div>`,
    `<div>涨停数：${item[4]}</div>`,
    `<div style="margin-top:6px;white-space:normal;line-height:1.5;">板块理由：${reasonText}</div>`,
    `<div style="margin-top:6px;white-space:normal;line-height:1.5;">热门标的：${stockLine}</div>`
  ].join('')
}

const stockTooltipFormatter = (item) => {
  const dateStr = dates.value[item[0]]
  const stock = yAxisItems.value[item[1]]
  if (!dateStr || !stock) return ''
  const name = stock.name && stock.symbol ? `${stock.name}(${stock.symbol})` : (stock.name || stock.symbol)
  return [
    `<div style="font-weight:600;margin-bottom:6px;">${dateStr} ${name}</div>`,
    `<div>${getStreakText(item)}</div>`,
    `<div>连续活跃天数：${item[2]}</div>`,
    `<div>${Number(item[3] || 0) === 1 ? '涨停/连板' : '活跃'}</div>`,
    `<div style="margin-top:6px;white-space:normal;line-height:1.5;">标的理由：${item[4] || '暂无标的理由'}</div>`
  ].join('')
}

const getTooltipPosition = (point, params, dom, rect, size) => {
  const viewWidth = size?.viewSize?.[0] || 0
  const viewHeight = size?.viewSize?.[1] || 0
  const contentWidth = size?.contentSize?.[0] || 0
  const contentHeight = size?.contentSize?.[1] || 0
  const x = Math.min(point[0], viewWidth - contentWidth - 10)
  const y = Math.min(point[1] + 12, viewHeight - contentHeight - 10)
  return [Math.max(10, x), Math.max(10, y)]
}

const renderItem = (params, api) => {
  const xValue = api.value(0)
  const yValue = api.value(1)
  const coord = api.coord([xValue, yValue])
  const size = api.size([1, 1])
  if (!Array.isArray(coord) || !Array.isArray(size)) return null
  const width = Math.max(size[0] - 2, 8)
  const height = Math.max(size[1] * 0.72, 10)
  const color = api.value(getColorValueIndex()) || '#d9d9d9'
  return {
    type: 'rect',
    shape: {
      x: coord[0] - width / 2,
      y: coord[1] - height / 2,
      width,
      height,
      r: 2
    },
    style: {
      fill: color,
      stroke: '#f5f7fa',
      lineWidth: 1
    },
    styleEmphasis: {
      stroke: '#1f2d3d',
      lineWidth: 1
    }
  }
}

const resolvePlateIdFromAxisPointerValue = (value) => {
  if (value == null || !showSidebar.value) return ''
  if (typeof value === 'number' && Number.isFinite(value)) {
    const item = yAxisItems.value[Math.round(value)]
    return String(item?.id || '')
  }
  const normalizedValue = String(value).trim()
  if (!normalizedValue) return ''
  const item = yAxisItems.value.find((candidate) => {
    return (
      String(candidate?.id || '') === normalizedValue ||
      String(candidate?.name || '') === normalizedValue
    )
  })
  return String(item?.id || normalizedValue)
}

const updateHoveredDateFromAxisPointer = (value) => {
  if (value == null) return
  if (typeof value === 'number' && Number.isFinite(value)) {
    const dateStr = dates.value[Math.round(value)]
    if (dateStr) hoveredDate.value = dateStr
    return
  }
  const dateStr = String(value).trim()
  if (dateStr) hoveredDate.value = dateStr
}

const isChartAlive = () => {
  return Boolean(chartInstance && !chartInstance.isDisposed?.())
}

const syncPlateSidebarFromChart = () => {
  if (!showSidebar.value) {
    clearSidebarViewport()
    return
  }

  const allItems = yAxisItems.value || []
  if (!allItems.length) {
    clearSidebarViewport()
    return
  }

  let startPct = 0
  let endPct = 100
  try {
    const option = chartInstance?.getOption?.()
    const zoomItems = Array.isArray(option?.dataZoom) ? option.dataZoom : []
    const yZoom = zoomItems.find((item) => item?.yAxisIndex === 0 && Number.isFinite(item?.start) && Number.isFinite(item?.end))
    if (yZoom) {
      startPct = Number(yZoom.start)
      endPct = Number(yZoom.end)
    }
  } catch (error) {
    // ignore transient dispose/race errors
  }

  if (!Number.isFinite(startPct)) startPct = 0
  if (!Number.isFinite(endPct)) endPct = 100
  if (endPct < startPct) [startPct, endPct] = [endPct, startPct]
  startPct = Math.max(0, Math.min(100, startPct))
  endPct = Math.max(0, Math.min(100, endPct))

  const total = allItems.length
  const startIdx = Math.max(0, Math.floor((startPct / 100) * total))
  const endIdx = Math.min(total - 1, Math.max(startIdx, Math.ceil((endPct / 100) * total) - 1))
  const visibleItems = allItems.slice(startIdx, endIdx + 1)

  sidebarItems.value = visibleItems

  const chartHeight = chartRef.value?.clientHeight || 0
  const usableHeight = Math.max(0, chartHeight - GRID_TOP - GRID_BOTTOM)
  const visibleCount = visibleItems.length || 1
  sidebarRowHeight.value = usableHeight > 0
    ? Math.max(24, usableHeight / visibleCount)
    : DEFAULT_SIDEBAR_ROW_HEIGHT
}

const scheduleSidebarSync = () => {
  if (!showSidebar.value) {
    clearSidebarViewport()
    return
  }
  if (sidebarSyncFrameId) {
    window.cancelAnimationFrame(sidebarSyncFrameId)
  }
  sidebarSyncFrameId = window.requestAnimationFrame(() => {
    sidebarSyncFrameId = 0
    syncPlateSidebarFromChart()
  })
}

const getGridRect = () => {
  if (!isChartAlive()) return null
  try {
    const gridModel = chartInstance.getModel?.().getComponent?.('grid', 0)
    const rect = gridModel?.coordinateSystem?.getRect?.()
    const x = rect?.x
    const y = rect?.y
    const width = rect?.width
    const height = rect?.height
    if (Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(width) && width > 0 && Number.isFinite(height) && height > 0) {
      return { x, y, width, height }
    }
  } catch (error) {
    // ignore transient chart lifecycle errors
  }
  return null
}

const getGridPixelSize = () => {
  const gridRect = getGridRect()
  if (gridRect) return { width: gridRect.width, height: gridRect.height }

  const chartWidth = chartRef.value?.clientWidth || 0
  const chartHeight = chartRef.value?.clientHeight || 0
  return {
    width: Math.max(1, chartWidth - GRID_LEFT_STOCK - GRID_RIGHT),
    height: Math.max(1, chartHeight - GRID_TOP - GRID_BOTTOM)
  }
}

const getChartZoomRanges = () => {
  if (!isChartAlive()) return null
  try {
    const option = chartInstance.getOption()
    const zoomItems = Array.isArray(option?.dataZoom) ? option.dataZoom : []
    const xZoom = zoomItems.find((item) => item?.xAxisIndex === 0) || {}
    const yZoom = zoomItems.find((item) => item?.yAxisIndex === 0) || {}
    return {
      xStart: Number.isFinite(xZoom.start) ? xZoom.start : 0,
      xEnd: Number.isFinite(xZoom.end) ? xZoom.end : 100,
      yStart: Number.isFinite(yZoom.start) ? yZoom.start : 0,
      yEnd: Number.isFinite(yZoom.end) ? yZoom.end : 100
    }
  } catch (error) {
    return null
  }
}

const shiftZoomRange = (start, end, delta) => {
  const span = end - start
  if (!Number.isFinite(span) || span <= 0) {
    return { start, end }
  }

  let nextStart = start + delta
  let nextEnd = end + delta
  if (nextStart < 0) {
    nextStart = 0
    nextEnd = span
  } else if (nextEnd > 100) {
    nextEnd = 100
    nextStart = 100 - span
  }

  return {
    start: Math.max(0, Math.min(100, nextStart)),
    end: Math.max(0, Math.min(100, nextEnd))
  }
}

const isInZoomSliderArea = (localX, localY, width, height) => {
  return localY >= height - ZOOM_SLIDER_SIZE - 4 || localX >= width - ZOOM_SLIDER_SIZE - 4
}

const handleStockPanMouseMove = (evt) => {
  if (!stockPanState) return
  stockPanState.lastX = evt.clientX
  stockPanState.lastY = evt.clientY
  if (stockPanFrameId) return

  stockPanFrameId = window.requestAnimationFrame(() => {
    stockPanFrameId = 0
    if (!stockPanState || !isChartAlive()) return

    const dx = stockPanState.lastX - stockPanState.startX
    const dy = stockPanState.lastY - stockPanState.startY
    const xSpan = stockPanState.xEnd - stockPanState.xStart
    const ySpan = stockPanState.yEnd - stockPanState.yStart
    const deltaX = -((dx / Math.max(1, stockPanState.gridWidth)) * xSpan)
    const deltaY = ((dy / Math.max(1, stockPanState.gridHeight)) * ySpan)
    const xRange = shiftZoomRange(stockPanState.xStart, stockPanState.xEnd, deltaX)
    const yRange = shiftZoomRange(stockPanState.yStart, stockPanState.yEnd, deltaY)

    try {
      chartInstance.dispatchAction({ type: 'dataZoom', dataZoomIndex: 0, start: xRange.start, end: xRange.end })
      chartInstance.dispatchAction({ type: 'dataZoom', dataZoomIndex: 2, start: yRange.start, end: yRange.end })
      chartInstance.dispatchAction({ type: 'hideTip' })
    } catch (error) {
      // ignore transient dispose/race errors
    }
  })

  evt.preventDefault()
}

const handleStockPanMouseUp = () => {
  if (stockPanFrameId) {
    window.cancelAnimationFrame(stockPanFrameId)
    stockPanFrameId = 0
  }
  if (chartRef.value) {
    chartRef.value.style.cursor = ''
  }
  stockPanState = null
  window.removeEventListener('mousemove', handleStockPanMouseMove, true)
  window.removeEventListener('mouseup', handleStockPanMouseUp, true)
}

const handleStockPanMouseDown = (evt) => {
  if (!isStocksMode.value || !isChartAlive()) return
  if (evt.button !== 0) return

  const chartEl = chartRef.value
  if (!chartEl) return

  const rect = chartEl.getBoundingClientRect()
  const localX = evt.clientX - rect.left
  const localY = evt.clientY - rect.top
  if (isInZoomSliderArea(localX, localY, rect.width, rect.height)) return

  const gridRect = getGridRect()
  if (gridRect) {
    const inGridX = localX >= gridRect.x && localX <= gridRect.x + gridRect.width
    const inGridY = localY >= gridRect.y && localY <= gridRect.y + gridRect.height
    if (inGridX && inGridY) return
  } else {
    const guessInGridX = localX >= GRID_LEFT_STOCK && localX <= rect.width - GRID_RIGHT
    const guessInGridY = localY >= GRID_TOP && localY <= rect.height - GRID_BOTTOM
    if (guessInGridX && guessInGridY) return
  }

  const zoomRanges = getChartZoomRanges()
  if (!zoomRanges) return
  const gridSize = getGridPixelSize()
  stockPanState = {
    startX: evt.clientX,
    startY: evt.clientY,
    lastX: evt.clientX,
    lastY: evt.clientY,
    xStart: zoomRanges.xStart,
    xEnd: zoomRanges.xEnd,
    yStart: zoomRanges.yStart,
    yEnd: zoomRanges.yEnd,
    gridWidth: gridSize.width,
    gridHeight: gridSize.height
  }

  chartEl.style.cursor = 'grabbing'
  try {
    chartInstance.dispatchAction({ type: 'hideTip' })
  } catch (error) {
    // ignore transient chart lifecycle errors
  }

  window.addEventListener('mousemove', handleStockPanMouseMove, true)
  window.addEventListener('mouseup', handleStockPanMouseUp, true)
  evt.preventDefault()
}

const bindChartEvents = () => {
  if (!chartInstance) return
  chartInstance.off('click')
  chartInstance.off('dataZoom')
  chartInstance.off('updateAxisPointer')
  chartInstance.off('mouseover')
  chartInstance.off('globalout')

  chartInstance.on('updateAxisPointer', (event) => {
    if (!showSidebar.value) return
    const axesInfo = Array.isArray(event?.axesInfo) ? event.axesInfo : []
    const yInfo = axesInfo.find((item) => item?.axisDim === 'y')
    const xInfo = axesInfo.find((item) => item?.axisDim === 'x')
    hoveredPlateKey.value = resolvePlateIdFromAxisPointerValue(yInfo?.value)
    updateHoveredDateFromAxisPointer(xInfo?.value)
  })

  chartInstance.on('mouseover', (params) => {
    if (!Array.isArray(params?.data)) return
    const point = params.data
    const dateStr = dates.value[point[0]]
    const item = yAxisItems.value[point[1]]
    if (dateStr) hoveredDate.value = dateStr
    if (item?.id) hoveredPlateKey.value = item.id
  })

  chartInstance.on('globalout', () => {
    clearHoverState()
  })

  chartInstance.on('dataZoom', () => {
    scheduleSidebarSync()
  })

  if (!showSidebar.value) return
  chartInstance.on('click', (params) => {
    if (!Array.isArray(params?.data)) return
    const point = params.data
    const item = yAxisItems.value[point[1]]
    if (!item?.id) return
    emit('drill-down', {
      plateKey: item.id,
      plateName: item.name,
      days: internalWindowDays.value
    })
  })
}

const renderChart = () => {
  if (!ensureChartInstance()) return
  if (!dates.value.length || !yAxisItems.value.length) {
    chartInstance.clear()
    clearSidebarViewport()
    return
  }

  const isPlateMode = showSidebar.value
  const yAxisLabels = isPlateMode
    ? yAxisItems.value.map((item) => item.id)
    : yAxisItems.value.map((item) => {
        if (item.name && item.symbol) return `${item.name}(${item.symbol})`
        return item.name || item.symbol
      })

  const visiblePercent = Math.min(100, Math.max(35, (12 / Math.max(yAxisItems.value.length, 1)) * 100))
  const option = {
    animation: false,
    axisPointer: {
      link: [{ xAxisIndex: 'all' }],
      label: { show: false },
      snap: false
    },
    grid: {
      top: GRID_TOP,
      right: GRID_RIGHT,
      bottom: GRID_BOTTOM,
      left: isPlateMode ? GRID_LEFT_PLATE : GRID_LEFT_STOCK,
      containLabel: !isPlateMode
    },
    tooltip: {
      trigger: 'item',
      confine: true,
      position: (point, params, dom, rect, size) => getTooltipPosition(point, params, dom, rect, size),
      formatter: (params) => {
        const point = params?.data
        if (!Array.isArray(point)) return ''
        return isPlateMode ? plateTooltipFormatter(point) : stockTooltipFormatter(point)
      }
    },
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: 0,
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
        moveOnMouseWheel: true,
        preventDefaultMouseMove: true,
        start: 0,
        end: 100,
        filterMode: 'filter'
      },
      {
        type: 'slider',
        xAxisIndex: 0,
        bottom: 6,
        height: ZOOM_SLIDER_SIZE,
        borderColor: '#dcdfe6',
        fillerColor: 'rgba(64, 158, 255, 0.2)',
        handleSize: 0,
        moveHandleSize: 0
      },
      {
        type: 'inside',
        yAxisIndex: 0,
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
        moveOnMouseWheel: true,
        preventDefaultMouseMove: true,
        start: 0,
        end: visiblePercent,
        filterMode: 'empty'
      },
      {
        type: 'slider',
        yAxisIndex: 0,
        right: 6,
        width: ZOOM_SLIDER_SIZE,
        borderColor: '#dcdfe6',
        fillerColor: 'rgba(64, 158, 255, 0.2)',
        handleSize: 0,
        moveHandleSize: 0
      }
    ],
    xAxis: {
      type: 'category',
      data: dates.value,
      boundaryGap: true,
      axisTick: { alignWithLabel: true },
      axisLabel: { interval: 0 }
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: yAxisLabels,
      splitArea: {
        show: true,
        areaStyle: { color: ['#ffffff', '#fafafa'] }
      },
      axisPointer: {
        show: showSidebar.value,
        type: 'shadow',
        shadowStyle: {
          color: 'rgba(64, 158, 255, 0.18)'
        },
        label: { show: false }
      },
      axisLabel: {
        show: !isPlateMode,
        width: 150,
        overflow: 'truncate'
      }
    },
    series: [
      {
        type: 'custom',
        renderItem,
        data: seriesData.value,
        encode: {
          x: 0,
          y: 1
        },
        emphasis: { focus: 'self' }
      }
    ]
  }

  chartInstance.setOption(option, true)
  bindChartEvents()
  scheduleSidebarSync()
}

const loadPlateData = async (requestId) => {
  const response = await getGanttPlates({
    provider: props.provider,
    days: internalWindowDays.value
  })
  if (requestId !== latestRequestId) return
  const payload = normalizeApiPayload(response)
  const chartPayload = payload.data || {}
  dates.value = Array.isArray(chartPayload.dates) ? chartPayload.dates : []
  const processed = processSeriesWithStreaks({
    dates: dates.value,
    yAxisRaw: Array.isArray(chartPayload.y_axis) ? chartPayload.y_axis : [],
    seriesData: chartPayload.series || [],
    level: 'plate'
  })
  yAxisItems.value = processed.yAxisRaw
  seriesData.value = processed.seriesData
  plateReasonMap.value = payload.meta?.reason_map || {}
  clearHoverState()
  await nextTick()
  attachResizeObserver()
  renderChart()
}

const loadStockData = async (requestId) => {
  const response = await getGanttStocks({
    provider: props.provider,
    plateKey: props.plateKey,
    days: internalWindowDays.value
  })
  if (requestId !== latestRequestId) return
  const payload = normalizeApiPayload(response)
  const chartPayload = payload.data || {}
  dates.value = Array.isArray(chartPayload.dates) ? chartPayload.dates : []
  const processed = processSeriesWithStreaks({
    dates: dates.value,
    yAxisRaw: Array.isArray(chartPayload.y_axis) ? chartPayload.y_axis : [],
    seriesData: chartPayload.series || [],
    level: 'stock'
  })
  yAxisItems.value = processed.yAxisRaw
  seriesData.value = processed.seriesData
  plateReasonMap.value = {}
  clearHoverState()
  clearSidebarViewport()
  await nextTick()
  attachResizeObserver()
  renderChart()
}

const loadData = async () => {
  latestRequestId += 1
  const requestId = latestRequestId
  loading.value = true
  try {
    if (showSidebar.value) {
      await loadPlateData(requestId)
    } else if (props.plateKey) {
      await loadStockData(requestId)
    } else {
      dates.value = []
      yAxisItems.value = []
      seriesData.value = []
      plateReasonMap.value = {}
      clearHoverState()
      clearSidebarViewport()
      renderChart()
    }
  } catch (error) {
    console.error(error)
    ElMessage.error(showSidebar.value ? '加载板块趋势失败' : '加载板块个股趋势失败')
  } finally {
    if (requestId === latestRequestId) {
      loading.value = false
    }
  }
}

const restoreViewport = () => {
  if (!isChartAlive()) return
  try {
    const option = chartInstance.getOption()
    const zoomItems = Array.isArray(option?.dataZoom) ? option.dataZoom : []
    const xZoom = zoomItems.find((item) => item?.xAxisIndex === 0) || {}
    const yZoom = zoomItems.find((item) => item?.yAxisIndex === 0) || {}
    const resetWindow = getResetViewportWindow(xZoom, yZoom)
    chartInstance.dispatchAction({
      type: 'dataZoom',
      dataZoomIndex: 0,
      start: resetWindow.xStart,
      end: resetWindow.xEnd
    })
    chartInstance.dispatchAction({
      type: 'dataZoom',
      dataZoomIndex: 2,
      start: resetWindow.yStart,
      end: resetWindow.yEnd
    })
  } catch (error) {
    // ignore transient dispose/race errors
  }
  scheduleSidebarSync()
}

watch(
  () => props.windowDays,
  (value) => {
    const next = normalizeWindowDays(value, internalWindowDays.value)
    if (next === internalWindowDays.value) return
    internalWindowDays.value = next
    loadData()
  }
)

watch(
  () => [props.provider, props.mode, props.plateKey],
  () => {
    loadData()
  }
)

onMounted(() => {
  ensureChartInstance()
  attachResizeObserver()
  nextTick(() => {
    loadData()
  })
})

onBeforeUnmount(() => {
  if (sidebarSyncFrameId) {
    window.cancelAnimationFrame(sidebarSyncFrameId)
    sidebarSyncFrameId = 0
  }
  handleStockPanMouseUp()
  chartRef.value?.removeEventListener('mousedown', handleStockPanMouseDown, true)
  resizeObserver?.disconnect()
  resizeObserver = null
  disposeChart()
})
</script>

<style scoped>
.gantt-history {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: calc(100vh - 124px);
  background: #fff;
}

.gantt-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  border-bottom: 1px solid #ebeef5;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.toolbar-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.back-btn {
  padding: 0;
}

.window-switch {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.window-button {
  min-width: 52px;
  padding: 6px 10px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  background: #fff;
  color: #606266;
  cursor: pointer;
}

.window-button.active {
  border-color: #409eff;
  background: #ecf5ff;
  color: #409eff;
}

.color-legend {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #606266;
}

.legend-dot {
  width: 14px;
  height: 14px;
  border-radius: 4px;
  display: inline-block;
  border: 1px solid rgba(0, 0, 0, 0.06);
}

.legend-label {
  white-space: nowrap;
}

.gantt-layout {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
}

.gantt-sidebar {
  width: 220px;
  border-right: 1px solid #ebeef5;
  background: #fafafa;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sidebar-list {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow-x: hidden;
  overflow-y: auto;
}

.sidebar-link {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  padding: 0 14px;
  min-height: 24px;
  box-sizing: border-box;
  color: #409eff;
  text-decoration: none;
  border-bottom: 1px solid rgba(0, 0, 0, 0.04);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sidebar-link.active {
  background: rgba(64, 158, 255, 0.12);
  box-shadow: inset 3px 0 0 #409eff;
}

.sidebar-link:hover {
  background: rgba(64, 158, 255, 0.08);
}

.gantt-chart-wrap {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  position: relative;
}

.gantt-chart {
  width: 100%;
  height: 100%;
  min-height: calc(100vh - 190px);
}

.empty-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  min-height: 320px;
}

@media (max-width: 900px) {
  .gantt-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .toolbar-right {
    width: 100%;
    justify-content: flex-start;
  }

  .gantt-layout {
    flex-direction: column;
  }

  .gantt-sidebar {
    width: 100%;
    max-height: 180px;
  }

  .gantt-chart {
    min-height: 420px;
  }
}
</style>
