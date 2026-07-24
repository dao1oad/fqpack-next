import http from '@/http'
import type {
  ApiErrorShape,
  BacktestRun,
  BacktestRunConfig,
  CandlePoint,
  ComboDetail,
  ComparisonResult,
  CursorPage,
  EquityPoint,
  ExportJob,
  FreezeRecord,
  FreezeSpecification,
  HeatmapCell,
  ManifestRecord,
  PerformanceMetrics,
  ProgressEvent,
  QualityReport,
  RankingFilters,
  RankingRow,
  RunProgress,
  RunFreezeSummary,
  SignalRecord,
  TradeRecord,
} from '@/types/clxBacktest'

const BASE = '/api/clx-backtest'

type AnyRecord = Record<string, any>

const record = (value: unknown): AnyRecord =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as AnyRecord : {}

export function unwrapData<T = any>(response: any): T {
  const outer = record(response)
  if (Object.prototype.hasOwnProperty.call(outer, 'data')) return outer.data as T
  return response as T
}

export function normalizePage<T>(response: any, mapper: (item: any, index: number) => T): CursorPage<T> {
  const payload: any = unwrapData(response)
  const rawItems = Array.isArray(payload)
    ? payload
    : Array.isArray(payload?.items)
      ? payload.items
      : Array.isArray(payload?.data)
        ? payload.data
        : []
  return {
    items: rawItems.map(mapper),
    nextCursor: payload?.next_cursor ?? payload?.nextCursor ?? null,
    total: payload?.total ?? payload?.total_count,
  }
}

const numberOrNull = (value: any): number | null => {
  if (value === undefined || value === null || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

const stringArray = (value: any): string[] => {
  if (Array.isArray(value)) return value.filter(Boolean).map(String)
  if (typeof value === 'string' && value.trim()) return value.split(/[,+|]/).map(v => v.trim()).filter(Boolean)
  return []
}

const normalizeModelId = (value: any): string => {
  const text = String(value ?? '')
  if (/^S\d{4}$/.test(text)) return text
  if (/^\d{1,2}$/.test(text)) return `S${String(Number(text)).padStart(4, '0')}`
  return text
}
const modelIdArray = (value: any): string[] => stringArray(value).map(normalizeModelId)

const normalizeRange = (value: any, source: AnyRecord, prefix: string) => {
  const range = record(value)
  return {
    start: range.start ?? range.start_date ?? source[`${prefix}_start`] ?? source[`${prefix}_start_date`],
    end: range.end ?? range.end_date ?? source[`${prefix}_end`] ?? source[`${prefix}_end_date`],
  }
}

export function normalizeConfig(raw: any): BacktestRunConfig {
  const cfg = record(raw)
  return {
    ...cfg,
    snapshotId: cfg.snapshot_id ?? cfg.snapshotId,
    snapshotManifestSha256: cfg.snapshot_manifest_sha256 ?? cfg.snapshotManifestSha256,
    signalSetId: cfg.signal_set_id ?? cfg.signalSetId,
    signalManifestSha256: cfg.signal_manifest_sha256 ?? cfg.signalManifestSha256,
    modelIds: modelIdArray(cfg.model_ids ?? cfg.modelIds),
    waveOpt: numberOrNull(cfg.wave_opt ?? cfg.waveOpt) ?? undefined,
    stretchOpt: numberOrNull(cfg.stretch_opt ?? cfg.stretchOpt) ?? undefined,
    extOpt: numberOrNull(cfg.ext_opt ?? cfg.extOpt) ?? undefined,
    trendOpt: numberOrNull(cfg.trend_opt ?? cfg.trendOpt) ?? undefined,
    train: normalizeRange(cfg.train, cfg, 'train'),
    validation: normalizeRange(cfg.validation, cfg, 'validation'),
    holdout: normalizeRange(cfg.holdout, cfg, 'holdout'),
    horizons: (cfg.horizons ?? []).map(Number).filter(Number.isFinite),
    initialCash: numberOrNull(cfg.initial_cash ?? cfg.initialCash) ?? undefined,
    maxPositions: numberOrNull(cfg.max_positions ?? cfg.maxPositions) ?? undefined,
    positionWeight: numberOrNull(cfg.position_weight ?? cfg.positionWeight) ?? undefined,
    combinationDsl: cfg.combination_dsl ?? cfg.canonical_dsl ?? cfg.combinationDsl,
    feeModel: cfg.fee_model ?? cfg.feeModel,
  }
}

export function normalizeRun(raw: any): BacktestRun {
  const item = record(raw)
  const freeze = record(item.freeze)
  const freezeSummary: RunFreezeSummary | null = Object.keys(freeze).length ? {
    freezeId: String(freeze.freeze_id ?? freeze.freezeId ?? ''),
    state: String(freeze.state ?? freeze.status ?? 'FROZEN'),
    revealCount: Number(freeze.reveal_count ?? freeze.revealCount ?? 0),
    createdAt: freeze.created_at ?? freeze.createdAt,
    holdoutRevealedAt: freeze.holdout_revealed_at ?? freeze.holdoutRevealedAt ?? null,
    runConfigSha256: freeze.run_config_sha256 ?? freeze.runConfigSha256,
  } : null
  const revealCount = Number(item.reveal_count ?? freeze.reveal_count ?? 0)
  return {
    runId: String(item.run_id ?? item.runId ?? item._id ?? ''),
    name: String(item.name ?? item.run_name ?? item.run_id ?? '未命名实验'),
    status: String(item.status ?? 'DRAFT').toUpperCase() as BacktestRun['status'],
    config: normalizeConfig(item.config ?? item.specification ?? {}),
    configSha256: String(item.config_sha256 ?? item.configSha256 ?? item.run_config_sha256 ?? ''),
    lineage: {
      ...(item.lineage ?? {}),
      clonedFromRunId: item.lineage?.clonedFromRunId ?? item.lineage?.cloned_from_run_id ?? item.cloned_from,
    },
    createdAt: item.created_at ?? item.createdAt,
    updatedAt: item.updated_at ?? item.updatedAt,
    frozen: Boolean(item.frozen ?? item.freeze_id ?? freezeSummary?.freezeId),
    freezeId: item.freeze_id ?? freezeSummary?.freezeId ?? null,
    holdoutRevealed: Boolean(
      item.holdout_revealed
      ?? item.holdout_revealed_at
      ?? freezeSummary?.holdoutRevealedAt
      ?? revealCount === 1,
    ),
    freeze: freezeSummary,
  }
}

export function normalizeMetrics(raw: any): PerformanceMetrics {
  const item = record(raw)
  return {
    ...item,
    meanReturn: numberOrNull(item.mean_return ?? item.meanReturn),
    totalReturn: numberOrNull(item.total_return ?? item.totalReturn),
    annualizedReturn: numberOrNull(item.annualized_return ?? item.annual_return ?? item.cagr ?? item.annualizedReturn),
    excessReturn: numberOrNull(item.excess_return ?? item.excessReturn),
    sharpe: numberOrNull(item.sharpe ?? item.sharpe_ratio),
    sortino: numberOrNull(item.sortino ?? item.sortino_ratio),
    maxDrawdown: numberOrNull(item.max_drawdown ?? item.maxDrawdown),
    calmar: numberOrNull(item.calmar ?? item.calmar_ratio),
    winRate: numberOrNull(item.win_rate ?? item.trade_win_rate ?? item.winRate),
    profitFactor: numberOrNull(item.profit_factor ?? item.profitFactor),
    turnover: numberOrNull(item.turnover),
    signalCount: numberOrNull(item.signal_count ?? item.signalCount),
    tradeCount: numberOrNull(item.trade_count ?? item.closed_lot_count ?? item.tradeCount),
    sampleCount: numberOrNull(item.sample_count ?? item.sampleCount),
    coverage: numberOrNull(item.coverage ?? item.signal_density),
    stabilityScore: numberOrNull(item.stability_score ?? item.year_positive_ratio ?? item.stabilityScore),
    fdrQValue: numberOrNull(item.fdr_q_value ?? item.fdrQValue),
    confidenceLow: numberOrNull(item.ci_low ?? item.confidence_low ?? item.confidenceLow),
    confidenceHigh: numberOrNull(item.ci_high ?? item.confidence_high ?? item.confidenceHigh),
  }
}

export function normalizeRanking(raw: any, index = 0): RankingRow {
  const item = record(raw)
  const modelRoots = modelIdArray(item.model_roots ?? item.model_ids ?? item.models ?? item.model_id)
  const segmentValue = String(item.segment_value ?? '')
  const modelIds = modelRoots.length ? modelRoots : /^S\d{4}$/.test(segmentValue) ? [segmentValue] : []
  const triggers = stringArray(item.primary_triggers ?? item.trigger_keys ?? item.primary_trigger)
  if (!triggers.length && String(item.segment_type ?? '').includes('TRIGGER') && segmentValue) triggers.push(segmentValue)
  const holdoutState = String(item.holdout_state ?? '').toUpperCase()
  return {
    rank: Number(item.frozen_rank ?? item.rank ?? index + 1),
    comboId: String(item.combo_id ?? item.comboId ?? item.ranking_id ?? ''),
    name: String(item.name ?? item.combo_name ?? item.canonical_dsl ?? item.combo_id ?? '未命名组合'),
    splitId: String(item.split_id ?? item.splitId ?? 'VALIDATION'),
    score: numberOrNull(item.validation_score ?? item.score),
    modelIds,
    direction: Number(item.direction) === 1 ? 'POSITIVE' : Number(item.direction) === -1 ? 'NEGATIVE' : item.direction,
    primaryTriggers: triggers,
    occurrence: numberOrNull(item.occurrence),
    horizon: numberOrNull(item.horizon),
    metrics: normalizeMetrics(item.metrics ?? item),
    frozen: Boolean(item.frozen_rank !== undefined || item.freeze_id),
    freezeId: item.freeze_id ?? null,
    holdoutRevealed: holdoutState === 'REVEALED' || Boolean(item.holdout_metrics),
    rankingConfigSha256: item.ranking_config_sha256,
  }
}

export function normalizeCombo(raw: any): ComboDetail {
  const payload = record(unwrapData(raw))
  const definition = record(payload.definition ?? payload)
  const summary = record(payload.portfolio_summary ?? payload.metrics)
  return {
    ...payload,
    comboId: String(definition.combo_id ?? payload.combo_id ?? ''),
    name: String(definition.name ?? payload.name ?? definition.canonical_dsl ?? definition.dsl ?? definition.combo_id ?? '未命名组合'),
    splitId: payload.split_id ?? 'VALIDATION',
    description: definition.description,
    definition: {
      ...definition,
      operator: definition.operator,
      rules: definition.rules ?? definition.legs ?? [],
      familyDeduplication: definition.family_deduplication ?? definition.familyDeduplication,
      holdingPeriod: numberOrNull(definition.holding_period ?? definition.horizon) ?? undefined,
      dsl: definition.dsl ?? definition.canonical_dsl,
    } as any,
    metrics: normalizeMetrics(summary),
    configSha256: definition.config_sha256 ?? payload.config_sha256,
    signalSetId: definition.signal_set_id ?? payload.signal_set_id,
    frozen: Boolean(payload.freeze_id ?? definition.freeze_id),
    freezeId: payload.freeze_id ?? definition.freeze_id ?? null,
    holdoutRevealed: Boolean(payload.holdout_revealed_at ?? definition.holdout_revealed_at),
  }
}

export function normalizeEquity(raw: any): EquityPoint {
  const item = record(raw)
  return {
    date: String(item.trade_date ?? item.date ?? item.session ?? ''),
    equity: Number(item.equity ?? item.nav ?? item.net_value ?? 0),
    benchmark: numberOrNull(item.benchmark ?? item.benchmark_equity),
    drawdown: numberOrNull(item.drawdown),
    cash: numberOrNull(item.cash),
    annualReturn: numberOrNull(item.annual_return),
  }
}

export function normalizeTrade(raw: any): TradeRecord {
  const item = record(raw)
  return {
    tradeId: String(item.trade_id ?? item.fill_id ?? item.sequence ?? ''),
    code: String(item.code ?? item.symbol ?? ''),
    name: item.name,
    side: String(item.side ?? item.direction ?? ''),
    signalDate: item.signal_date,
    tradeDate: String(item.trade_date ?? item.fill_date ?? item.date ?? ''),
    price: Number(item.price ?? item.fill_price ?? 0),
    quantity: Number(item.quantity ?? item.qty ?? 0),
    fees: Number(item.fees ?? item.total_fee ?? 0),
    pnl: numberOrNull(item.pnl ?? item.realized_pnl),
    returnRate: numberOrNull(item.return_rate ?? item.return),
    exitReason: item.exit_reason,
    blockedReason: item.blocked_reason,
  }
}

export function normalizeSignal(raw: any): SignalRecord {
  const item = record(raw)
  return {
    signalId: String(item.signal_id ?? item.signal_fact_id ?? item._id ?? ''),
    decisionId: item.decision_id ? String(item.decision_id) : undefined,
    code: String(item.code ?? item.symbol ?? ''),
    name: item.name,
    signalDate: String(item.signal_date ?? ''),
    revealDate: String(item.reveal_date ?? ''),
    direction: String(item.direction ?? ''),
    decisionRevealDate: item.decision_reveal_date
      ? String(item.decision_reveal_date)
      : undefined,
    decisionDirection: item.decision_direction !== undefined
      ? String(item.decision_direction)
      : undefined,
    modelId: normalizeModelId(item.model_id ?? item.modelId),
    occurrence: Number(item.occurrence ?? 0),
    primaryTrigger: String(item.primary_trigger ?? item.trigger_key ?? item.entrypoint ?? ''),
    concurrentTriggers: stringArray(item.concurrent_triggers ?? item.concurrent_trigger_keys),
    baseTriggerMask: item.direction_base_trigger_mask ?? item.base_trigger_mask,
    syntheticPrimaryMask: item.synthetic_primary_mask,
    finalTriggerMask: item.concurrent_trigger_mask ?? item.final_trigger_mask,
    rawSignal: numberOrNull(item.raw_signal ?? item.raw) ?? undefined,
    comboId: item.combo_id,
  }
}

const queryParams = (filters: RankingFilters = {}) => ({
  split_id: filters.splitId ?? 'VALIDATION',
  model_id: filters.modelId ? Number(String(filters.modelId).replace(/^S/, '')) : undefined,
  direction: filters.direction ? (['POSITIVE', 'BUY', 'LONG', '1'].includes(String(filters.direction).toUpperCase()) ? 1 : -1) : undefined,
  occurrence: filters.occurrence,
  horizon: filters.horizon,
  primary_trigger: filters.primaryTrigger,
  min_score: filters.minScore,
  page_size: filters.pageSize,
  cursor: filters.cursor,
})

function normalizeError(error: any): ApiErrorShape {
  const status = error?.response?.status
  const payload = record(error?.response?.data?.error ?? error?.error)
  return {
    code: String(payload.code ?? (status ? `HTTP_${status}` : 'NETWORK_ERROR')),
    message: String(payload.message ?? error?.message ?? '请求失败'),
    details: payload.details,
    status,
  }
}

async function request<T>(config: AnyRecord): Promise<T> {
  try {
    return await http(config) as T
  } catch (error) {
    throw normalizeError(error)
  }
}

export const clxBacktestApi = {
  health: () => request({ url: `${BASE}/health`, method: 'get' }).then(unwrapData),

  async listRuns(params: { status?: string; pageSize?: number; cursor?: string } = {}) {
    const response = await request({
      url: `${BASE}/runs`, method: 'get',
      params: { status: params.status, page_size: params.pageSize ?? 100, cursor: params.cursor },
    })
    return normalizePage(response, normalizeRun)
  },

  async createRun(payload: { name: string; config: Record<string, unknown> }) {
    return normalizeRun(unwrapData(await request({ url: `${BASE}/runs`, method: 'post', data: payload })))
  },

  async getRun(runId: string) {
    const payload = record(unwrapData(await request({ url: `${BASE}/runs/${runId}`, method: 'get' })))
    const run = record(payload.run ?? payload)
    return normalizeRun({ ...run, freeze: payload.freeze ?? run.freeze })
  },

  async cloneRun(runId: string, name?: string) {
    return normalizeRun(unwrapData(await request({
      url: `${BASE}/runs/${runId}/clone`, method: 'post', data: name ? { name } : {},
    })))
  },

  async startRun(runId: string) {
    const payload = record(unwrapData(await request({ url: `${BASE}/runs/${runId}/start`, method: 'post' })))
    return { run: normalizeRun(payload.run ?? payload), job: payload.job }
  },

  async cancelRun(runId: string) {
    const payload = record(unwrapData(await request({ url: `${BASE}/runs/${runId}/cancel`, method: 'post' })))
    return normalizeRun(payload.run ?? payload)
  },

  async listRankings(runId: string, filters: RankingFilters = {}) {
    const response = await request({ url: `${BASE}/runs/${runId}/rankings`, method: 'get', params: queryParams(filters) })
    return normalizePage(response, normalizeRanking)
  },

  async getCombo(runId: string, comboId: string, params: { splitId?: string } = {}) {
    return normalizeCombo(await request({
      url: `${BASE}/runs/${runId}/combos/${comboId}`, method: 'get',
      params: { split_id: params.splitId ?? 'VALIDATION' },
    }))
  },

  async getMetrics(runId: string, comboId: string, params: { splitId?: string; horizon?: number } = {}) {
    const response = await request({
      url: `${BASE}/runs/${runId}/combos/${comboId}/metrics`, method: 'get',
      params: { split_id: params.splitId ?? 'VALIDATION', horizon: params.horizon },
    })
    const page = normalizePage(response, (item) => normalizeMetrics(item))
    return page.items
  },

  async getEquity(runId: string, comboId: string, params: { splitId?: string; horizon?: number } = {}) {
    const items: EquityPoint[] = []
    let cursor: string | undefined
    for (let pageIndex = 0; pageIndex < 100; pageIndex += 1) {
      const response = await request({
        url: `${BASE}/runs/${runId}/combos/${comboId}/equity`, method: 'get',
        params: { split_id: params.splitId ?? 'VALIDATION', horizon: params.horizon, page_size: 200, cursor },
      })
      const page = normalizePage(response, normalizeEquity)
      items.push(...page.items)
      if (!page.nextCursor) return { items, nextCursor: null, total: items.length }
      cursor = page.nextCursor
    }
    return { items, nextCursor: cursor ?? null, total: items.length }
  },

  async listTrades(runId: string, comboId: string, params: { splitId?: string; horizon?: number; cursor?: string; pageSize?: number } = {}) {
    const response = await request({
      url: `${BASE}/runs/${runId}/combos/${comboId}/trades`, method: 'get',
      params: { split_id: params.splitId ?? 'VALIDATION', horizon: params.horizon, cursor: params.cursor, page_size: params.pageSize ?? 50 },
    })
    return normalizePage(response, normalizeTrade)
  },

  async listSignals(runId: string, comboId: string, params: { splitId?: string; horizon?: number; cursor?: string; pageSize?: number } = {}) {
    const response = await request({
      url: `${BASE}/runs/${runId}/combos/${comboId}/signals`, method: 'get',
      params: { split_id: params.splitId ?? 'VALIDATION', horizon: params.horizon, cursor: params.cursor, page_size: params.pageSize ?? 50 },
    })
    return normalizePage(response, normalizeSignal)
  },

  async getModelHeatmap(runId: string, params: { splitId?: string; metric?: string; cursor?: string } = {}) {
    const items: HeatmapCell[] = []
    let cursor = params.cursor
    let metric = String(params.metric ?? 'mean_return')
    for (let pageIndex = 0; pageIndex < 50; pageIndex += 1) {
      const response = await request({
        url: `${BASE}/runs/${runId}/model-heatmap`, method: 'get',
        params: { split_id: params.splitId ?? 'VALIDATION', metric: params.metric, cursor, page_size: 200 },
      })
      const payload = record(unwrapData(response))
      metric = String(payload.metric ?? metric)
      const page = normalizePage(response, (raw): HeatmapCell => {
        const item = record(raw)
        return {
          modelId: normalizeModelId(item.model_id ?? item.modelId),
          trigger: String(item.trigger_key ?? item.primary_trigger ?? ''),
          value: numberOrNull(item[metric] ?? item.value ?? item.score),
          sampleCount: numberOrNull(item.sample_count) ?? undefined,
          splitId: item.split_id,
          metric,
        }
      })
      items.push(...page.items)
      if (!page.nextCursor) return { items, nextCursor: null, total: items.length, metric }
      cursor = page.nextCursor
    }
    return { items, nextCursor: cursor ?? null, total: items.length, metric }
  },

  async compare(runId: string, comboIds: string[], splitId: string, horizon?: number): Promise<ComparisonResult> {
    const payload: any = unwrapData(await request({
      url: `${BASE}/compare`, method: 'post', data: { run_id: runId, combo_ids: comboIds, split_id: splitId, horizon },
    }))
    const rawItems = payload?.items ?? payload?.combos ?? payload ?? []
    return {
      runId,
      splitId,
      items: (Array.isArray(rawItems) ? rawItems : []).map((item: any) => {
        const combo = record(item.combo)
        const comboId = String(item.combo_id ?? combo.combo_id ?? '')
        return {
          comboId,
          name: String(item.name ?? item.combo_name ?? item.canonical_dsl ?? combo.name ?? combo.canonical_dsl ?? combo.dsl ?? comboId),
          metrics: normalizeMetrics(item.metrics ?? item),
          equity: (item.equity ?? []).map(normalizeEquity),
          splitId: item.split_id ?? splitId,
        }
      }),
    }
  },

  async getProgress(runId: string): Promise<RunProgress> {
    const payload: any = unwrapData(await request({ url: `${BASE}/runs/${runId}/progress`, method: 'get' }))
    const rawEvents = Array.isArray(payload) ? payload : payload?.items ?? payload?.events ?? []
    const events: ProgressEvent[] = rawEvents.map((raw: any) => ({
      eventId: raw.event_id,
      at: raw.created_at ?? raw.at ?? '',
      level: raw.level ?? (String(raw.event_type ?? '').includes('FAIL') ? 'ERROR' : 'INFO'),
      stage: raw.stage ?? raw.event_type ?? '',
      message: raw.message ?? raw.event_type ?? '',
      completed: numberOrNull(raw.completed) ?? undefined,
      total: numberOrNull(raw.total) ?? undefined,
      percent: numberOrNull(raw.progress ?? raw.percent) ?? undefined,
      details: raw.details,
    }))
    const latest = events.at(-1)
    return {
      runId,
      status: String(payload?.status ?? payload?.run_status ?? 'RUNNING').toUpperCase() as any,
      stage: payload?.stage ?? latest?.stage,
      message: payload?.message ?? latest?.message,
      completed: numberOrNull(payload?.completed) ?? latest?.completed,
      total: numberOrNull(payload?.total) ?? latest?.total,
      percent: numberOrNull(payload?.progress ?? payload?.percent) ?? latest?.percent ?? 0,
      updatedAt: payload?.updated_at ?? latest?.at,
      events,
    }
  },

  progressStreamUrl: (runId: string) => `${BASE}/runs/${encodeURIComponent(runId)}/progress/stream`,

  async getManifest(runId: string): Promise<ManifestRecord> {
    const item: any = unwrapData(await request({ url: `${BASE}/runs/${runId}/manifest`, method: 'get' }))
    return {
      ...item,
      manifestId: item.manifest_id ?? item._id,
      snapshotId: item.snapshot_id,
      signalSetId: item.signal_set_id,
      runId: item.run_id ?? runId,
      sha256: item.manifest_sha256 ?? item.sha256,
      sourceCollectionUuid: item.source_collection_uuid,
      sourceCount: numberOrNull(item.source_count ?? item.count) ?? undefined,
      codeCount: numberOrNull(item.code_count) ?? undefined,
      dateMin: item.date_min ?? item.min_date,
      dateMax: item.date_max ?? item.max_date,
      artifactUri: item.artifact_uri ?? item.artifact_root,
      createdAt: item.created_at,
      payload: item,
    }
  },

  async getQuality(runId: string): Promise<QualityReport> {
    const payload: any = unwrapData(await request({ url: `${BASE}/runs/${runId}/quality`, method: 'get' }))
    const quality = record(payload?.quality)
    const findings = payload?.audit_findings ?? quality.issues ?? []
    return {
      runId,
      status: quality.status ?? payload?.status,
      sourceRows: numberOrNull(quality.source_rows ?? quality.source_count) ?? undefined,
      signalRows: numberOrNull(quality.signal_rows) ?? undefined,
      excludedRows: numberOrNull(quality.excluded_rows) ?? undefined,
      adjustmentGapCount: numberOrNull(quality.adjustment_gap_count ?? quality.known_adjustment_gaps) ?? undefined,
      causalityMismatchRate: numberOrNull(quality.causality_mismatch_rate),
      tradabilityApproximation: quality.tradability_approximation,
      generatedAt: quality.generated_at ?? payload?.created_at,
      issues: (Array.isArray(findings) ? findings : []).map((finding: any) => ({
        code: String(finding.finding_id ?? finding.kind ?? finding.code ?? ''),
        severity: String(finding.severity ?? 'INFO').toUpperCase(),
        title: String(finding.title ?? finding.kind ?? finding.code ?? '数据质量提示'),
        detail: String(finding.detail ?? finding.message ?? (finding.details ? JSON.stringify(finding.details) : '')),
        affectedRows: numberOrNull(finding.affected_rows) ?? undefined,
        affectedCodes: numberOrNull(finding.affected_codes) ?? undefined,
      })),
    }
  },

  async freezeRun(runId: string, specification: FreezeSpecification): Promise<FreezeRecord> {
    const item: any = unwrapData(await request({
      url: `${BASE}/runs/${runId}/freeze`, method: 'post',
      data: {
        validation: {
          selected_combo_ids: specification.validation.selectedComboIds,
          rank_order: specification.validation.rankOrder,
        },
        ranking_config: specification.rankingConfig,
        split_config_sha256: specification.splitConfigSha256,
        frozen_rank_digest: specification.frozenRankDigest,
      },
    }))
    return {
      freezeId: String(item.freeze_id ?? ''), runId: String(item.run_id ?? runId),
      status: String(item.state ?? item.status ?? 'FROZEN'), configSha256: item.run_config_sha256,
      frozenAt: item.created_at, holdoutRevealed: Boolean(item.holdout_revealed_at ?? item.reveal_count),
      revealedAt: item.holdout_revealed_at ?? null, revealCount: Number(item.reveal_count ?? 0),
    }
  },

  async revealHoldout(runId: string, freezeId: string): Promise<FreezeRecord> {
    const item: any = unwrapData(await request({
      url: `${BASE}/runs/${runId}/freezes/${freezeId}/holdout/reveal`, method: 'post',
    }))
    return {
      freezeId: String(item.freeze_id ?? freezeId), runId: String(item.run_id ?? runId),
      status: String(item.state ?? item.status ?? 'REVEALING'), configSha256: item.run_config_sha256,
      frozenAt: item.created_at, holdoutRevealed: Boolean(item.holdout_revealed_at ?? item.reveal_count),
      revealedAt: item.holdout_revealed_at ?? null, revealCount: Number(item.reveal_count ?? 0),
    }
  },

  async createExport(runId: string, data: { resource: string; format: string; comboIds: string[]; splitId?: string }): Promise<ExportJob> {
    const item: any = unwrapData(await request({
      url: `${BASE}/runs/${runId}/exports`, method: 'post',
      data: { resource: data.resource, format: data.format, combo_ids: data.comboIds, split_id: data.splitId ?? 'VALIDATION' },
    }))
    return {
      jobId: String(item.job_id ?? ''), status: String(item.status ?? 'QUEUED'),
      resource: item.resource, format: item.format, splitId: item.split_id, downloadUrl: item.download_url ?? null,
      expiresAt: item.expires_at ?? null, error: item.error ?? null,
    }
  },

  async getExport(jobId: string): Promise<ExportJob> {
    const item: any = unwrapData(await request({ url: `${BASE}/exports/${jobId}`, method: 'get' }))
    return {
      jobId: String(item.job_id ?? jobId), status: String(item.status ?? ''),
      resource: item.resource, format: item.format, splitId: item.split_id, downloadUrl: item.download_url ?? item.url ?? null,
      expiresAt: item.expires_at ?? null, error: item.error ?? null,
    }
  },

  async getCandles(code: string, endDate?: string): Promise<CandlePoint[]> {
    const payload: any = unwrapData(await request({
      url: '/api/stock_data', method: 'get', params: { period: '1d', symbol: code, endDate },
    }))
    const source = payload?.data ?? payload
    if (Array.isArray(source)) {
      return source.map((row: any) => Array.isArray(row)
        ? { date: String(row[0]), open: Number(row[1]), close: Number(row[2]), low: Number(row[3]), high: Number(row[4]), volume: Number(row[5] ?? 0) }
        : { date: String(row.date), open: Number(row.open), high: Number(row.high), low: Number(row.low), close: Number(row.close), volume: Number(row.volume ?? row.vol ?? 0) })
    }
    const dates = source?.date ?? []
    return dates.map((date: string, index: number) => ({
      date, open: Number(source.open?.[index]), high: Number(source.high?.[index]),
      low: Number(source.low?.[index]), close: Number(source.close?.[index]), volume: Number(source.volume?.[index] ?? 0),
    }))
  },
}

export function describeApiError(error: any): string {
  const known = record(error)
  if (known.code === 'HOLDOUT_LOCKED') return '锁定测试集仍处于封存状态，请先冻结研究规则后再执行一次揭示。'
  if (known.code === 'HOLDOUT_ALREADY_REVEALED') return '该冻结版本已经完成过一次锁定测试揭示。'
  if (known.code === 'HOLDOUT_REVEAL_IN_PROGRESS') return '锁定测试揭示任务正在处理中，完成 artifact 校验与投影后自动开放。'
  if (known.code === 'HOLDOUT_REVEAL_FAILED') return '锁定测试揭示任务失败，请保留 ledger 与 artifact 并进行运维检查。'
  if (known.code === 'INVALID_RUN_STATE') return `当前实验状态不允许此操作：${known.message ?? ''}`
  return String(known.message ?? '请求失败，请检查服务状态后重试。')
}
