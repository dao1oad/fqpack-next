import test from 'node:test'
import assert from 'node:assert/strict'
import * as echarts from 'echarts'

import {
  buildFullMarkerTooltip,
  buildMarkerTooltip,
  buildPortfolioBenchmarkSummary,
  buildPortfolioTradeTooltip,
  buildPortfolioEquityOption,
  buildSymbolCostChartOption,
  buildSymbolReviewChartOption,
  normalizeConditions,
  normalizePortfolioContributions,
  normalizePortfolioSummary,
  normalizeSymbolChart,
} from './positionReview.mjs'

const makeKline = () => ({
  symbol: '002262',
  name: '恩华药业',
  date: [
    '2026-03-16 09:30:00',
    '2026-03-16 09:35:00',
    '2026-03-16 09:40:00',
    '2026-03-16 09:45:00',
  ],
  open: [10, 10.02, 10.04, 10.06],
  close: [10.02, 10.04, 10.06, 10.08],
  low: [9.98, 10, 10.02, 10.04],
  high: [10.04, 10.06, 10.08, 10.1],
})

const makeChart = () => ({
  order_events: [
    {
      event_id: 'order-buy',
      side: 'buy',
      event_type: 'filled_order',
      signal: { label: '反转买点', type: 'buy_v_reverse', family: 'reversal' },
      execution: {
        actual_quantity: 10000,
        avg_filled_price: 10.27,
        fill_count: 3,
        first_fill_time: '2026-03-16T09:35:00+08:00',
        last_fill_time: '2026-03-16T09:40:00+08:00',
      },
      position_impact: { position_before: 0, position_after: 10000 },
      review: { verdict: 'PASS' },
      marker: { bar_time: '2026-03-16T09:35:00+08:00', price: 10.27, symbol: 'triangle' },
      conditions: { count: 2, condition_snapshot_status: 'complete', threshold_missing_count: 0 },
      data_quality: { warnings: [] },
    },
    {
      event_id: 'order-sell',
      side: 'sell',
      event_type: 'filled_order',
      signal: { label: '止盈卖点', type: 'sell_takeprofit', family: 'takeprofit' },
      execution: {
        actual_quantity: 4000,
        avg_filled_price: 10.35,
        fill_count: 1,
        first_fill_time: '2026-03-16T09:45:00+08:00',
        last_fill_time: '2026-03-16T09:45:00+08:00',
      },
      position_impact: { position_before: 10000, position_after: 6000 },
      review: { verdict: 'FAIL' },
      marker: { bar_time: '2026-03-16T09:45:00+08:00', price: 10.35, symbol: 'path://M0,18 L10,0 L-10,0 Z' },
      conditions: { count: 6, condition_snapshot_status: 'complete', threshold_missing_count: 0 },
      data_quality: { warnings: [] },
    },
  ],
  cost_basis_series: [
    { time: '2026-03-16T09:35:00+08:00', average_cost: 10.27 },
    { time: '2026-03-16T09:45:00+08:00', average_cost: 10.27 },
  ],
})

test('normalizePortfolioSummary maps kpis, verdicts and signal types', () => {
  const normalized = normalizePortfolioSummary({
    kpis: {
      total_asset: 67100.9,
      net_value: 65400.0,
      market_value: 62100.0,
      remaining_cost: 61620.0,
      floating_pnl: 480.0,
      realized_pnl: -320.5,
      position_ratio: 0.925,
      cash: 5000.9,
    },
    monthly_turnover: [{ month: '2026-07', buy: 68965.0, sell: 46424.0 }],
    verdict_counts: { PASS: 2, FAIL: 1 },
    signal_type_counts: { buy_v_reverse: 1, unknown: 2 },
    reviewable: 3,
    pass_rate: 0.666667,
    data_quality: {
      equity_basis: 'broker_total_asset',
      cost_basis: 'degraded',
      warnings: [{ code: 'cost_basis_degraded_symbols' }],
    },
  })
  assert.equal(normalized.kpis.find((item) => item.key === 'totalAsset').value, 67100.9)
  assert.equal(normalized.kpis.find((item) => item.key === 'netValue').value, 65400.0)
  assert.equal(normalized.kpis.find((item) => item.key === 'floatingPnl').kind, 'signedAmount')
  assert.equal(normalized.verdictDistribution.length, 4)
  assert.equal(normalized.signalTypeDistribution[0].label, '反转买点')
  assert.equal(normalized.equityBasis, 'broker_total_asset')
})

test('buildPortfolioEquityOption renders net value with period buckets and trade points', () => {
  const option = buildPortfolioEquityOption({
    label: '账户净资产（信用资产快照重建）',
    equity_basis: 'credit_snapshot_reconstructed',
    period: 'day',
    series: [
      {
        time: '2026-07-21T12:17',
        period_label: '2026-07-21',
        total_equity: 5196064.04,
        net_value: 3558338.87,
        estimated_equity: 3558338.87,
        trades: [
          { time: '2026-07-21T13:00+08:00', symbol: '002262', name: '恩华药业', side: 'buy', quantity: 4000, price: 10.26, amount: 41040.0 },
        ],
        trade_count: 1,
      },
      {
        time: '2026-07-22T13:00',
        period_label: '2026-07-22',
        total_equity: null,
        net_value: 3600000.0,
        estimated_equity: 3600000.0,
        trades: [],
        trade_count: 0,
      },
    ],
  })
  assert.ok(option)
  assert.equal(option.series[0].name, '账户净资产')
  assert.equal(option.xAxis.data.length, 2)
  assert.equal(option.xAxis.data[0], '07-21')
  const tradeSeries = option.series.find((item) => item.id === 'position-review-portfolio-trades')
  assert.ok(tradeSeries)
  assert.equal(tradeSeries.data.length, 1)
  assert.equal(tradeSeries.data[0].trades[0].symbol, '002262')
})

test('buildPortfolioEquityOption splits net and total-asset modes with own y-axis data', () => {
  const payload = {
    period: 'day',
    series: [
      { time: '2026-07-21', period_label: '2026-07-21', total_equity: 5196064.04, net_value: 3558338.87 },
      { time: '2026-07-22', period_label: '2026-07-22', total_equity: 5200000.0, net_value: 3600000.0 },
    ],
  }
  const net = buildPortfolioEquityOption(payload, 'net')
  const asset = buildPortfolioEquityOption(payload, 'asset')
  assert.ok(net)
  assert.ok(asset)
  // 净资产模式：只有一条主曲线 + 交易点，无总资产线。
  assert.equal(net.series[0].name, '账户净资产')
  assert.deepEqual(net.series[0].data, [3558338.87, 3600000.0])
  assert.equal(net.series.some((item) => item.name === '总资产'), false)
  // 总资产模式：只有总资产曲线，不渲染交易点。
  assert.equal(asset.series[0].name, '总资产')
  assert.deepEqual(asset.series[0].data, [5196064.04, 5200000.0])
  assert.equal(asset.series.length, 1)
  // 各自 Y 轴独立（min/max 数据自适应）。
  assert.equal(net.yAxis.min, 'dataMin')
  assert.equal(net.yAxis.max, 'dataMax')
  assert.equal(asset.yAxis.min, 'dataMin')
  assert.equal(asset.yAxis.max, 'dataMax')
})

test('buildPortfolioEquityOption renders 510210 benchmark on second axis', () => {
  const option = buildPortfolioEquityOption({
    period: '30d',
    series: [
      { time: '2026-08-12', period_label: '2026-08-12', total_equity: 100000.0, net_value: 90000.0 },
      { time: '2026-08-13', period_label: '2026-08-13', total_equity: 102000.0, net_value: 91800.0 },
    ],
    benchmark: {
      code: '510210',
      name: '上证综指ETF',
      series: [
        { period_label: '2026-08-12', close: 1.01 },
        { period_label: '2026-08-13', close: 1.02 },
      ],
    },
  }, 'net')
  assert.ok(option)
  // 两条曲线归一化到同一 Y 轴（起点=100）便于对比。
  assert.equal(typeof option.yAxis, 'object')
  assert.equal(option.yAxis.name, '起点=100')
  const benchmark = option.series.find((item) => item.id === 'position-review-benchmark')
  assert.ok(benchmark)
  assert.equal(benchmark.yAxisIndex, undefined)
  assert.deepEqual(benchmark.data, [100, 100.9901])
  const account = option.series[0]
  assert.deepEqual(account.data, [100, 102])
  assert.ok(option.legend.data.includes('上证综指ETF 510210'))
})

test('buildPortfolioEquityOption normalizes trade scatter onto benchmark axis', () => {
  const option = buildPortfolioEquityOption({
    period: '30d',
    series: [
      {
        time: '2026-08-12', period_label: '2026-08-12',
        total_equity: 100000.0, net_value: 90000.0,
        trades: [{ time: '2026-08-12T10:00+08:00', symbol: '300760', side: 'buy', quantity: 100, price: 153.0 }],
        trade_count: 1,
      },
      { time: '2026-08-13', period_label: '2026-08-13', total_equity: 102000.0, net_value: 91800.0 },
    ],
    benchmark: {
      code: '510210',
      name: '上证综指ETF',
      series: [
        { period_label: '2026-08-12', close: 1.01 },
        { period_label: '2026-08-13', close: 1.02 },
      ],
    },
  }, 'net')
  assert.ok(option)
  const scatter = option.series.find((item) => item.id === 'position-review-portfolio-trades')
  assert.ok(scatter)
  assert.equal(scatter.data[0].value[1], 100)
  // 成交明细改为：hover 走 axis 快照卡合并 + 点击自绘固定卡（ECharts
  // 全局 axis 触发下 series 级 tooltip 不生效，不再配置）。
  assert.equal(scatter.tooltip, undefined)
  assert.equal(option.tooltip.triggerOn, 'mousemove')
})

test('benchmark option renders via ECharts SSR without axis errors', () => {
  const option = buildPortfolioEquityOption({
    period: '30d',
    series: [
      { time: '2026-08-12', period_label: '2026-08-12', total_equity: 100000.0, net_value: 90000.0 },
      { time: '2026-08-13', period_label: '2026-08-13', total_equity: 102000.0, net_value: 91800.0 },
    ],
    benchmark: {
      code: '510210',
      name: '上证综指ETF',
      series: [
        { period_label: '2026-08-12', close: 1.01 },
        { period_label: '2026-08-13', close: 1.02 },
      ],
    },
  }, 'net')
  assert.ok(option)
  const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 800, height: 400 })
  assert.doesNotThrow(() => chart.setOption(option))
  const svg = chart.renderToSVGString()
  assert.ok(svg.length > 0)
  chart.dispose()
})

test('account-only option renders via ECharts SSR', () => {
  const option = buildPortfolioEquityOption({
    period: '30d',
    series: [
      { time: '2026-08-12', period_label: '2026-08-12', total_equity: 100000.0, net_value: 90000.0, market_value: 80000.0, cash: 12000.0 },
    ],
  }, 'net')
  assert.ok(option)
  const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 800, height: 400 })
  assert.doesNotThrow(() => chart.setOption(option))
  const svg = chart.renderToSVGString()
  assert.ok(svg.length > 0)
  chart.dispose()
})

test('buildPortfolioEquityOption supports disabling tooltip while pinned card is open', () => {
  const option = buildPortfolioEquityOption({
    period: '30d',
    series: [
      { time: '2026-08-12', period_label: '2026-08-12', total_equity: 100000.0, net_value: 90000.0 },
    ],
  }, 'net', { tooltipEnabled: false })
  assert.equal(option.tooltip.show, false)
})

test('buildPortfolioEquityOption line series use lttb sampling for large windows', () => {
  const option = buildPortfolioEquityOption({
    period: '2y',
    series: [
      { time: '2026-08-12 09:30', period_label: '2026-08-12 09:30', total_equity: 100000.0, net_value: 90000.0 },
      { time: '2026-08-12 09:35', period_label: '2026-08-12 09:35', total_equity: 100100.0, net_value: 90100.0 },
    ],
    benchmark: {
      code: '510210',
      name: '上证综指ETF',
      series: [
        { period_label: '2026-08-12 09:30', close: 1.01 },
        { period_label: '2026-08-12 09:35', close: 1.02 },
      ],
    },
  }, 'net')
  assert.ok(option)
  const lines = option.series.filter((item) => item.type === 'line')
  assert.equal(lines.length, 2)
  assert.ok(lines.every((item) => item.sampling === 'lttb'))
})

test('buildPortfolioBenchmarkSummary computes beat spread over common span', () => {
  const summary = buildPortfolioBenchmarkSummary({
    period: '30d',
    series: [
      { net_value: 100000.0 },
      { net_value: 106000.0 },
    ],
    benchmark: {
      code: '510210',
      name: '上证综指ETF',
      series: [
        { close: 1.0 },
        { close: 1.02 },
      ],
    },
  }, 'net')
  assert.ok(summary)
  assert.equal(summary.accountPct.toFixed(2), '6.00')
  assert.equal(summary.benchmarkPct.toFixed(2), '2.00')
  assert.equal(summary.spread.toFixed(2), '4.00')
  assert.equal(summary.beat, true)
  assert.equal(summary.benchmarkName, '上证综指ETF')
})

test('buildPortfolioTradeTooltip aggregates fills per order and summarizes buy/sell', () => {
  const html = buildPortfolioTradeTooltip({
    period_label: '2026-07-21',
    trades: [
      { time: '2026-07-21T13:00+08:00', symbol: '300760', name: '迈瑞医疗', side: 'buy', quantity: 100, price: 153.8, amount: 15380.0, request_id: 'req_buy_1', signal_label: '反转买点', association_quality: 'high', account_partition: 'partition_a' },
      { time: '2026-07-21T13:01+08:00', symbol: '300760', name: '迈瑞医疗', side: 'buy', quantity: 200, price: 153.9, amount: 30780.0, request_id: 'req_buy_1', signal_label: '反转买点', association_quality: 'high', account_partition: 'partition_a' },
      { time: '2026-07-21T13:02+08:00', symbol: '300760', name: '迈瑞医疗', side: 'buy', quantity: 100, price: null, amount: null, request_id: 'req_buy_1', signal_label: '反转买点', association_quality: 'high', account_partition: 'partition_a' },
      { time: '2026-07-21T14:00+08:00', symbol: '002262', name: '恩华药业', side: 'sell', quantity: 1000, price: 0.57, amount: 570.0, request_id: 'req_sell_2', signal_label: '止盈卖点', association_quality: 'high', account_partition: 'partition_a' },
    ],
  })
  assert.match(html, /2026-07-21 · 2 笔订单/)
  assert.match(html, /当日汇总/)
  assert.match(html, /买入 1 笔订单 · 合计 46,160 元（400 股）/)
  assert.match(html, /卖出 1 笔订单 · 合计 570 元（1,000 股）/)
  assert.match(html, /成交 400 股/)
  // 无价格成交不计入加权均价分母（成本合计 46,160 / 300 股）。
  assert.match(html, /均价 153\.87 元/)
  assert.match(html, /3 笔/)
  assert.doesNotMatch(html, /153\.8 元/)
  assert.match(html, /请求 req_buy_1/)
  assert.match(html, /信号 反转买点/)
  assert.match(html, /信号 止盈卖点/)
  assert.match(html, /关联 high/)
  assert.match(html, /分区 partition_a/)
})

test('buildPortfolioTradeTooltip does not merge fills without order ids', () => {
  const html = buildPortfolioTradeTooltip({
    period_label: '2026-07-21',
    trades: [
      { time: '2026-07-21T13:00+08:00', symbol: '300760', name: '迈瑞医疗', side: 'buy', quantity: 100, price: 153.8, amount: 15380.0 },
      { time: '2026-07-21T13:01+08:00', symbol: '300760', name: '迈瑞医疗', side: 'buy', quantity: 100, price: 153.8, amount: 15380.0 },
    ],
  })
  // 双空 ID 的成交不跨成交合并：两笔各成一行。
  assert.match(html, /2026-07-21 · 2 笔订单/)
  assert.match(html, /买入 2 笔订单/)
})

test('portfolio tooltip formatters render asset snapshot with dark theme', () => {
  const option = buildPortfolioEquityOption({
    period: '30d',
    series: [
      {
        time: '2026-08-12', period_label: '2026-08-12',
        total_equity: 100000.0, net_value: 90000.0,
        market_value: 80000.0, cash: 12000.0, total_debt: 8000.0,
      },
      {
        time: '2026-08-13', period_label: '2026-08-13',
        total_equity: 102000.0, net_value: 91800.0,
        market_value: 81000.0, cash: 13000.0, total_debt: 8200.0,
        trades: [{
          time: '2026-08-13T10:00+08:00', symbol: '300760', name: '迈瑞医疗',
          side: 'buy', quantity: 100, price: 153.0, amount: 15300.0,
          request_id: 'req_buy_x', association_quality: 'high', account_partition: 'partition_a',
        }],
        trade_count: 1,
      },
    ],
    benchmark: {
      code: '510210',
      name: '上证综指ETF',
      series: [
        { period_label: '2026-08-12', close: 1.01 },
        { period_label: '2026-08-13', close: 1.02 },
      ],
    },
  }, 'net')
  assert.ok(option)
  assert.match(option.tooltip.extraCssText, /#0f172a/)
  const html = option.tooltip.formatter([
    { seriesType: 'line', seriesName: '账户净资产', dataIndex: 1 },
  ])
  assert.match(html, /账户净资产/)
  assert.match(html, /较前一交易日/)
  assert.match(html, /持仓市值/)
  assert.match(html, /81,000/)
  assert.match(html, /现金/)
  assert.match(html, /13,000/)
  assert.match(html, /总负债/)
  assert.match(html, /8,200/)
  assert.match(html, /上证综指ETF/)
  assert.match(html, /相对基准/)
  assert.match(html, /跑赢/)
  assert.match(html, /当日成交明细/)
  assert.match(html, /请求 req_buy_x/)
})

test('portfolio account-only tooltip renders snapshot without benchmark', () => {
  const option = buildPortfolioEquityOption({
    period: '30d',
    series: [
      {
        time: '2026-08-12', period_label: '2026-08-12',
        total_equity: 100000.0, net_value: 90000.0,
        market_value: 80000.0, cash: 12000.0, total_debt: 8000.0,
      },
    ],
  }, 'net')
  assert.ok(option)
  assert.match(option.tooltip.extraCssText, /#0f172a/)
  const html = option.tooltip.formatter([
    { seriesType: 'line', seriesName: '账户净资产', dataIndex: 0 },
  ])
  assert.match(html, /账户净资产/)
  assert.match(html, /持仓市值/)
  assert.match(html, /80,000/)
  assert.match(html, /现金/)
  assert.match(html, /总负债/)
  assert.doesNotMatch(html, /相对基准/)
})

test('broker asset basis hides debt row in tooltip', () => {
  const option = buildPortfolioEquityOption({
    period: '30d',
    equity_basis: 'broker_total_asset',
    series: [
      {
        time: '2026-08-12', period_label: '2026-08-12',
        total_equity: 100000.0, net_value: 100000.0,
        market_value: 90000.0, cash: 10000.0,
      },
    ],
  }, 'asset')
  assert.ok(option)
  const html = option.tooltip.formatter([
    { seriesType: 'line', seriesName: '总资产', dataIndex: 0 },
  ])
  assert.doesNotMatch(html, /总负债/)
})

test('buildSymbolCostChartOption renders cost line and order markers without kline', () => {
  const chart = makeChart()
  const option = buildSymbolCostChartOption({ chart })
  assert.ok(option)
  assert.equal(option.xAxis.name, undefined)
  assert.equal(option.yAxis.name, '成本价')
  const costLine = option.series.find((item) => item.id === 'position-review-symbol-cost-line')
  const markers = option.series.find((item) => item.id === 'position-review-symbol-cost-markers')
  assert.ok(costLine)
  assert.ok(markers)
  assert.equal(markers.data.length, 2)
  const buy = markers.data.find((item) => item.event.event_id === 'order-buy')
  assert.equal(buy.itemStyle.color, '#ef4444')
  const sell = markers.data.find((item) => item.event.event_id === 'order-sell')
  assert.equal(sell.itemStyle.color, '#22c55e')
})

test('buildSymbolCostChartOption markArea uses ECharts point-array format', () => {
  const chart = makeChart()
  const option = buildSymbolCostChartOption({
    chart: {
      ...chart,
      holding_cycles: [
        {
          cycle_id: '002262:cycle:1',
          status: 'open',
          open_time: '2026-03-16T09:35:00+08:00',
          close_time: null,
        },
      ],
    },
  })
  const costLine = option.series.find((item) => item.id === 'position-review-symbol-cost-line')
  const markAreas = costLine.markArea?.data || []
  assert.ok(markAreas.length > 0)
  for (const area of markAreas) {
    assert.ok(Array.isArray(area), 'markArea item must be [start, end] pair')
    assert.ok(area.length === 2, 'markArea item must have two points')
    assert.ok('coord' in area[0] && 'coord' in area[1], 'each point must carry coord')
    assert.ok(Array.isArray(area[0].coord) && Array.isArray(area[1].coord))
    assert.ok(area[0].coord[1] === 'min' && area[1].coord[1] === 'max')
  }
})

test('buildSymbolCostChartOption returns null without cost points or events', () => {
  assert.equal(buildSymbolCostChartOption({ chart: {} }), null)
})

test('normalizePortfolioContributions keeps sorted rows', () => {
  const rows = normalizePortfolioContributions({
    top: [
      { symbol: '688772', name: '珠海冠宇', total_pnl: 615.3, realized_pnl: 615.3, is_holding: false },
      { symbol: '002262', name: '恩华药业', total_pnl: -27300.26, is_holding: true },
    ],
  })
  assert.equal(rows.length, 2)
  assert.equal(rows[0].symbol, '688772')
  assert.equal(rows[1].isHolding, true)
})

test('buildSymbolReviewChartOption renders candles, markers, spans and cost line', () => {
  const option = buildSymbolReviewChartOption({ kline: makeKline(), chart: makeChart() })
  assert.ok(option)
  const candles = option.series.find((item) => item.id === 'position-review-symbol-candles')
  const markers = option.series.find((item) => item.id === 'position-review-symbol-markers')
  const spans = option.series.find((item) => item.id === 'position-review-symbol-fill-spans')
  const cost = option.series.find((item) => item.id === 'position-review-symbol-cost')
  assert.equal(candles.data.length, 4)
  assert.equal(markers.data.length, 2)
  assert.equal(spans.data.length, 1)
  assert.equal(cost.data.length, 2)
  const buy = markers.data.find((item) => item.event.event_id === 'order-buy')
  const sell = markers.data.find((item) => item.event.event_id === 'order-sell')
  assert.equal(buy.itemStyle.color, '#ef4444')
  assert.equal(buy.sideText, 'B')
  assert.equal(buy.symbol, 'triangle')
  assert.equal(buy.mark, false)
  assert.equal(sell.itemStyle.color, '#22c55e')
  assert.equal(sell.mark, true)
})

test('buildSymbolReviewChartOption skips null average_cost points instead of plotting y=0', () => {
  const chart = {
    ...makeChart(),
    cost_basis_series: [
      { time: '2026-03-16T09:35:00+08:00', average_cost: 10.27 },
      { time: '2026-03-16T09:40:00+08:00', average_cost: null },
      { time: '2026-03-16T09:45:00+08:00', average_cost: '' },
    ],
  }
  const option = buildSymbolReviewChartOption({ kline: makeKline(), chart })

  const cost = option.series.find((item) => item.id === 'position-review-symbol-cost')
  assert.ok(cost)
  assert.equal(cost.data.length, 1)
  assert.deepEqual(cost.data[0].value, [1, 10.27])
})

test('buildSymbolReviewChartOption returns null without bars', () => {
  assert.equal(buildSymbolReviewChartOption({ kline: { date: [] }, chart: {} }), null)
})

test('normalizeSymbolChart exposes events and cost basis', () => {
  const normalized = normalizeSymbolChart(makeChart())
  assert.equal(normalized.hasEvents, true)
  assert.equal(normalized.events.length, 2)
  assert.equal(normalized.costSeries.length, 2)
})

test('normalizeConditions keeps missing thresholds as null', () => {
  const normalized = normalizeConditions({
    conditions: [
      {
        condition_key: 'signal_price_above_threshold',
        label: '触发价格 >= 历史阈值',
        actual_value: 22.41,
        threshold_value: null,
        passed: null,
        source: 'missing',
      },
    ],
    data_quality: { threshold_missing_count: 1 },
  })
  assert.equal(normalized.conditions[0].thresholdMissing, true)
  assert.equal(normalized.thresholdMissingCount, 1)
})

test('buildMarkerTooltip renders the full signal and execution sections', () => {
  const html = buildMarkerTooltip(makeChart().order_events[0])
  assert.match(html, /买入/)
  assert.match(html, /order-buy/)
  assert.match(html, /反转买点/)
  assert.match(html, /buy_v_reverse/)
  assert.match(html, /触发信号/)
  assert.match(html, /触发条件与全部阈值/)
  assert.match(html, /订单与成交/)
  assert.match(html, /仓位与成本影响/)
  assert.match(html, /10000/)
  assert.match(html, /10\.27/)
  assert.match(html, /fees_included: false/)
})

test('buildFullMarkerTooltip renders every condition threshold once loaded', () => {
  const event = makeChart().order_events[0]
  const html = buildFullMarkerTooltip(event, {
    conditions: [
      {
        condition_key: 'signal_price_reaches_grid',
        label: '触发价格达到网格买入价',
        actual_value: 10.25,
        actual_display: '10.25',
        operator: '<=',
        threshold_value: 10.27,
        threshold_display: '10.27',
        passed: true,
        source: 'request_snapshot',
        observed_at: '2026-04-29T10:15:00+08:00',
      },
      {
        condition_key: 'expected_quantity_achieved',
        label: '策略应有量与真实成交一致',
        actual_value: 10000,
        actual_display: '10000',
        operator: '==',
        threshold_value: null,
        threshold_display: '',
        passed: null,
        source: 'missing',
        observed_at: null,
      },
    ],
    data_quality: { threshold_missing_count: 1 },
  })
  assert.match(html, /触发价格达到网格买入价/)
  assert.match(html, /10\.27/)
  assert.match(html, /缺失/)
  assert.doesNotMatch(html, /条件证据加载中/)
  assert.doesNotMatch(html, /点击固定订单查看完整证据/)
})
