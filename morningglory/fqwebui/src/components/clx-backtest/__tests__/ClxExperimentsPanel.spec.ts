import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import ClxExperimentsPanel from '@/components/clx-backtest/ClxExperimentsPanel.vue'
import { clxBacktestApi } from '@/api/clxBacktestApi'
import { mountWithProviders } from '@/test/mountClx'
import { fixtureDraftRun, fixtureProgress, fixtureRun } from '@/test/fixtures/clxBacktest'

vi.mock('@/api/clxBacktestApi', () => ({
  clxBacktestApi: {
    listRuns: vi.fn(), getRun: vi.fn(), getProgress: vi.fn(), cloneRun: vi.fn(), createRun: vi.fn(), startRun: vi.fn(), cancelRun: vi.fn(),
    progressStreamUrl: vi.fn((id: string) => `/api/clx-backtest/runs/${id}/progress/stream`),
  },
  describeApiError: (error: any) => error?.message ?? 'fixture error',
}))
const api = vi.mocked(clxBacktestApi)
const runningRun = { ...fixtureRun, runId: 'run-fixture-running', name: '运行中的实验', status: 'RUNNING' as const }
async function settle() { await flushPromises(); await new Promise(resolve => setTimeout(resolve, 0)); await flushPromises() }

describe('ClxExperimentsPanel F2', () => {
  beforeEach(() => {
    api.listRuns.mockResolvedValue({ items: [fixtureRun, fixtureDraftRun, runningRun], nextCursor: null })
    api.getRun.mockImplementation(async (runId: string) => (
      [fixtureRun, fixtureDraftRun, runningRun].find(run => run.runId === runId) ?? fixtureRun
    ))
    api.getProgress.mockResolvedValue(fixtureProgress)
    api.cloneRun.mockResolvedValue({ ...fixtureDraftRun, runId: 'run-cloned' })
    api.createRun.mockResolvedValue(fixtureDraftRun)
    api.startRun.mockResolvedValue({ run: { ...fixtureDraftRun, status: 'QUEUED' }, job: { status: 'QUEUED' } })
    api.cancelRun.mockResolvedValue({ ...runningRun, status: 'CANCEL_REQUESTED' })
  })
  afterEach(() => { document.body.innerHTML = ''; vi.useRealTimers() })

  it('展示运行清单、进度事件和不可变配置摘要', async () => {
    const wrapper = mountWithProviders(ClxExperimentsPanel)
    await settle()
    expect(wrapper.text()).toContain('CLX 因果验证基线')
    expect(wrapper.get('[data-testid="run-progress"]').text()).toContain('artifact 与 manifest 已发布')
    const run = wrapper.get('[data-testid="run-run-fixture-complete"]')
    const configButton = run.findAll('button').find(node => node.text() === '配置')
    await configButton!.trigger('click')
    await settle()
    expect(document.body.textContent).toContain('不可变研究配置')
    expect(document.body.textContent).toContain('T 日确认 → T+1 开盘')
    wrapper.unmount()
  })

  it('支持克隆以及新建实验入口，并显式展示固定研究合同', async () => {
    const wrapper = mountWithProviders(ClxExperimentsPanel)
    await settle()
    const draft = wrapper.get('[data-testid="run-run-fixture-draft"]')
    const cloneButton = draft.findAll('button').find(node => node.text() === '克隆')
    await cloneButton!.trigger('click')
    await settle()
    expect(api.cloneRun).toHaveBeenCalledWith('run-fixture-draft', '下一轮组合实验 · 克隆')

    await wrapper.get('[data-testid="create-run-button"]').trigger('click')
    await settle()
    expect(document.body.textContent).toContain('新建 CLX 回测实验')
    expect(document.body.textContent).toContain('WAVEOPT=1560')
    expect(document.body.textContent).toContain('S0000～S0017')
    wrapper.unmount()
  })

  it('按冻结研究合同创建默认实验配置', async () => {
    const wrapper = mountWithProviders(ClxExperimentsPanel)
    await settle()
    await wrapper.get('[data-testid="create-run-button"]').trigger('click')
    await settle()

    const panel = wrapper.findComponent(ClxExperimentsPanel)
    const state = (panel.vm as any).$?.setupState
    expect(state.form.initialCash).toBe(10000000)
    expect(state.form.horizons).toEqual(['1', '3', '5', '10', '20'])
    Object.assign(state.form, {
      name: '默认研究合同', snapshotId: 'snapshot-fixture',
      trainStart: '2020-01-01', trainEnd: '2020-12-31',
      validationStart: '2021-01-01', validationEnd: '2021-12-31',
      holdoutStart: '2022-01-01', holdoutEnd: '2022-12-31',
    })
    await state.createRun()
    await settle()

    expect(api.createRun).toHaveBeenCalledWith({
      name: '默认研究合同',
      config: expect.objectContaining({
        horizons: [1, 3, 5, 10, 20],
        initial_cash: 10000000,
        signal_price_domain: 'QFQ_OHLC_RAW_VOLUME',
        execution_price_domain: 'RAW',
        execution_timing: 'T1_OPEN',
      }),
    })
    wrapper.unmount()
  })

  it('针对草稿和运行态显示受控启动/取消动作', async () => {
    const wrapper = mountWithProviders(ClxExperimentsPanel)
    await settle()
    expect(wrapper.get('[data-testid="run-run-fixture-draft"]').text()).toContain('启动')
    expect(wrapper.get('[data-testid="run-run-fixture-running"]').text()).toContain('取消')
    expect(wrapper.get('[data-testid="run-run-fixture-complete"]').text()).toContain('查看结果')
    wrapper.unmount()
  })

  it('轮询进度时同步 worker 终态并停止展示运行操作', async () => {
    api.getRun.mockResolvedValue({ ...runningRun, status: 'COMPLETE' })
    const wrapper = mountWithProviders(ClxExperimentsPanel)
    await settle()
    await wrapper.get('[data-testid="run-run-fixture-running"]').trigger('click')
    await settle()
    const state = (wrapper.vm as any).$?.setupState
    await state.loadProgress()
    await settle()
    expect(wrapper.get('[data-testid="run-run-fixture-running"]').text()).toContain('查看结果')
    expect(wrapper.get('[data-testid="run-run-fixture-running"]').text()).not.toContain('取消')
    wrapper.unmount()
  })
})
