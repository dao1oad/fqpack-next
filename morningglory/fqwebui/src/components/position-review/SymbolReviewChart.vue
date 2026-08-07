<script setup>
import { computed, ref, watch } from 'vue'

import { positionReviewApi } from '../../api/positionReviewApi.js'
import { stockApi } from '../../api/stockApi.js'
import {
  buildSymbolReviewChartOption,
  normalizeSymbolChart,
  positionReviewRefactorFormatters,
} from '../../views/positionReviewRefactor.mjs'
import PositionReviewChart from './PositionReviewChart.vue'

const props = defineProps({
  symbol: {
    type: String,
    default: '',
  },
  period: {
    type: String,
    default: '5m',
  },
})

const emit = defineEmits(['fix-event'])

const kline = ref(null)
const chartPayload = ref(null)
const loading = ref(false)
const error = ref('')
const conditionsCache = ref(new Map())
let requestId = 0

const normalized = computed(() => normalizeSymbolChart(chartPayload.value || {}))

const chartOption = computed(() => (
  buildSymbolReviewChartOption({
    kline: kline.value || {},
    chart: chartPayload.value || {},
    conditionsResolver: (eventId) => conditionsCache.value.get(eventId) || null,
  })
))

const costBasisSourceLabel = computed(() => {
  const source = normalized.value.costBasis.source
  if (source === 'entry_slice_allocation') return 'entry/slice/allocation 账本'
  if (source === 'estimated_moving_average') return '成交移动加权（估算）'
  return source || '—'
})

const feesIncluded = computed(() => Boolean(normalized.value.costBasis.fees_included))

const loadChart = async ({ force = false } = {}) => {
  const symbol = String(props.symbol || '').trim()
  if (!symbol) {
    kline.value = null
    chartPayload.value = null
    return
  }
  const requestIdValue = ++requestId
  loading.value = true
  error.value = ''
  try {
    const [klinePayload, chartResult] = await Promise.allSettled([
      stockApi.stockData({
        symbol,
        period: props.period,
        ...(force ? {} : {}),
      }),
      positionReviewApi.getSymbolChart(symbol, { period: props.period }),
    ])
    if (requestIdValue !== requestId) return
    kline.value = klinePayload.status === 'fulfilled' ? (klinePayload.value || null) : null
    chartPayload.value = chartResult.status === 'fulfilled' ? (chartResult.value || null) : null
    if (chartResult.status === 'rejected') {
      error.value = Number(chartResult.reason?.response?.status) === 404
        ? '标的复盘投影暂不可用'
        : '标的复盘加载失败'
    }
  } finally {
    if (requestIdValue === requestId) {
      loading.value = false
    }
  }
}

const handleChartClick = (params) => {
  const event = params?.data?.event
  if (event?.event_id) {
    emit('fix-event', event)
  }
}

const handleChartHover = async (params) => {
  const event = params?.data?.event
  if (!event?.event_id) return
  if (conditionsCache.value.has(event.event_id)) return
  try {
    const payload = await positionReviewApi.getEventConditions(event.event_id)
    const next = new Map(conditionsCache.value)
    next.set(event.event_id, payload || null)
    conditionsCache.value = next
  } catch {
    const next = new Map(conditionsCache.value)
    next.set(event.event_id, null)
    conditionsCache.value = next
  }
}

watch(
  () => [props.symbol, props.period],
  () => {
    loadChart()
  },
  { immediate: true },
)

defineExpose({ reload: () => loadChart({ force: true }) })
</script>

<template>
  <div class="symbol-review-chart">
    <div class="symbol-review-chart__meta">
      <span class="symbol-review-chart__badge">
        成本口径：{{ costBasisSourceLabel }}
      </span>
      <span class="symbol-review-chart__badge">
        fees_included: {{ feesIncluded ? 'true' : 'false' }}
      </span>
      <span v-if="normalized.holdingCycles.length" class="symbol-review-chart__badge">
        {{ normalized.holdingCycles.length }} 个持仓周期
      </span>
      <span v-if="normalized.costBasis.realized_pnl != null" class="symbol-review-chart__badge">
        已实现盈亏：{{ positionReviewRefactorFormatters.signedAmount(normalized.costBasis.realized_pnl) }}
      </span>
    </div>
    <PositionReviewChart
      class="symbol-review-chart__canvas"
      :option="chartOption || {}"
      :loading="loading"
      :empty="Boolean(error) || !chartOption"
      :empty-text="error || '当前标的暂无可绘制的交易复盘主图'"
      @chart-click="handleChartClick"
      @chart-hover="handleChartHover"
    />
    <p class="symbol-review-chart__hint">
      红色 = 买入 / 绿色 = 卖出；形状 = 信号类型；边框/透明度 = 复盘结论；点击 marker 固定订单并查看完整证据。
    </p>
  </div>
</template>

<style scoped>
.symbol-review-chart {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
  gap: 6px;
}

.symbol-review-chart__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.symbol-review-chart__badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  color: #d1d5db;
  font-size: 12px;
  line-height: 18px;
}

.symbol-review-chart__canvas {
  flex: 1;
  min-height: 240px;
}

.symbol-review-chart__hint {
  margin: 0;
  color: #9ca3af;
  font-size: 12px;
  line-height: 16px;
}
</style>
