import { beforeEach, describe, expect, it, vi } from 'vitest'
import http from '@/http'
import { clxBacktestApi, describeApiError, normalizeRanking, normalizeRun } from '@/api/clxBacktestApi'

vi.mock('@/http', () => ({ default: vi.fn() }))
const httpMock = vi.mocked(http)

describe('clxBacktestApi 合同适配', () => {
  beforeEach(() => httpMock.mockReset())

  it('将后端 snake_case run 映射为不可变前端模型', () => {
    const run = normalizeRun({
      run_id: 'run-1', name: '实验', status: 'complete', config_sha256: 'abc',
      config: { snapshot_id: 'snap-1', model_ids: ['S0000'], wave_opt: 1560, train: { start: '2020-01-01', end: '2020-12-31' } },
      freeze_id: 'freeze-1', holdout_revealed_at: null,
    })
    expect(run).toMatchObject({ runId: 'run-1', status: 'COMPLETE', configSha256: 'abc', frozen: true, holdoutRevealed: false })
    expect(run.config).toMatchObject({ snapshotId: 'snap-1', modelIds: ['S0000'], waveOpt: 1560 })
  })

  it('兼容冻结排行的研究统计字段', () => {
    const ranking = normalizeRanking({
      combo_id: 'combo-1', frozen_rank: 3, validation_score: 0.71, canonical_dsl: 'ANY_OF(...)',
      model_roots: ['S0002', 'S0007'], mean_return: 0.025, win_rate: 0.57,
      ci_low: 0.01, ci_high: 0.04, fdr_q_value: 0.03, signal_density: 0.12,
      year_positive_ratio: 0.8, holdout_state: 'SEALED', sample_count: 500,
    })
    expect(ranking).toMatchObject({ rank: 3, comboId: 'combo-1', score: 0.71, modelIds: ['S0002', 'S0007'], frozen: true, holdoutRevealed: false })
    expect(ranking.metrics).toMatchObject({ totalReturn: 0.025, winRate: 0.57, fdrQValue: 0.03, coverage: 0.12, stabilityScore: 0.8 })
  })

  it('从 run detail 包装中合并冻结摘要', async () => {
    httpMock.mockResolvedValueOnce({ data: {
      run: { run_id: 'run-1', name: '实验', status: 'COMPLETE', config: {}, config_sha256: 'run-sha' },
      job: null,
      freeze: {
        freeze_id: 'freeze-1', state: 'REVEALED', reveal_count: 1, created_at: '2026-07-22T00:00:00Z',
        holdout_revealed_at: '2026-07-22T01:00:00Z', run_config_sha256: 'run-sha',
      },
    } })
    const run = await clxBacktestApi.getRun('run-1')
    expect(run).toMatchObject({ frozen: true, freezeId: 'freeze-1', holdoutRevealed: true })
    expect(run.freeze).toMatchObject({ freezeId: 'freeze-1', state: 'REVEALED', revealCount: 1, runConfigSha256: 'run-sha' })
  })

  it('组合详情明确使用默认 VALIDATION split', async () => {
    httpMock.mockResolvedValueOnce({ data: { split_id: 'VALIDATION', definition: { combo_id: 'combo-1' }, portfolio_summary: {} } })
    const combo = await clxBacktestApi.getCombo('run-1', 'combo-1')
    expect(combo.splitId).toBe('VALIDATION')
    expect(httpMock).toHaveBeenCalledWith(expect.objectContaining({
      url: '/api/clx-backtest/runs/run-1/combos/combo-1',
      params: { split_id: 'VALIDATION' },
    }))
  })

  it('按 cursor 合同请求排行并规范分页', async () => {
    httpMock.mockResolvedValueOnce({ data: { items: [{ combo_id: 'combo-1', score: 0.4 }], next_cursor: 'next-1' } })
    const page = await clxBacktestApi.listRankings('run-1', { splitId: 'VALIDATION', modelId: 'S0002', occurrence: 3, pageSize: 25, cursor: 'cursor-1' })
    expect(httpMock).toHaveBeenCalledWith(expect.objectContaining({
      url: '/api/clx-backtest/runs/run-1/rankings', method: 'get',
      params: expect.objectContaining({ split_id: 'VALIDATION', model_id: 2, occurrence: 3, page_size: 25, cursor: 'cursor-1' }),
    }))
    expect(page.items[0].comboId).toBe('combo-1')
    expect(page.nextCursor).toBe('next-1')
  })

  it('start/cancel/freeze/reveal/export 使用冻结合同端点', async () => {
    httpMock
      .mockResolvedValueOnce({ data: { run: { run_id: 'run-1', status: 'QUEUED', config: {} }, job: { status: 'QUEUED' } } })
      .mockResolvedValueOnce({ data: { run_id: 'run-1', status: 'CANCEL_REQUESTED', config: {} } })
      .mockResolvedValueOnce({ data: { run_id: 'run-1', freeze_id: 'freeze-1', state: 'FROZEN', reveal_count: 0 } })
      .mockResolvedValueOnce({ data: { run_id: 'run-1', freeze_id: 'freeze-1', state: 'REVEALED', reveal_count: 1 } })
      .mockResolvedValueOnce({ data: { job_id: 'export-1', status: 'QUEUED', resource: 'metrics', format: 'csv', split_id: 'HOLDOUT' } })
    const freezeSpecification = {
      validation: { selectedComboIds: ['a'], rankOrder: ['a', 'b'] },
      rankingConfig: { score: 'validation_score', horizon: 5 },
      splitConfigSha256: `sha256:${'1'.repeat(64)}`,
      frozenRankDigest: `sha256:${'2'.repeat(64)}`,
    }
    expect((await clxBacktestApi.startRun('run-1')).run.status).toBe('QUEUED')
    expect((await clxBacktestApi.cancelRun('run-1')).status).toBe('CANCEL_REQUESTED')
    expect((await clxBacktestApi.freezeRun('run-1', freezeSpecification)).holdoutRevealed).toBe(false)
    expect((await clxBacktestApi.revealHoldout('run-1', 'freeze-1')).holdoutRevealed).toBe(true)
    expect((await clxBacktestApi.createExport('run-1', { resource: 'metrics', format: 'csv', comboIds: ['a'], splitId: 'HOLDOUT' })).jobId).toBe('export-1')
    expect(httpMock.mock.calls.map(call => (call[0] as any).url)).toEqual([
      '/api/clx-backtest/runs/run-1/start',
      '/api/clx-backtest/runs/run-1/cancel',
      '/api/clx-backtest/runs/run-1/freeze',
      '/api/clx-backtest/runs/run-1/freezes/freeze-1/holdout/reveal',
      '/api/clx-backtest/runs/run-1/exports',
    ])
    expect(httpMock.mock.calls[2][0]).toMatchObject({ data: {
      validation: { selected_combo_ids: ['a'], rank_order: ['a', 'b'] },
      ranking_config: { score: 'validation_score', horizon: 5 },
      split_config_sha256: freezeSpecification.splitConfigSha256,
      frozen_rank_digest: freezeSpecification.frozenRankDigest,
    } })
    expect(httpMock.mock.calls[3][0]).not.toHaveProperty('data')
    expect(httpMock.mock.calls[4][0]).toMatchObject({ data: {
      resource: 'metrics', format: 'csv', combo_ids: ['a'], split_id: 'HOLDOUT',
    } })
  })

  it('将 HOLDOUT 锁定错误翻译为明确中文状态', () => {
    expect(describeApiError({ code: 'HOLDOUT_LOCKED' })).toContain('封存')
    expect(describeApiError({ code: 'HOLDOUT_ALREADY_REVEALED' })).toContain('已经完成过一次')
  })
})
