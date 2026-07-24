export const DEFAULT_CLX_RANKING_CONFIG = Object.freeze({
  horizon: 5,
  min_train_sample: 100,
  min_validation_sample: 50,
  min_train_density: 0.01,
  min_validation_density: 0.005,
  min_train_years: 2,
  min_validation_years: 1,
  min_events_per_year: 3,
  max_train_fdr: 0.2,
  max_validation_fdr: 0.2,
  beam_width_per_stage: 64,
  max_candidates_per_stage: 4096,
  max_total_candidates: 16384,
  max_seed_per_root: 2,
  max_trigger_terms: 2,
  jaccard_threshold: 0.95,
  resonance_lookbacks: [0, 1, 3, 5],
  enable_sequences: true,
  train_score_weights: [
    ['ci_low', 0.5],
    ['complexity', -0.001],
    ['density', 0.001],
    ['mean_return', 1],
    ['win_rate_edge', 0.2],
    ['year_positive_ratio', 0.1],
  ],
  validation_score_weights: [
    ['ci_low', 0.5],
    ['complexity', -0.001],
    ['density', 0.001],
    ['mean_return', 1],
    ['retention', 0.1],
    ['stability', 0.1],
    ['win_rate_edge', 0.2],
    ['year_positive_ratio', 0.1],
  ],
})

export const fixtureRun = {
  runId: 'run-fixture-complete',
  name: 'CLX 因果验证基线',
  status: 'COMPLETE',
  configSha256: '64b9c3146e03571fab57fc5be59b52d44ac76887a9d43568da692876554c0c62',
  config: {
    snapshotId: 'snapshot-fixture',
    snapshotManifestSha256: 'snapshot-sha-fixture',
    signalSetId: 'signal-set-fixture',
    modelIds: Array.from({ length: 18 }, (_, index) => `S${String(index).padStart(4, '0')}`),
    waveOpt: 1560,
    stretchOpt: 0,
    extOpt: 0,
    trendOpt: 0,
    train: { start: '2016-01-01', end: '2020-12-31' },
    validation: { start: '2021-01-01', end: '2023-12-31' },
    holdout: { start: '2024-01-01', end: '2025-12-31' },
    horizons: [5, 10, 20],
    initialCash: 1000000,
    maxPositions: 10,
  },
  createdAt: '2026-07-22T02:00:00Z',
  updatedAt: '2026-07-22T03:30:00Z',
  frozen: false,
  freezeId: null,
  holdoutRevealed: false,
}

const metricsA = {
  meanReturn: 0.021,
  winRate: 0.574,
  fdrQValue: 0.031,
  sampleCount: 1260,
  stabilityScore: 0.75,
  confidenceLow: 0.012,
  confidenceHigh: 0.029,
}
const metricsB = {
  meanReturn: 0.016,
  winRate: 0.552,
  fdrQValue: 0.044,
  sampleCount: 980,
  stabilityScore: 0.68,
  confidenceLow: 0.008,
  confidenceHigh: 0.023,
}

export const fixturePortfolioMetrics = [
  { totalReturn: 0.184, cagr: 0.116, sharpe: 1.21, maxDrawdown: -0.087, tradeWinRate: 0.574, closedLotCount: 318 },
  { totalReturn: 0.129, cagr: 0.084, sharpe: 0.96, maxDrawdown: -0.064, tradeWinRate: 0.552, closedLotCount: 244 },
]

export const fixtureRankings = [
  {
    rank: 1,
    comboId: 'combo-a',
    name: 'S0002 正向吞没 × S0007 趋势确认',
    splitId: 'VALIDATION',
    score: 0.812,
    modelIds: ['S0002', 'S0007'],
    direction: 'POSITIVE',
    primaryTriggers: ['ENGULFING', 'TREND_CONFIRM'],
    occurrence: 1,
    horizon: 5,
    metrics: metricsA,
  },
  {
    rank: 2,
    comboId: 'combo-b',
    name: 'S0011 首次突破 × S0016 风险过滤',
    splitId: 'VALIDATION',
    score: 0.744,
    modelIds: ['S0011', 'S0016'],
    direction: 'POSITIVE',
    primaryTriggers: ['BREAKOUT', 'RISK_FILTER'],
    occurrence: 1,
    horizon: 5,
    metrics: metricsB,
  },
]

export const fixtureEquity = [
  { date: '2021-01-04', equity: 1000000, benchmark: 1000000, drawdown: 0 },
  { date: '2021-06-30', equity: 1060000, benchmark: 1020000, drawdown: -0.018 },
  { date: '2022-01-04', equity: 1025000, benchmark: 970000, drawdown: -0.052 },
  { date: '2022-12-30', equity: 1110000, benchmark: 995000, drawdown: -0.021 },
  { date: '2023-12-29', equity: 1184000, benchmark: 1010000, drawdown: -0.016 },
]

export const fixtureTrades = [
  {
    tradeId: 'trade-1',
    code: '000001',
    name: '平安银行',
    side: 'BUY',
    signalDate: '2023-03-01',
    tradeDate: '2023-03-02',
    price: 12.31,
    quantity: 1000,
    fees: 5.13,
    pnl: null,
  },
  {
    tradeId: 'trade-2',
    code: '000001',
    name: '平安银行',
    side: 'SELL',
    signalDate: '2023-03-20',
    tradeDate: '2023-03-21',
    price: 13.04,
    quantity: 1000,
    fees: 19.11,
    pnl: 705.76,
    returnRate: 0.0573,
    exitReason: 'NEGATIVE_SIGNAL',
  },
]

export const fixtureSignals = [
  {
    signalId: 'signal-1',
    code: '000001',
    name: '平安银行',
    signalDate: '2023-03-01',
    revealDate: '2023-03-01',
    direction: 'POSITIVE',
    modelId: 'S0002',
    occurrence: 1,
    primaryTrigger: 'ENGULFING',
    concurrentTriggers: ['ENGULFING', 'NORMAL_FRACTAL'],
    rawSignal: 2101,
    comboId: 'combo-a',
  },
]

export const fixtureCandles = [
  { date: '2023-02-27', open: 12.0, high: 12.3, low: 11.9, close: 12.2, volume: 120000 },
  { date: '2023-02-28', open: 12.2, high: 12.35, low: 12.0, close: 12.05, volume: 100000 },
  { date: '2023-03-01', open: 12.0, high: 12.4, low: 11.95, close: 12.38, volume: 180000 },
  { date: '2023-03-02', open: 12.31, high: 12.6, low: 12.25, close: 12.5, volume: 160000 },
]

export const fixtureProgress = {
  runId: fixtureRun.runId,
  status: 'COMPLETE',
  stage: 'PUBLISH',
  message: 'artifact 与 manifest 已发布',
  percent: 100,
  updatedAt: '2026-07-22T03:30:00Z',
  events: [
    { eventId: 'event-1', at: '2026-07-22T02:00:00Z', stage: 'SNAPSHOT', message: '加载不可变数据快照', percent: 5 },
    { eventId: 'event-2', at: '2026-07-22T03:00:00Z', stage: 'PORTFOLIO', message: '完成组合撮合与对账', percent: 85 },
    { eventId: 'event-3', at: '2026-07-22T03:30:00Z', stage: 'PUBLISH', message: 'artifact 与 manifest 已发布', percent: 100 },
  ],
}

export const fixtureQuality = {
  runId: fixtureRun.runId,
  status: 'WARNING',
  sourceRows: 16426284,
  signalRows: 45217,
  excludedRows: 3,
  adjustmentGapCount: 7,
  causalityMismatchRate: 0.3298,
  tradabilityApproximation: true,
  generatedAt: '2026-07-22T03:30:00Z',
  issues: [
    {
      code: 'POINT_IN_TIME_STATUS',
      severity: 'WARNING',
      title: '历史证券状态不完整',
      detail: '历史 ST 与退市状态按可得字段近似。',
    },
  ],
}

export const fixtureManifest = {
  manifestId: 'manifest-fixture',
  snapshotId: 'snapshot-fixture',
  signalSetId: 'signal-set-fixture',
  runId: fixtureRun.runId,
  sha256: '2a135ba9a1062293583f96cc4505fc78de512f32c9b5665436b57232f12af278',
  sourceCollectionUuid: 'uuid-fixture',
  sourceCount: 16426284,
  codeCount: 5201,
  dateMin: '1990-12-19',
  dateMax: '2026-07-21',
  artifactUri: '/opt/fqpack/runtime/clx-backtest/runs/run-fixture-complete',
  payload: {
    run_id: fixtureRun.runId,
    state: 'PUBLISHED',
    manifest_sha256: '2a135ba9a1062293583f96cc4505fc78de512f32c9b5665436b57232f12af278',
    config: { split_config_sha256: `sha256:${'1'.repeat(64)}` },
  },
}
