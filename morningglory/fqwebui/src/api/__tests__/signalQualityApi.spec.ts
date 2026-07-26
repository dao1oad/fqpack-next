import { beforeEach, describe, expect, it, vi } from 'vitest'

const httpMock = vi.fn()
vi.mock('@/http', () => ({ default: (...args: any[]) => httpMock(...args) }))

import { normalizeCell, signalQualityApi } from '@/api/signalQualityApi'

const rawCell = {
  cell_id: 'S0000|ENGULFING|+1',
  model_code: 'S0000',
  model_id: 0,
  trigger: 'ENGULFING',
  direction: 1,
  splits: {
    TRAIN: {
      n_total: 1240,
      n_blocked: 40,
      n_executable: 1200,
      execution_rate: 0.967742,
      mean_excess: 0.006,
      median_excess: 0.001,
      std_excess: 0.05,
      win_rate: 0.52,
      t_stat: 4.1,
      p_value: 0.00004,
      fdr_q_value: 0.001,
      net_mean_excess: 0.001,
      information_ratio: 0.12,
      yearly_mean_excess: { '2019': 0.008 },
      worst_year_mean: 0.004,
      positive_year_ratio: 1,
      horizon_decay: { '1': 0.002, '5': 0.006 },
      random_pool_control: { reps: 300, draw_n: 1000, control_mean: 0.0002, percentile: 0.99 },
    },
  },
  qualification: { status: 'CORE', checks: { train_fdr: true } },
}

describe('signalQualityApi', () => {
  beforeEach(() => httpMock.mockReset())

  it('normalizes cells to camelCase with numeric coercion', () => {
    const cell = normalizeCell(rawCell)
    expect(cell.cellId).toBe('S0000|ENGULFING|+1')
    expect(cell.modelCode).toBe('S0000')
    expect(cell.direction).toBe(1)
    expect(cell.qualification.status).toBe('CORE')
    const train = cell.splits.TRAIN
    expect(train.nExecutable).toBe(1200)
    expect(train.meanExcess).toBeCloseTo(0.006)
    expect(train.fdrQValue).toBeCloseTo(0.001)
    expect(train.yearlyMeanExcess['2019']).toBeCloseTo(0.008)
    expect(train.horizonDecay['5']).toBeCloseTo(0.006)
    expect(train.randomPoolControl?.percentile).toBeCloseTo(0.99)
    expect(train.dateShiftControl).toBeNull()
  })

  it('tolerates missing optional statistics', () => {
    const cell = normalizeCell({
      cell_id: 'S0005|MACD_CROSS|-1',
      model_code: 'S0005',
      model_id: 5,
      trigger: 'MACD_CROSS',
      direction: -1,
      splits: { TRAIN: { n_total: 12, n_blocked: 2, n_executable: 10 } },
      qualification: { status: 'REJECTED', checks: {} },
    })
    expect(cell.splits.TRAIN.meanExcess).toBeNull()
    expect(cell.splits.TRAIN.randomPoolControl).toBeNull()
    expect(cell.qualification.status).toBe('REJECTED')
  })

  it('requests summary and unwraps envelope', async () => {
    httpMock.mockResolvedValueOnce({
      data: {
        schema_version: '1.0',
        run_id: 'RUN_X',
        generated_at: '2026-07-26T00:00:00+00:00',
        methodology: { primary_horizon: 5 },
        status_counts: { CORE: 1 },
        cell_count: 1,
        models: ['S0000'],
        triggers: ['ENGULFING'],
      },
    })
    const summary = await signalQualityApi.summary('RUN_X')
    expect(httpMock).toHaveBeenCalledWith({
      url: '/api/clx-backtest/runs/RUN_X/signal-quality',
      method: 'get',
    })
    expect(summary.cellCount).toBe(1)
    expect(summary.models).toEqual(['S0000'])
  })

  it('passes filters through to the cells endpoint', async () => {
    httpMock.mockResolvedValueOnce({
      data: { run_id: 'RUN_X', generated_at: 'now', cell_count: 1, items: [rawCell] },
    })
    const result = await signalQualityApi.cells('RUN_X', {
      splitId: 'TRAIN',
      direction: 1,
      status: 'CORE',
      minExecutable: 500,
    })
    expect(httpMock).toHaveBeenCalledWith({
      url: '/api/clx-backtest/runs/RUN_X/signal-quality/cells',
      method: 'get',
      params: {
        split_id: 'TRAIN',
        direction: 1,
        model_id: undefined,
        trigger: undefined,
        status: 'CORE',
        min_executable: 500,
      },
    })
    expect(result.items).toHaveLength(1)
    expect(result.items[0].modelCode).toBe('S0000')
  })
})
