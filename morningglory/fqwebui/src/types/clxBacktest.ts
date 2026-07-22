export type RunStatus =
  | 'DRAFT'
  | 'QUEUED'
  | 'RUNNING'
  | 'CANCEL_REQUESTED'
  | 'CANCELLED'
  | 'FAILED'
  | 'COMPLETE'

export type SplitId = 'TRAIN' | 'VALIDATION' | 'HOLDOUT'
export type Direction = 'BUY' | 'SELL' | 'LONG' | 'EXIT' | 'POSITIVE' | 'NEGATIVE'

export interface CursorPage<T> {
  items: T[]
  nextCursor: string | null
  total?: number
}

export interface RunLineage {
  clonedFromRunId?: string | null
  parentRunId?: string | null
  [key: string]: unknown
}

export interface BacktestRunConfig {
  snapshotId?: string
  snapshotManifestSha256?: string
  signalSetId?: string
  signalManifestSha256?: string
  modelIds?: string[]
  waveOpt?: number
  stretchOpt?: number
  extOpt?: number
  trendOpt?: number
  train?: { start?: string; end?: string }
  validation?: { start?: string; end?: string }
  holdout?: { start?: string; end?: string }
  horizons?: number[]
  initialCash?: number
  maxPositions?: number
  positionWeight?: number
  combinationDsl?: string
  feeModel?: Record<string, unknown>
  [key: string]: unknown
}

export interface RunFreezeSummary {
  freezeId: string
  state: string
  revealCount: number
  createdAt?: string
  holdoutRevealedAt?: string | null
  runConfigSha256?: string
}

export interface BacktestRun {
  runId: string
  name: string
  status: RunStatus
  config: BacktestRunConfig
  configSha256: string
  lineage?: RunLineage
  createdAt?: string
  updatedAt?: string
  frozen?: boolean
  freezeId?: string | null
  holdoutRevealed?: boolean
  freeze?: RunFreezeSummary | null
}

export interface RankingFilters {
  splitId?: SplitId
  modelId?: string
  direction?: string
  occurrence?: number
  horizon?: number
  primaryTrigger?: string
  minScore?: number
  pageSize?: number
  cursor?: string
}

export interface PerformanceMetrics {
  totalReturn?: number | null
  annualizedReturn?: number | null
  excessReturn?: number | null
  sharpe?: number | null
  sortino?: number | null
  maxDrawdown?: number | null
  calmar?: number | null
  winRate?: number | null
  profitFactor?: number | null
  turnover?: number | null
  signalCount?: number | null
  tradeCount?: number | null
  sampleCount?: number | null
  coverage?: number | null
  stabilityScore?: number | null
  fdrQValue?: number | null
  confidenceLow?: number | null
  confidenceHigh?: number | null
  [key: string]: unknown
}

export interface RankingRow {
  rank: number
  comboId: string
  name: string
  splitId: SplitId | string
  score: number | null
  modelIds: string[]
  direction?: string
  primaryTriggers?: string[]
  occurrence?: number | null
  horizon?: number | null
  metrics: PerformanceMetrics
  frozen?: boolean
  freezeId?: string | null
  holdoutRevealed?: boolean
  rankingConfigSha256?: string
}

export interface TriggerRule {
  modelId?: string
  direction?: string
  primaryTrigger?: string
  concurrentTriggers?: string[]
  occurrence?: number | { min?: number; max?: number } | null
  weight?: number
  role?: 'ENTRY' | 'EXIT' | 'VETO' | 'FILTER' | string
  [key: string]: unknown
}

export interface ComboDetail {
  comboId: string
  name: string
  splitId?: SplitId | string
  description?: string
  definition?: {
    operator?: string
    rules?: TriggerRule[]
    familyDeduplication?: boolean
    holdingPeriod?: number
    [key: string]: unknown
  }
  metrics?: PerformanceMetrics
  configSha256?: string
  signalSetId?: string
  frozen?: boolean
  freezeId?: string | null
  holdoutRevealed?: boolean
  [key: string]: unknown
}

export interface EquityPoint {
  date: string
  equity: number
  benchmark?: number | null
  drawdown?: number | null
  cash?: number | null
  annualReturn?: number | null
}

export interface AnnualReturnPoint {
  year: string
  strategy: number
  benchmark?: number | null
}

export interface TradeRecord {
  tradeId: string
  code: string
  name?: string
  side: string
  signalDate?: string
  tradeDate: string
  price: number
  quantity: number
  fees?: number
  pnl?: number | null
  returnRate?: number | null
  exitReason?: string
  blockedReason?: string
}

export interface SignalRecord {
  signalId: string
  decisionId?: string
  code: string
  name?: string
  signalDate: string
  revealDate: string
  direction: string
  decisionRevealDate?: string
  decisionDirection?: string
  modelId: string
  occurrence: number
  primaryTrigger: string
  concurrentTriggers: string[]
  baseTriggerMask?: number | string
  syntheticPrimaryMask?: number | string
  finalTriggerMask?: number | string
  rawSignal?: number
  comboId?: string
}

export interface CandlePoint {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume?: number
  signalIds?: string[]
  signalDirection?: string
}

export interface HeatmapCell {
  modelId: string
  trigger: string
  value: number | null
  sampleCount?: number
  splitId?: string
  metric?: string
}

export interface ProgressEvent {
  eventId?: string
  at: string
  level?: 'INFO' | 'WARNING' | 'ERROR' | string
  stage: string
  message: string
  completed?: number
  total?: number
  percent?: number
  details?: Record<string, unknown>
}

export interface RunProgress {
  runId: string
  status: RunStatus
  stage?: string
  message?: string
  completed?: number
  total?: number
  percent: number
  updatedAt?: string
  events: ProgressEvent[]
}

export interface DataQualityIssue {
  code: string
  severity: 'INFO' | 'WARNING' | 'ERROR' | string
  title: string
  detail: string
  affectedRows?: number
  affectedCodes?: number
}

export interface QualityReport {
  runId?: string
  status?: string
  sourceRows?: number
  signalRows?: number
  excludedRows?: number
  adjustmentGapCount?: number
  causalityMismatchRate?: number | null
  tradabilityApproximation?: boolean
  issues: DataQualityIssue[]
  generatedAt?: string
}

export interface ManifestRecord {
  manifestId?: string
  snapshotId?: string
  signalSetId?: string
  runId?: string
  sha256?: string
  sourceCollectionUuid?: string
  sourceCount?: number
  codeCount?: number
  dateMin?: string
  dateMax?: string
  artifactUri?: string
  createdAt?: string
  payload?: Record<string, unknown>
}

export interface FreezeRecord {
  freezeId: string
  runId: string
  status: string
  configSha256?: string
  frozenAt?: string
  holdoutRevealed?: boolean
  revealedAt?: string | null
  revealCount?: number
}

export interface FreezeSpecification {
  validation: {
    selectedComboIds: string[]
    rankOrder: string[]
  }
  rankingConfig: Record<string, unknown>
  splitConfigSha256: string
  frozenRankDigest: string
}

export interface ExportJob {
  jobId: string
  status: 'QUEUED' | 'RUNNING' | 'COMPLETE' | 'FAILED' | string
  resource?: string
  format?: string
  splitId?: SplitId | string
  downloadUrl?: string | null
  expiresAt?: string | null
  error?: string | null
}

export interface ComparisonItem {
  comboId: string
  name: string
  metrics: PerformanceMetrics
  equity?: EquityPoint[]
  splitId?: string
}

export interface ComparisonResult {
  runId: string
  splitId: string
  items: ComparisonItem[]
}

export interface ApiErrorShape {
  code: string
  message: string
  details?: unknown
  status?: number
}
