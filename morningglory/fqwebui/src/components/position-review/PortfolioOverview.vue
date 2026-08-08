<script setup>
import { computed, onMounted, ref } from 'vue'

import { positionReviewApi } from '../../api/positionReviewApi.js'
import {
  buildPortfolioEquityOption,
  normalizePortfolioContributions,
  normalizePortfolioSummary,
  positionReviewRefactorFormatters,
} from '../../views/positionReviewRefactor.mjs'
import PositionReviewChart from './PositionReviewChart.vue'

const emit = defineEmits(['drill-symbol'])

const summary = ref(null)
const series = ref(null)
const contributions = ref(null)
const loading = ref(false)
const error = ref('')
const equityPeriod = ref('day')

const normalizedSummary = computed(() => normalizePortfolioSummary(summary.value || {}))
const normalizedContributions = computed(() => normalizePortfolioContributions(contributions.value || {}))
const equityOption = computed(() => buildPortfolioEquityOption(series.value || {}))

const equityBasisLabel = computed(() => {
  const basis = normalizedSummary.value.equityBasis
  if (basis === 'broker_total_asset') return '券商历史总资产'
  if (basis === 'credit_snapshot_reconstructed') return '信用资产快照重建（估算）'
  if (basis === 'estimated') return '估算权益（证据不足）'
  return basis || '—'
})

const monthlyOption = computed(() => {
  const monthly = normalizedSummary.value.monthly
  if (!monthly.length) return null
  return {
    backgroundColor: 'transparent',
    animation: false,
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value) => Number(value).toLocaleString('zh-CN'),
    },
    legend: {
      top: 4,
      textStyle: { color: '#374151' },
      data: ['买入', '卖出'],
    },
    grid: { left: 60, right: 16, top: 36, bottom: 26 },
    xAxis: {
      type: 'category',
      data: monthly.map((item) => item.month),
      axisLabel: { color: '#6b7280' },
      axisLine: { lineStyle: { color: '#d1d5db' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#6b7280' },
      splitLine: { lineStyle: { color: 'rgba(15,23,42,0.08)' } },
    },
    series: [
      { name: '买入', type: 'bar', data: monthly.map((item) => item.buy), itemStyle: { color: '#ef4444' } },
      { name: '卖出', type: 'bar', data: monthly.map((item) => item.sell), itemStyle: { color: '#22c55e' } },
    ],
  }
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

const formatKpi = (kpi) => {
  const formatter = positionReviewRefactorFormatters[kpi.kind] || positionReviewRefactorFormatters.amount
  return formatter(kpi.value)
}

const handleContributionClick = (row) => {
  if (row.symbol) {
    emit('drill-symbol', row.symbol)
  }
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
      <div class="portfolio-overview__panel-head">
        <div class="portfolio-overview__panel-title">账户净资产曲线（QMT 口径）</div>
        <div class="portfolio-overview__period-switch">
          <button
            v-for="option in [{ value: 'day', label: '日' }, { value: 'week', label: '周' }, { value: 'month', label: '月' }]"
            :key="option.value"
            type="button"
            class="portfolio-overview__period-btn"
            :class="{ 'portfolio-overview__period-btn--active': equityPeriod === option.value }"
            @click="switchEquityPeriod(option.value)"
          >
            {{ option.label }}
          </button>
        </div>
      </div>
      <p class="portfolio-overview__panel-note">
        净资产 = 总资产 − 总负债；Y 轴从净资产区间内放大（min/max 自适应），使波动更明显；日/周/月聚合取各周期末笔快照，缺失区间不插值；交易发生的周期标注交易点。
      </p>
      <PositionReviewChart
        class="portfolio-overview__hero-chart"
        :option="equityOption || {}"
        :loading="loading"
        :empty="!equityOption"
        empty-text="缺少资产快照，暂无可绘制的权益曲线"
      />
    </section>

    <section class="portfolio-overview__grid">
      <div class="portfolio-overview__panel">
        <div class="portfolio-overview__panel-title">月度成交额</div>
        <PositionReviewChart
          class="portfolio-overview__panel-chart"
          :option="monthlyOption || {}"
          :loading="loading"
          :empty="!monthlyOption"
          empty-text="暂无月度成交数据"
        />
      </div>
      <div class="portfolio-overview__panel">
        <div class="portfolio-overview__panel-title">复盘结论分布</div>
        <PositionReviewChart
          class="portfolio-overview__panel-chart"
          :option="verdictOption || {}"
          :loading="loading"
          :empty="!verdictOption"
          empty-text="暂无复盘结论"
        />
      </div>
      <div class="portfolio-overview__panel portfolio-overview__panel--wide">
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
            <el-table-column label="标的" min-width="130">
              <template #default="{ row }">
                <span class="workbench-code">{{ row.symbol }}</span>
                <span class="portfolio-overview__symbol-name">{{ row.name }}</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="86">
              <template #default="{ row }">
                <span :class="`position-review-side position-review-side--${row.isHolding ? 'holding' : 'closed'}`">
                  {{ row.isHolding ? '持仓' : '已清仓' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="市值" min-width="110" align="right">
              <template #default="{ row }">
                <span class="workbench-code">{{ positionReviewRefactorFormatters.amount(row.marketValue) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="已实现盈亏" min-width="116" align="right">
              <template #default="{ row }">
                <span class="workbench-code" :class="{ 'position-review-delta--anomaly': row.realizedPnl < 0 }">
                  {{ positionReviewRefactorFormatters.signedAmount(row.realizedPnl) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="浮动盈亏" min-width="116" align="right">
              <template #default="{ row }">
                <span class="workbench-code" :class="{ 'position-review-delta--anomaly': row.floatingPnl < 0 }">
                  {{ positionReviewRefactorFormatters.signedAmount(row.floatingPnl) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="合计盈亏" min-width="116" align="right">
              <template #default="{ row }">
                <strong
                  class="workbench-code"
                  :class="{ 'position-review-delta--anomaly': row.totalPnl < 0 }"
                >
                  {{ positionReviewRefactorFormatters.signedAmount(row.totalPnl) }}
                </strong>
              </template>
            </el-table-column>
            <el-table-column label="成本口径" min-width="140">
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

.portfolio-overview__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  min-height: 0;
}

.portfolio-overview__hero {
  display: flex;
  flex: 0 0 auto;
  flex-direction: column;
  gap: 8px;
  min-height: 360px;
  padding: 14px 16px;
  border-radius: 12px;
  background: #ffffff;
  border: 1px solid #d8dee9;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.06);
}

.portfolio-overview__hero-chart {
  flex: 1 1 auto;
  min-height: 300px;
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

.portfolio-overview__panel--wide {
  grid-column: span 2;
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

.portfolio-overview__period-switch {
  display: inline-flex;
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
