import http from '@/http'

const BASE = '/api/clx-backtest'

type AnyRecord = Record<string, any>

const record = (value: unknown): AnyRecord =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as AnyRecord : {}

const unwrapData = <T = any>(response: any): T => {
  const outer = record(response)
  if (Object.prototype.hasOwnProperty.call(outer, 'data')) return outer.data as T
  return response as T
}

export interface SqControlStats {
  reps: number
  drawN: number
  controlMean: number | null
  percentile: number | null
}

export interface SqSplitStats {
  nTotal: number
  nBlocked: number
  nExecutable: number
  executionRate: number | null
  meanExcess: number | null
  medianExcess: number | null
  stdExcess: number | null
  winRate: number | null
  tStat: number | null
  pValue: number | null
  fdrQValue: number | null
  netMeanExcess: number | null
  informationRatio: number | null
  yearlyMeanExcess: Record<string, number>
  worstYearMean: number | null
  positiveYearRatio: number | null
  horizonDecay: Record<string, number | null>
  randomPoolControl: SqControlStats | null
  dateShiftControl: SqControlStats | null
}

export interface SqCell {
  cellId: string
  modelCode: string
  modelId: number
  trigger: string
  direction: number
  splits: Record<string, SqSplitStats>
  qualification: { status: string; checks: Record<string, boolean> }
}

export interface SqSummary {
  schemaVersion: string
  runId: string
  generatedAt: string
  methodology: AnyRecord
  statusCounts: Record<string, number>
  cellCount: number
  models: string[]
  triggers: string[]
}

const numberOrNull = (value: any): number | null => {
  if (value === undefined || value === null || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

const normalizeControl = (raw: any): SqControlStats | null => {
  if (!raw || typeof raw !== 'object') return null
  const item = record(raw)
  return {
    reps: Number(item.reps ?? 0),
    drawN: Number(item.draw_n ?? 0),
    controlMean: numberOrNull(item.control_mean),
    percentile: numberOrNull(item.percentile),
  }
}

const normalizeSplitStats = (raw: any): SqSplitStats => {
  const item = record(raw)
  return {
    nTotal: Number(item.n_total ?? 0),
    nBlocked: Number(item.n_blocked ?? 0),
    nExecutable: Number(item.n_executable ?? 0),
    executionRate: numberOrNull(item.execution_rate),
    meanExcess: numberOrNull(item.mean_excess),
    medianExcess: numberOrNull(item.median_excess),
    stdExcess: numberOrNull(item.std_excess),
    winRate: numberOrNull(item.win_rate),
    tStat: numberOrNull(item.t_stat),
    pValue: numberOrNull(item.p_value),
    fdrQValue: numberOrNull(item.fdr_q_value),
    netMeanExcess: numberOrNull(item.net_mean_excess),
    informationRatio: numberOrNull(item.information_ratio),
    yearlyMeanExcess: record(item.yearly_mean_excess) as Record<string, number>,
    worstYearMean: numberOrNull(item.worst_year_mean),
    positiveYearRatio: numberOrNull(item.positive_year_ratio),
    horizonDecay: record(item.horizon_decay) as Record<string, number | null>,
    randomPoolControl: normalizeControl(item.random_pool_control),
    dateShiftControl: normalizeControl(item.date_shift_control),
  }
}

export const normalizeCell = (raw: any): SqCell => {
  const item = record(raw)
  const splits: Record<string, SqSplitStats> = {}
  for (const [split, stats] of Object.entries(record(item.splits))) {
    splits[split] = normalizeSplitStats(stats)
  }
  const qualification = record(item.qualification)
  return {
    cellId: String(item.cell_id ?? ''),
    modelCode: String(item.model_code ?? ''),
    modelId: Number(item.model_id ?? -1),
    trigger: String(item.trigger ?? ''),
    direction: Number(item.direction ?? 0),
    splits,
    qualification: {
      status: String(qualification.status ?? 'REJECTED'),
      checks: record(qualification.checks) as Record<string, boolean>,
    },
  }
}

export const signalQualityApi = {
  async summary(runId: string): Promise<SqSummary> {
    const payload = record(unwrapData(await http({
      url: `${BASE}/runs/${runId}/signal-quality`, method: 'get',
    })))
    return {
      schemaVersion: String(payload.schema_version ?? ''),
      runId: String(payload.run_id ?? runId),
      generatedAt: String(payload.generated_at ?? ''),
      methodology: record(payload.methodology),
      statusCounts: record(payload.status_counts) as Record<string, number>,
      cellCount: Number(payload.cell_count ?? 0),
      models: Array.isArray(payload.models) ? payload.models.map(String) : [],
      triggers: Array.isArray(payload.triggers) ? payload.triggers.map(String) : [],
    }
  },

  async cells(runId: string, params: {
    splitId?: string
    direction?: number
    modelId?: string
    trigger?: string
    status?: string
    minExecutable?: number
  } = {}): Promise<{ items: SqCell[]; generatedAt: string }> {
    const payload = record(unwrapData(await http({
      url: `${BASE}/runs/${runId}/signal-quality/cells`,
      method: 'get',
      params: {
        split_id: params.splitId,
        direction: params.direction,
        model_id: params.modelId,
        trigger: params.trigger,
        status: params.status,
        min_executable: params.minExecutable,
      },
    })))
    const items = Array.isArray(payload.items) ? payload.items.map(normalizeCell) : []
    return { items, generatedAt: String(payload.generated_at ?? '') }
  },
}
