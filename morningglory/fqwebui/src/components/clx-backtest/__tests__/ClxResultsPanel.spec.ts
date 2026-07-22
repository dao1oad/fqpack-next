import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { ElOption } from 'element-plus'
import ClxResultsPanel from '@/components/clx-backtest/ClxResultsPanel.vue'
import { clxBacktestApi } from '@/api/clxBacktestApi'
import { mountWithProviders } from '@/test/mountClx'
import {
  fixtureCandles, fixtureCombo, fixtureEquity, fixtureHeatmap, fixtureRankingPage,
  fixtureRun, fixtureSignals, fixtureTrades,
} from '@/test/fixtures/clxBacktest'

vi.mock('echarts', () => ({ init: vi.fn(() => ({ setOption: vi.fn(), resize: vi.fn(), clear: vi.fn(), dispose: vi.fn() })) }))
vi.mock('@/api/clxBacktestApi', () => ({
  clxBacktestApi: {
    listRuns: vi.fn(), listRankings: vi.fn(), getModelHeatmap: vi.fn(), getCombo: vi.fn(), getEquity: vi.fn(),
    listTrades: vi.fn(), listSignals: vi.fn(), getCandles: vi.fn(),
  },
  describeApiError: (error: any) => error?.message ?? 'fixture error',
}))
const api = vi.mocked(clxBacktestApi)

async function settle() { await flushPromises(); await new Promise(resolve => setTimeout(resolve, 0)); await flushPromises() }

describe('ClxResultsPanel F1', () => {
  beforeEach(() => {
    api.listRuns.mockResolvedValue({ items: [fixtureRun], nextCursor: null })
    api.listRankings.mockResolvedValue(fixtureRankingPage)
    api.getModelHeatmap.mockResolvedValue({ items: fixtureHeatmap, nextCursor: null, metric: 'mean_return' })
    api.getCombo.mockResolvedValue(fixtureCombo)
    api.getEquity.mockResolvedValue({ items: fixtureEquity, nextCursor: null })
    api.listTrades.mockResolvedValue({ items: fixtureTrades, nextCursor: null })
    api.listSignals.mockResolvedValue({ items: fixtureSignals, nextCursor: null })
    api.getCandles.mockResolvedValue(fixtureCandles)
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('渲染筛选排行、18模型热力图、指标卡和组合下钻', async () => {
    const wrapper = mountWithProviders(ClxResultsPanel)
    await settle()
    expect(wrapper.get('[data-testid="ranking-filters"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="ranking-table"]').text()).toContain('S0002 正向吞没')
    expect(wrapper.get('[data-testid="model-trigger-heatmap"]').text()).toContain('18 模型 × 主触发热力图')
    expect(wrapper.get('[data-testid="metric-cards"]').text()).toContain('综合得分')
    expect(wrapper.get('[data-testid="combo-detail"]').text()).toContain('ALL_OF')
    expect(wrapper.get('[data-testid="performance-charts"]').text()).toContain('净值、回撤与年度收益')
    expect(api.listRankings).toHaveBeenCalledWith(fixtureRun.runId, expect.objectContaining({ splitId: 'VALIDATION', pageSize: 25 }))
    const holdoutOption = wrapper.findAllComponents(ElOption).find(option => option.props('value') === 'HOLDOUT')
    expect(holdoutOption?.props('disabled')).toBe(true)
    wrapper.unmount()
  })

  it('从信号明细打开K线信号下钻', async () => {
    const wrapper = mountWithProviders(ClxResultsPanel)
    await settle()
    const signalTab = wrapper.findAll('.el-tabs__item').find(node => node.text().includes('信号明细'))
    expect(signalTab).toBeTruthy()
    await signalTab!.trigger('click')
    await settle()
    const klineButton = wrapper.findAll('button').find(node => node.text().includes('看K线'))
    expect(klineButton).toBeTruthy()
    await klineButton!.trigger('click')
    await settle()
    expect(api.getCandles).toHaveBeenCalledWith('000001', '2023-03-01')
    expect(document.body.textContent).toContain('日线（前后窗口）')
    expect(document.body.textContent).toContain('同K线并发触发')
    wrapper.unmount()
  })
})
