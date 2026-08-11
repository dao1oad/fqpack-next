<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

import {
  buildDimensionStackOption,
  buildEvidenceRingOption,
  buildIndustryBarOption,
  buildKpiItems,
  buildQuadrantOption,
  buildRiskHeatOption,
  buildScatterOption,
  buildValuationHistOption,
  fetchStats,
  normalizeStats,
} from './clxFundamentalStatsLogic.mjs'

const emit = defineEmits(['industry-filter', 'symbol-search', 'stats-ready'])

const loading = ref(false)
const error = ref('')
const latest = ref(null)
const stats = ref(null)
const statsRef = normalizeStats({})
const moreOpen = ref(false)
const fullscreen = ref(false)

const chartEls = ref({})
const charts = new Map()

const setChartEl = (key) => (el) => {
  chartEls.value[key] = el
}

const kpiItems = computed(() => buildKpiItems(stats.value || statsRef))
const gateStatus = computed(() => stats.value?.qualityGateStatus || 'passed')

const fetchStatsData = async () => {
  loading.value = true
  error.value = ''
  try {
    const result = await fetchStats()
    latest.value = result.latest
    stats.value = result.stats ? normalizeStats(result.stats) : null
    emit('stats-ready', stats.value)
    if (!result.stats) {
      error.value = 'stats 缺失：统计区不可用（列表与详情不受影响）'
    }
  } catch (err) {
    error.value = err?.message || '统计加载失败'
  } finally {
    loading.value = false
  }
}

const renderCharts = () => {
  const spec = {
    scatter: buildScatterOption({ stats: stats.value }),
    industry: buildIndustryBarOption({ stats: stats.value }),
    dimension: buildDimensionStackOption({ stats: stats.value }),
    quadrant: buildQuadrantOption({ stats: stats.value }),
    riskHeat: buildRiskHeatOption({ stats: stats.value }),
    evidenceRing: buildEvidenceRingOption({ stats: stats.value }),
    peHist: buildValuationHistOption({ stats: stats.value, kind: 'pe' }),
    pbHist: buildValuationHistOption({ stats: stats.value, kind: 'pb' }),
  }
  for (const [key, option] of Object.entries(spec)) {
    const el = chartEls.value[key]
    if (!el) continue
    let chart = charts.get(key)
    if (!chart) {
      chart = echarts.init(el)
      charts.set(key, chart)
    }
    chart.setOption(option, true)
    chart.off('click')
    chart.on('click', (params) => {
      if (key === 'industry') onIndustryClick(params)
      if (key === 'scatter') onScatterClick(params)
    })
  }
}

const onIndustryClick = (params) => {
  const industry = params?.name
  if (industry) emit('industry-filter', [industry])
}

const onScatterClick = (params) => {
  // 散点点击只写列表搜索筛选，不覆盖已选中标的（单向下钻）
  const label = params?.value?.[3] || ''
  const symbol = String(label).split(' ')[0]
  if (symbol) emit('symbol-search', symbol)
}

watch(
  () => stats.value,
  () => {
    if (stats.value) renderCharts()
  },
  { flush: 'post' },
)

watch(
  () => moreOpen.value,
  () => {
    nextTick(() => {
      if (stats.value) renderCharts()
    })
  },
)

watch(
  () => fullscreen.value,
  () => {
    nextTick(() => {
      for (const chart of charts.values()) chart.resize()
    })
  },
)

onMounted(() => {
  fetchStatsData()
})

onBeforeUnmount(() => {
  for (const chart of charts.values()) chart.dispose()
  charts.clear()
})

defineExpose({ refresh: fetchStatsData })
</script>

<template>
  <section
    class="clx-workbench-panel clx-fund-stats-panel"
    :class="{ 'clx-fund-stats-panel--fullscreen': fullscreen }"
  >
    <header class="clx-panel-head">
      <div>
        <h2>池子统计分析</h2>
        <p class="clx-panel-time">
          交易日 <strong>{{ stats?.tradeDate || latest?.tradeDate || '—' }}</strong>
          <span
            class="clx-fund-stats-gate"
            :class="`clx-fund-stats-gate--${gateStatus}`"
          >
            质量门：{{ gateStatus === 'passed' ? '通过' : '琥珀' }}
          </span>
        </p>
      </div>
      <div class="clx-panel-actions">
        <el-button size="small" :loading="loading" @click="fetchStatsData">刷新</el-button>
        <el-button size="small" @click="moreOpen = !moreOpen">
          {{ moreOpen ? '收起图表' : '更多图表' }}
        </el-button>
        <el-button size="small" @click="fullscreen = !fullscreen">
          {{ fullscreen ? '退出全屏' : '全屏' }}
        </el-button>
      </div>
    </header>

    <div v-if="loading && !stats" class="clx-panel-empty">加载中...</div>
    <div v-else-if="!stats" class="clx-panel-empty">
      {{ error || 'stats 缺失：统计区不可用（列表与详情不受影响）' }}
    </div>
    <template v-else>
      <div class="clx-fund-stats__scroll">
        <div class="clx-fund-kpis">
          <div v-for="item in kpiItems" :key="item.label" class="clx-fund-kpis__item">
            <span>{{ item.label }}</span>
            <strong>
              {{ item.ratio
                ? `${Math.round((item.value || 0) * 100)}${item.suffix || '%'}`
                : item.value ?? '—' }}
            </strong>
          </div>
        </div>

        <div class="clx-fund-chart clx-fund-chart--default">
          <div class="clx-fund-chart__title">质量 × 估值散点（又好又便宜）</div>
          <div :ref="setChartEl('scatter')" class="clx-fund-chart__canvas" />
        </div>
        <div class="clx-fund-chart clx-fund-chart--default">
          <div class="clx-fund-chart__title">行业分布（点击写入列表筛选）</div>
          <div :ref="setChartEl('industry')" class="clx-fund-chart__canvas" />
        </div>
        <div class="clx-fund-chart clx-fund-chart--default">
          <div class="clx-fund-chart__title">六维等级分布</div>
          <div :ref="setChartEl('dimension')" class="clx-fund-chart__canvas" />
        </div>

        <template v-if="moreOpen">
          <div class="clx-fund-chart">
            <div class="clx-fund-chart__title">成长 × 盈利四象限（净利增速 × 毛利率）</div>
            <div :ref="setChartEl('quadrant')" class="clx-fund-chart__canvas" />
          </div>
          <div class="clx-fund-chart">
            <div class="clx-fund-chart__title">风险热力（风险 × 行业）</div>
            <div :ref="setChartEl('riskHeat')" class="clx-fund-chart__canvas" />
          </div>
          <div class="clx-fund-chart">
            <div class="clx-fund-chart__title">证据覆盖</div>
            <div :ref="setChartEl('evidenceRing')" class="clx-fund-chart__canvas" />
          </div>
          <div class="clx-fund-chart__pair">
            <div class="clx-fund-chart">
              <div class="clx-fund-chart__title">PE 分位直方图</div>
              <div :ref="setChartEl('peHist')" class="clx-fund-chart__canvas" />
            </div>
            <div class="clx-fund-chart">
              <div class="clx-fund-chart__title">PB 分位直方图</div>
              <div :ref="setChartEl('pbHist')" class="clx-fund-chart__canvas" />
            </div>
          </div>
        </template>
      </div>
    </template>
  </section>
</template>

<style scoped>
.clx-workbench-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--fq-border-soft, #ebeef5);
  border-radius: var(--fq-radius-md, 8px);
  background: var(--fq-panel-bg, #fff);
  box-shadow: var(--fq-shadow-sm, 0 1px 2px rgba(15, 23, 42, 0.04));
}

.clx-fund-stats-panel--fullscreen {
  position: fixed;
  inset: 0;
  z-index: 1000;
  border-radius: 0;
}

.clx-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--fq-border-soft, #ebeef5);
}

.clx-panel-head h2 {
  margin: 0;
  font-size: 15px;
}

.clx-panel-time {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 6px 0 0;
  color: var(--fq-text-muted, #909399);
  font-size: 12px;
}

.clx-fund-stats-gate {
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10px;
}

.clx-fund-stats-gate--passed {
  background: var(--fq-chip-bg-success, #f0fdf4);
  color: var(--fq-status-success, #16a34a);
}

.clx-fund-stats-gate--amber {
  background: var(--fq-chip-bg-warning, #fef3c7);
  color: var(--fq-status-warning, #d97706);
}

.clx-panel-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.clx-fund-stats__scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 10px;
}

.clx-fund-kpis {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  margin-bottom: 10px;
}

.clx-fund-kpis__item {
  padding: 8px;
  border-radius: 6px;
  background: var(--fq-panel-bg-muted, #f8fafc);
  text-align: center;
}

.clx-fund-kpis__item span {
  display: block;
  color: var(--fq-text-muted, #909399);
  font-size: 11px;
}

.clx-fund-kpis__item strong {
  display: block;
  margin-top: 2px;
  font-size: 15px;
}

.clx-fund-chart {
  margin-bottom: 10px;
}

.clx-fund-chart__title {
  margin-bottom: 4px;
  color: var(--fq-text-secondary, #606266);
  font-size: 12px;
  font-weight: 600;
}

.clx-fund-chart__canvas {
  width: 100%;
  height: 180px;
}

.clx-fund-chart__pair {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.clx-panel-empty {
  padding: 16px 12px;
  color: var(--fq-text-muted, #909399);
  font-size: 12px;
  text-align: center;
}
</style>
