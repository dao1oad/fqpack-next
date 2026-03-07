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
      </div>
    </div>

    <div class="gantt-layout">
      <aside v-if="showSidebar" class="gantt-sidebar">
        <div class="sidebar-head">板块</div>
        <div class="sidebar-list">
          <a
            v-for="item in sidebarItems"
            :key="String(item.id)"
            class="sidebar-link"
            :class="{ active: isHoveredPlate(item.id) }"
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

const dayOptions = [7, 15, 30, 45, 60, 90]
const platePalette = ['#6d1f1f', '#8b2727', '#b43434', '#cf5c3f', '#df8b3a']
const stockPalette = ['#d9d9d9', '#91d5ff', '#409eff', '#fa8c16', '#f5222d']

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

let chartInstance = null
let resizeObserver = null
let latestRequestId = 0

const isStocksMode = computed(() => props.mode === 'stocks')
const showSidebar = computed(() => props.mode === 'plates')
const sidebarItems = computed(() => {
  return showSidebar.value ? yAxisItems.value : []
})
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
    })
  }
  resizeObserver.disconnect()
  resizeObserver.observe(chartRef.value)
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

const changeWindowDays = (value) => {
  const next = normalizeWindowDays(value, internalWindowDays.value)
  if (next === internalWindowDays.value) return
  internalWindowDays.value = next
  emit('update:windowDays', next)
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

const buildPlateColor = (point) => {
  const rank = Number(point[2] || 0)
  const hotCount = Number(point[3] || 0)
  if (rank <= 1) return platePalette[0]
  if (rank <= 3) return platePalette[1]
  if (hotCount >= 8) return platePalette[2]
  if (hotCount >= 4) return platePalette[3]
  return platePalette[4]
}

const buildStockColor = (point) => {
  const streak = Number(point[2] || 0)
  const isLimit = Number(point[3] || 0) === 1
  if (isLimit && streak >= 3) return stockPalette[4]
  if (isLimit) return stockPalette[3]
  if (streak >= 3) return stockPalette[2]
  if (streak >= 2) return stockPalette[1]
  return stockPalette[0]
}

const extendSeriesForRender = (series) => {
  return (series || []).map((point) => {
    const color = showSidebar.value ? buildPlateColor(point) : buildStockColor(point)
    return [...point, color]
  })
}

const getColorValueIndex = () => {
  return showSidebar.value ? 6 : 5
}

const resolvePlateReasonText = (dateIndex, yIndex) => {
  const dateStr = (dates.value || [])[dateIndex]
  const item = (yAxisItems.value || [])[yIndex]
  if (!dateStr || !item) return ''
  return plateReasonMap.value?.[`${dateStr}|${item.id}`]?.reason_text || ''
}

const plateTooltipFormatter = (item) => {
  const dateStr = dates.value[item[0]]
  const plate = yAxisItems.value[item[1]]
  if (!dateStr || !plate) return ''
  const stockCodes = Array.isArray(item[5]) ? item[5] : []
  const reasonText = resolvePlateReasonText(item[0], item[1]) || '暂无板块理由'
  const stockLine = stockCodes.length ? stockCodes.join('、') : '暂无热门标的'
  return [
    `<div style="font-weight:600;margin-bottom:6px;">${dateStr} ${plate.name}</div>`,
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
    `<div>连续活跃天数：${item[2]}</div>`,
    `<div>${Number(item[3] || 0) === 1 ? '涨停/连板' : '活跃'}</div>`,
    `<div style="margin-top:6px;white-space:normal;line-height:1.5;">标的理由：${item[4] || '暂无标的理由'}</div>`
  ].join('')
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
    }
  }
}

const bindChartEvents = () => {
  if (!chartInstance) return
  chartInstance.off('click')
  chartInstance.off('mouseover')
  chartInstance.off('globalout')

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
    grid: {
      top: 16,
      right: 36,
      bottom: 36,
      left: isPlateMode ? 24 : 180,
      containLabel: !isPlateMode
    },
    tooltip: {
      trigger: 'item',
      confine: true,
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
        start: 0,
        end: 100,
        filterMode: 'filter'
      },
      {
        type: 'slider',
        xAxisIndex: 0,
        bottom: 6,
        height: 18,
        handleSize: 0,
        moveHandleSize: 0
      },
      {
        type: 'inside',
        yAxisIndex: 0,
        start: 0,
        end: visiblePercent,
        filterMode: 'empty'
      },
      {
        type: 'slider',
        yAxisIndex: 0,
        right: 6,
        width: 18,
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
        }
      }
    ]
  }

  chartInstance.setOption(option, true)
  bindChartEvents()
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
  yAxisItems.value = Array.isArray(chartPayload.y_axis) ? chartPayload.y_axis : []
  seriesData.value = extendSeriesForRender(chartPayload.series || [])
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
  yAxisItems.value = Array.isArray(chartPayload.y_axis) ? chartPayload.y_axis : []
  seriesData.value = extendSeriesForRender(chartPayload.series || [])
  plateReasonMap.value = {}
  clearHoverState()
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
  if (!chartInstance) return
  const option = chartInstance.getOption()
  const zoomItems = Array.isArray(option?.dataZoom) ? option.dataZoom : []
  const xZoom = zoomItems.find((item) => item?.xAxisIndex === 0) || {}
  const yZoom = zoomItems.find((item) => item?.yAxisIndex === 0) || {}
  const xSpan = Math.min(100, Math.max(10, Number(xZoom.end) - Number(xZoom.start) || 100))
  const ySpan = Math.min(100, Math.max(20, Number(yZoom.end) - Number(yZoom.start) || 100))
  chartInstance.dispatchAction({
    type: 'dataZoom',
    dataZoomIndex: 0,
    start: Math.max(0, 100 - xSpan),
    end: 100
  })
  chartInstance.dispatchAction({
    type: 'dataZoom',
    dataZoomIndex: 2,
    start: 0,
    end: ySpan
  })
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

.gantt-layout {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
}

.gantt-sidebar {
  width: 220px;
  border-right: 1px solid #ebeef5;
  background: #fafafa;
  display: flex;
  flex-direction: column;
}

.sidebar-head {
  padding: 12px 14px;
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  border-bottom: 1px solid #ebeef5;
}

.sidebar-list {
  flex: 1 1 auto;
  overflow-y: auto;
}

.sidebar-link {
  display: block;
  padding: 10px 14px;
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
