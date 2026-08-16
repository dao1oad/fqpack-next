<script setup>
import { computed, onMounted, ref } from 'vue'

import { positionReviewApi } from '../../api/positionReviewApi.js'
import {
  buildPortfolioBenchmarkSummary,
  buildPortfolioEquityOption,
  buildPortfolioTradeTooltip,
  normalizePortfolioContributions,
  normalizePortfolioSummary,
  positionReviewRefactorFormatters,
} from '../../views/positionReview.mjs'
import PositionReviewChart from './PositionReviewChart.vue'

const emit = defineEmits(['drill-symbol'])

const summary = ref(null)
const series = ref(null)
const contributions = ref(null)
const loading = ref(false)
const error = ref('')
const equityPeriod = ref('30d')
const equityMode = ref('net')
const pinnedTrade = ref(null)
const equityPeriodOptions = [
  { value: '30d', label: '30日' },
  { value: '60d', label: '60日' },
  { value: '90d', label: '90日' },
  { value: '6m', label: '半年' },
  { value: '1y', label: '一年' },
  { value: '2y', label: '两年' },
]

const normalizedSummary = computed(() => normalizePortfolioSummary(summary.value || {}))
const normalizedContributions = computed(() => normalizePortfolioContributions(contributions.value || {}))
const equityOption = computed(() => buildPortfolioEquityOption(
  series.value || {},
  equityMode.value,
  { tooltipEnabled: !pinnedTrade.value },
))
const benchmarkSummary = computed(() => buildPortfolioBenchmarkSummary(series.value || {}, equityMode.value))
const windowCoverage = computed(() => {
  const windowInfo = series.value?.data_quality?.window
  if (!windowInfo || windowInfo.covered !== false) return null
  return windowInfo
})
const tradeCardHtml = computed(() => (
  pinnedTrade.value ? buildPortfolioTradeTooltip(pinnedTrade.value) : ''
))

const equityBasisLabel = computed(() => {
  const basis = normalizedSummary.value.equityBasis
  if (basis === 'broker_total_asset') return '券商历史总资产'
  if (basis === 'credit_snapshot_reconstructed') return '信用资产快照重建（估算）'
  if (basis === 'estimated') return '估算权益（证据不足）'
  return basis || '—'
})

const verdictOption = computed(() => {
  const distribution = normalizedSummary.value.verdictDistribution
  if (!distribution.some((item) => item.value > 0)) return null
  const colors = {
    PASS: '#22c55e',
    FAIL: '#ef4444',
    INSUFFICIENT_EVIDENCE: '#f59e0b',
    NOT_APPLICABLE: '#94a3b8',
  }
  return {
    backgroundColor: 'transparent',
    animation: false,
    tooltip: { trigger: 'item' },
    legend: {
      bottom: 0,
      textStyle: { color: '#374151' },
      formatter: (name) => ({
        PASS: 'PASS 合规',
        FAIL: 'FAIL 偏离',
        INSUFFICIENT_EVIDENCE: '证据不足',
        NOT_APPLICABLE: '不适用',
      }[name] || name),
    },
    series: [{
      name: '复盘结论',
      type: 'pie',
      radius: ['42%', '66%'],
      center: ['50%', '42%'],
      label: { show: false },
      data: distribution
        .filter((item) => item.value > 0)
        .map((item) => ({ name: item.name, value: item.value, itemStyle: { color: colors[item.name] } })),
    }],
  }
})

const loadPortfolio = async ({ force = false } = {}) => {
  loading.value = true
  error.value = ''
  try {
    const [summaryResult, seriesResult, contributionResult] = await Promise.allSettled([
      positionReviewApi.getPortfolioSummary({ ...(force ? { refresh: 1 } : {}) }),
      positionReviewApi.getPortfolioSeries({
        period: equityPeriod.value,
        ...(force ? { refresh: 1 } : {}),
      }),
      positionReviewApi.getPortfolioContributions({ top_n: 10 }),
    ])
    summary.value = summaryResult.status === 'fulfilled' ? (summaryResult.value || null) : null
    series.value = seriesResult.status === 'fulfilled' ? (seriesResult.value || null) : null
    contributions.value = contributionResult.status === 'fulfilled' ? (contributionResult.value || null) : null
    if (summaryResult.status === 'rejected') {
      error.value = '组合总览加载失败'
    }
  } finally {
    loading.value = false
  }
}

const switchEquityPeriod = (period) => {
  if (equityPeriod.value === period) return
  equityPeriod.value = period
  loadPortfolio()
}

const switchEquityMode = (mode) => {
  equityMode.value = mode === 'asset' ? 'asset' : 'net'
}

const formatKpi = (kpi) => {
  const formatter = positionReviewRefactorFormatters[kpi.kind] || positionReviewRefactorFormatters.amount
  return formatter(kpi.value)
}

const handleContributionClick = (row) => {
  if (row.symbol) {
    emit('drill-symbol', row.symbol)
  }
}

const handleChartClick = (params) => {
  if (
    params?.seriesId === 'position-review-portfolio-trades'
    && params?.data?.point
  ) {
    pinnedTrade.value = params.data.point
    return
  }
  pinnedTrade.value = null
}

const closePinnedTrade = () => {
  pinnedTrade.value = null
}

onMounted(() => {
  loadPortfolio()
})

defineExpose({ reload: () => loadPortfolio({ force: true }) })
</script>

<template>
  <div class="portfolio-overview">
    <div class="portfolio-overview__error" v-if="error">
      <el-alert :title="error" type="error" :closable="false" />
    </div>

    <section class="portfolio-overview__kpis">
      <div
        v-for="kpi in normalizedSummary.kpis"
        :key="kpi.key"
        class="portfolio-overview__kpi"
        :class="{ 'portfolio-overview__kpi--signed': kpi.kind === 'signedAmount' }"
      >
        <span class="portfolio-overview__kpi-label">{{ kpi.label }}</span>
        <strong class="portfolio-overview__kpi-value">{{ formatKpi(kpi) }}</strong>
      </div>
    </section>

    <section class="portfolio-overview__quality">
      <span class="portfolio-overview__badge">权益口径：{{ equityBasisLabel }}</span>
      <span
        class="portfolio-overview__badge"
        :class="{ 'portfolio-overview__badge--warning': normalizedSummary.costBasis === 'degraded' }"
      >
        成本口径：{{ normalizedSummary.costBasis === 'degraded' ? '部分估算' : '完整账本' }}
      </span>
      <span class="portfolio-overview__badge">
        合规率：{{
          normalizedSummary.passRate == null
            ? '—'
            : `${(normalizedSummary.passRate * 100).toFixed(2)}%`
        }}（可判定 {{ normalizedSummary.reviewable }} 笔）
      </span>
      <span
        v-for="warning in normalizedSummary.warnings"
        :key="warning.code"
        class="portfolio-overview__badge portfolio-overview__badge--warning"
        :title="warning.message"
      >
        {{ warning.code }}
      </span>
    </section>

    <section class="portfolio-overview__hero">
      <div class="portfolio-overview__hero-left">
        <div class="portfolio-overview__panel-head">
          <div class="portfolio-overview__panel-title">
            {{ equityMode === 'asset' ? '账户总资产曲线' : '账户净资产曲线（QMT 口径）' }}
          </div>
          <div
            v-if="benchmarkSummary"
            class="portfolio-overview__benchmark-chip"
            :class="{ 'portfolio-overview__benchmark-chip--beat': benchmarkSummary.beat }"
          >
            区间 {{ equityMode === 'asset' ? '总资产' : '净资产' }}
            {{ benchmarkSummary.accountPct >= 0 ? '+' : '' }}{{ benchmarkSummary.accountPct.toFixed(2) }}%
            vs {{ benchmarkSummary.benchmarkName }}
            {{ benchmarkSummary.benchmarkPct >= 0 ? '+' : '' }}{{ benchmarkSummary.benchmarkPct.toFixed(2) }}%
            · {{ benchmarkSummary.beat ? '跑赢' : '跑输' }}
            {{ Math.abs(benchmarkSummary.spread).toFixed(2) }}pp
          </div>
          <div class="portfolio-overview__mode-switch">
            <button
              type="button"
              class="portfolio-overview__period-btn"
              :class="{ 'portfolio-overview__period-btn--active': equityMode === 'net' }"
              @click="switchEquityMode('net')"
            >
              净资产
            </button>
            <button
              type="button"
              class="portfolio-overview__period-btn"
              :class="{ 'portfolio-overview__period-btn--active': equityMode === 'asset' }"
              @click="switchEquityMode('asset')"
            >
              总资产
            </button>
          </div>
        </div>
        <div class="portfolio-overview__hero-toolbar">
          <div class="portfolio-overview__period-switch">
            <button
              v-for="option in equityPeriodOptions"
              :key="option.value"
              type="button"
              class="portfolio-overview__period-btn"
              :class="{ 'portfolio-overview__period-btn--active': equityPeriod === option.value }"
              @click="switchEquityPeriod(option.value)"
            >
              {{ option.label }}
            </button>
          </div>
          <p class="portfolio-overview__panel-note">
            {{
              equityMode === 'asset'
                ? '总资产 = 现金 + 证券市值 + 其他资产 − 负债；切换的是时间窗口（跨度），曲线按日采样、X 轴仅交易日；净资产与上证综指ETF 510210 归一化到同一 Y 轴（可见区间首交易日=100，半年及以上窗口首日即 2026-04-07）便于对比；窗口早于可用历史的区间不插值；点击交易点可固定查看成交明细（点击空白处关闭）。'
                : '净资产 = 总资产 − 总负债；切换的是时间窗口（跨度），曲线按日采样、X 轴仅交易日；净资产与上证综指ETF 510210 归一化到同一 Y 轴（可见区间首交易日=100，半年及以上窗口首日即 2026-04-07）便于对比；窗口早于可用历史的区间不插值；点击交易点可固定查看成交明细（点击空白处关闭）。'
            }}
          </p>
        </div>
        <el-alert
          v-if="windowCoverage"
          class="portfolio-overview__window-alert"
          type="warning"
          :closable="false"
          show-icon
          :title="`请求窗口 ${windowCoverage.window_days} 天，但账户快照历史晚于窗口起点；曲线仅覆盖可用区间，早段不做插值。`"
        />
        <PositionReviewChart
          class="portfolio-overview__hero-chart"
          :option="equityOption || {}"
          :loading="loading"
          :empty="!equityOption"
          empty-text="缺少资产快照，暂无可绘制的曲线"
          @chart-click="handleChartClick"
          @chart-blank-click="closePinnedTrade"
        />
        <div
          v-if="pinnedTrade"
          class="portfolio-overview__trade-card prt-tooltip"
        >
          <button
            type="button"
            class="portfolio-overview__trade-card-close"
            aria-label="关闭成交明细"
            @click.stop="closePinnedTrade"
          >
            ×
          </button>
          <!-- eslint-disable-next-line vue/no-v-html -->
          <div
            class="portfolio-overview__trade-card-body"
            v-html="tradeCardHtml"
          ></div>
        </div>
      </div>

      <div class="portfolio-overview__hero-right">
        <div class="portfolio-overview__panel portfolio-overview__panel--shrink">
          <div class="portfolio-overview__panel-title">复盘结论分布</div>
          <PositionReviewChart
            class="portfolio-overview__panel-chart portfolio-overview__verdict-chart"
            :option="verdictOption || {}"
            :loading="loading"
            :empty="!verdictOption"
            empty-text="暂无复盘结论"
          />
        </div>
        <div class="portfolio-overview__panel portfolio-overview__panel--grow">
          <div class="portfolio-overview__panel-title">标的贡献 Top {{ normalizedContributions.length || 10 }}</div>
          <div class="portfolio-overview__table-wrap">
            <el-table
              v-if="normalizedContributions.length"
              :data="normalizedContributions"
              stripe
              border
              height="100%"
              @row-click="handleContributionClick"
            >
              <el-table-column label="标的" min-width="120">
                <template #default="{ row }">
                  <span class="workbench-code">{{ row.symbol }}</span>
                  <span class="portfolio-overview__symbol-name">{{ row.name }}</span>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="76">
                <template #default="{ row }">
                  <span :class="`position-review-side position-review-side--${row.isHolding ? 'holding' : 'closed'}`">
                    {{ row.isHolding ? '持仓' : '已清仓' }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="市值" min-width="104" align="right">
                <template #default="{ row }">
                  <span class="workbench-code">{{ positionReviewRefactorFormatters.amount(row.marketValue) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="已实现盈亏" min-width="104" align="right">
                <template #default="{ row }">
                  <span class="workbench-code" :class="{ 'position-review-delta--anomaly': row.realizedPnl < 0 }">
                    {{ positionReviewRefactorFormatters.signedAmount(row.realizedPnl) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="浮动盈亏" min-width="104" align="right">
                <template #default="{ row }">
                  <span class="workbench-code" :class="{ 'position-review-delta--anomaly': row.floatingPnl < 0 }">
                    {{ positionReviewRefactorFormatters.signedAmount(row.floatingPnl) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="合计盈亏" min-width="104" align="right">
                <template #default="{ row }">
                  <strong
                    class="workbench-code"
                    :class="{ 'position-review-delta--anomaly': row.totalPnl < 0 }"
                  >
                    {{ positionReviewRefactorFormatters.signedAmount(row.totalPnl) }}
                  </strong>
                </template>
              </el-table-column>
              <el-table-column label="成本口径" min-width="118">
                <template #default="{ row }">
                  <span class="portfolio-overview__badge">
                    {{
                      row.costBasisSource === 'entry_slice_allocation'
                        ? '账本'
                        : row.costBasisSource === 'estimated_moving_average'
                          ? '估算'
                          : row.costBasisSource === 'broker_snapshot_estimate'
                            ? '券商均价估算'
                            : '—'
                    }}
                  </span>
                </template>
              </el-table-column>
            </el-table>
            <div v-else class="workbench-empty">
              <el-empty description="暂无标的贡献数据" :image-size="72" />
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.portfolio-overview {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  min-height: 0;
}

.portfolio-overview__kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
}

.portfolio-overview__kpi {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 14px;
  border-radius: 8px;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.portfolio-overview__kpi-label {
  color: #6b7280;
  font-size: 12px;
}

.portfolio-overview__kpi-value {
  color: #111827;
  font-size: 20px;
  font-weight: 600;
}

.portfolio-overview__kpi--signed .portfolio-overview__kpi-value {
  color: #1d4ed8;
}

.portfolio-overview__quality {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.portfolio-overview__badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  color: #475569;
  font-size: 12px;
  line-height: 18px;
}

.portfolio-overview__badge--warning {
  background: #fffbeb;
  border-color: #fde68a;
  color: #92400e;
}

.portfolio-overview__hero {
  display: flex;
  flex: 1 1 auto;
  flex-direction: row;
  gap: 12px;
  min-height: 0;
  min-width: 0;
  padding: 14px 16px;
  border-radius: 12px;
  background: #ffffff;
  border: 1px solid #d8dee9;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.06);
}

.portfolio-overview__hero-left {
  display: flex;
  flex: 1 1 0;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  min-height: 0;
  position: relative;
}

.portfolio-overview__trade-card {
  position: absolute;
  top: 12px;
  right: 16px;
  z-index: 10000000;
  max-width: 560px;
  max-height: 420px;
  overflow: auto;
  padding: 10px 12px;
  pointer-events: none;
}

.portfolio-overview__trade-card-body {
  pointer-events: auto;
}

.portfolio-overview__trade-card-close {
  position: absolute;
  top: 6px;
  right: 8px;
  width: 22px;
  height: 22px;
  border: 0;
  border-radius: 6px;
  background: rgba(148, 163, 184, 0.2);
  color: #e2e8f0;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  pointer-events: auto;
}

.portfolio-overview__trade-card-close:hover {
  background: rgba(248, 113, 113, 0.45);
}

.portfolio-overview__hero-right {
  display: flex;
  flex: 0 0 560px;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
  min-height: 0;
}

.portfolio-overview__hero-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.portfolio-overview__hero-chart {
  flex: 1 1 auto;
  min-height: 0;
}

.portfolio-overview__mode-switch {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  border-radius: 8px;
  background: #f1f5f9;
}

.portfolio-overview__panel--grow {
  flex: 1 1 auto;
  min-height: 0;
}

.portfolio-overview__panel--shrink {
  flex: 0 0 auto;
  min-height: 0;
}

.portfolio-overview__verdict-chart {
  min-height: 120px;
}

.portfolio-overview__panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 220px;
  padding: 12px;
  border-radius: 10px;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.portfolio-overview__panel-title {
  color: #1f2937;
  font-size: 13px;
  font-weight: 600;
}

.portfolio-overview__panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.portfolio-overview__benchmark-chip {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: 999px;
  background: #faf5ff;
  border: 1px solid #e9d5ff;
  color: #7c3aed;
  font-size: 12px;
  line-height: 16px;
  white-space: nowrap;
}

.portfolio-overview__benchmark-chip--beat {
  color: #16a34a;
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.portfolio-overview__window-alert {
  margin: 0;
}

.portfolio-overview__period-switch {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 2px;
  padding: 2px;
  border-radius: 8px;
  background: #f1f5f9;
}

.portfolio-overview__period-btn {
  min-width: 28px;
  padding: 3px 9px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #64748b;
  font-size: 12px;
  line-height: 16px;
  cursor: pointer;
}

.portfolio-overview__period-btn:hover {
  color: #0f172a;
}

.portfolio-overview__period-btn--active {
  background: #dbeafe;
  color: #1d4ed8;
  font-weight: 600;
}

.portfolio-overview__panel-note {
  margin: 0;
  color: #6b7280;
  font-size: 12px;
  line-height: 16px;
}

.portfolio-overview__panel-chart {
  flex: 1;
  min-height: 180px;
}

.portfolio-overview__table-wrap {
  flex: 1;
  min-height: 200px;
  overflow: auto;
}

.portfolio-overview__symbol-name {
  margin-left: 6px;
  color: #6b7280;
  font-size: 12px;
}
</style>
