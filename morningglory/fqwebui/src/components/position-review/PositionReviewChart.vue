<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  option: {
    type: Object,
    default: () => ({}),
  },
  loading: {
    type: Boolean,
    default: false,
  },
  empty: {
    type: Boolean,
    default: false,
  },
  emptyText: {
    type: String,
    default: '暂无图表数据',
  },
})

const emit = defineEmits(['chart-click'])

const chartRef = ref(null)
let chartInstance = null
let resizeObserver = null

const hasRenderableSize = () => Boolean(
  chartRef.value &&
  chartRef.value.clientWidth > 0 &&
  chartRef.value.clientHeight > 0
)

const ensureChart = () => {
  if (!hasRenderableSize()) return null
  chartInstance = echarts.getInstanceByDom(chartRef.value) || chartInstance
  if (!chartInstance || chartInstance.isDisposed?.()) {
    chartInstance = echarts.init(chartRef.value)
    chartInstance.on('click', (params) => {
      emit('chart-click', params)
    })
  }
  return chartInstance
}

const renderChart = async () => {
  await nextTick()
  const chart = ensureChart()
  if (!chart || props.empty) {
    chart?.clear()
    return
  }
  chart.setOption(props.option || {}, true)
  chart.resize()
}

const syncLoading = () => {
  const chart = ensureChart()
  if (!chart) return
  if (props.loading) {
    chart.showLoading('default', {
      text: '正在加载复盘数据…',
      color: '#409eff',
      textColor: '#606266',
      maskColor: 'rgba(255, 255, 255, 0.82)',
    })
  } else {
    chart.hideLoading()
  }
}

onMounted(() => {
  if (typeof ResizeObserver !== 'undefined' && chartRef.value) {
    resizeObserver = new ResizeObserver(() => {
      if (chartInstance) {
        chartInstance.resize()
      } else {
        renderChart()
        syncLoading()
      }
    })
    resizeObserver.observe(chartRef.value)
  }
  syncLoading()
  renderChart()
})

watch(
  () => props.option,
  () => {
    renderChart()
  },
  { deep: true },
)

watch(
  () => props.empty,
  () => {
    renderChart()
  },
)

watch(
  () => props.loading,
  () => {
    syncLoading()
  },
)

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  chartInstance?.dispose()
  chartInstance = null
})
</script>

<template>
  <div class="position-review-chart-shell">
    <div
      v-show="!empty"
      ref="chartRef"
      class="position-review-chart"
      role="img"
      aria-label="持仓复盘图表"
    />
    <div v-if="empty" class="position-review-chart-empty">
      <el-empty :description="emptyText" :image-size="72" />
    </div>
  </div>
</template>

<style scoped>
.position-review-chart-shell,
.position-review-chart {
  width: 100%;
  height: 100%;
  min-height: 0;
}

.position-review-chart-shell {
  position: relative;
}

.position-review-chart-empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
}
</style>
