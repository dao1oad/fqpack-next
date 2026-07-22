import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { ElSelect } from 'element-plus'
import ClxComparePanel from '@/components/clx-backtest/ClxComparePanel.vue'
import { clxBacktestApi } from '@/api/clxBacktestApi'
import { mountWithProviders } from '@/test/mountClx'
import { buildFrozenRankDigest, DEFAULT_CLX_RANKING_CONFIG } from '@/utils/clxFreeze'
import {
  fixtureComparison, fixtureEquity, fixtureManifest, fixtureQuality, fixtureRankingPage, fixtureRun,
} from '@/test/fixtures/clxBacktest'

vi.mock('echarts', () => ({ init: vi.fn(() => ({ setOption: vi.fn(), resize: vi.fn(), clear: vi.fn(), dispose: vi.fn() })) }))
vi.mock('@/api/clxBacktestApi', () => ({
  clxBacktestApi: {
    listRuns: vi.fn(), listRankings: vi.fn(), getQuality: vi.fn(), getManifest: vi.fn(), getRun: vi.fn(),
    compare: vi.fn(), getEquity: vi.fn(), freezeRun: vi.fn(), revealHoldout: vi.fn(), createExport: vi.fn(), getExport: vi.fn(),
  },
  describeApiError: (error: any) => error?.message ?? 'fixture error',
}))
const api = vi.mocked(clxBacktestApi)
async function settle() { await flushPromises(); await new Promise(resolve => setTimeout(resolve, 0)); await flushPromises() }

describe('ClxComparePanel F3', () => {
  beforeEach(() => {
    api.listRuns.mockResolvedValue({ items: [fixtureRun], nextCursor: null })
    api.listRankings.mockResolvedValue(fixtureRankingPage)
    api.getQuality.mockResolvedValue(fixtureQuality)
    api.getManifest.mockResolvedValue(fixtureManifest)
    api.getRun.mockResolvedValue(fixtureRun)
    api.compare.mockResolvedValue(fixtureComparison)
    api.getEquity.mockResolvedValue({ items: fixtureEquity, nextCursor: null })
    api.freezeRun.mockResolvedValue({ freezeId: 'freeze-fixture', runId: fixtureRun.runId, status: 'FROZEN', holdoutRevealed: false })
    api.createExport.mockResolvedValue({ jobId: 'export-fixture', status: 'QUEUED', resource: 'metrics', format: 'csv', splitId: 'VALIDATION' })
    api.getExport.mockResolvedValue({ jobId: 'export-fixture', status: 'COMPLETE', resource: 'metrics', format: 'csv', splitId: 'VALIDATION' })
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('展示最多4组合选择、冻结状态、质量偏差、manifest和导出', async () => {
    const wrapper = mountWithProviders(ClxComparePanel)
    await settle()
    expect(wrapper.text()).toContain('已选')
    expect(wrapper.text()).toContain('/ 4')
    expect(wrapper.get('[data-testid="quality-report"]').text()).toContain('幸存者偏差')
    expect(wrapper.get('[data-testid="quality-report"]').text()).toContain('历史 ST / 退市状态')
    expect(wrapper.get('[data-testid="manifest-card"]').text()).toContain(fixtureManifest.sha256)
    expect(wrapper.text()).toContain('一次性揭示 HOLDOUT')
    wrapper.unmount()
  })

  it('选择两个组合后调用 compare 并绘制并列指标', async () => {
    const wrapper = mountWithProviders(ClxComparePanel)
    await settle()
    const comboSelect = wrapper.findAllComponents(ElSelect).find(node => node.props('multiple'))
    expect(comboSelect).toBeTruthy()
    comboSelect!.vm.$emit('update:modelValue', ['combo-a', 'combo-b'])
    await settle()
    await wrapper.get('[data-testid="compare-button"]').trigger('click')
    await settle()
    expect(api.compare).toHaveBeenCalledWith(fixtureRun.runId, ['combo-a', 'combo-b'], 'VALIDATION', undefined)
    expect(wrapper.get('[data-testid="comparison-results"]').text()).toContain('S0002 正向吞没')
    wrapper.unmount()
  })

  it('从 manifest.freeze_input 组装严格冻结材料，对比选择不改变冻结范围', async () => {
    const manifestRankingConfig = { ...DEFAULT_CLX_RANKING_CONFIG, max_total_candidates: 8192 }
    const { rankingConfigSha256, frozenRankDigest } = await buildFrozenRankDigest(
      fixtureRun.runId,
      ['combo-a', 'combo-b'],
      manifestRankingConfig,
    )
    api.listRankings.mockResolvedValue({
      ...fixtureRankingPage,
      items: fixtureRankingPage.items.map(item => ({ ...item, rankingConfigSha256 })),
    })
    api.getManifest.mockResolvedValue({
      ...fixtureManifest,
      payload: {
        ...fixtureManifest.payload,
        freeze_input: {
          validation: {
            selected_combo_ids: ['combo-a', 'combo-b'],
            rank_order: ['combo-a', 'combo-b'],
          },
          ranking_config: manifestRankingConfig,
          ranking_config_sha256: rankingConfigSha256,
          split_config_sha256: `sha256:${'1'.repeat(64)}`,
          frozen_rank_digest: frozenRankDigest,
        },
      },
    })
    const wrapper = mountWithProviders(ClxComparePanel)
    await settle()
    const freezeButton = wrapper.findAll('button').find(node => node.text().includes('冻结当前规则'))!
    expect(freezeButton.attributes('disabled')).toBeUndefined()

    const comboSelect = wrapper.findAllComponents(ElSelect).find(node => node.props('multiple'))!
    comboSelect.vm.$emit('update:modelValue', ['combo-a'])
    await settle()

    const exportButton = wrapper.findAll('button').find(node => node.text().includes('创建可审计导出'))!
    await exportButton.trigger('click')
    await settle()
    expect(api.createExport).toHaveBeenCalledWith(fixtureRun.runId, {
      resource: 'metrics', format: 'csv', comboIds: ['combo-a'], splitId: 'VALIDATION',
    })

    await freezeButton.trigger('click')
    await settle()
    const confirm = Array.from(document.body.querySelectorAll('button')).find(node => node.textContent?.includes('确认冻结')) as HTMLButtonElement
    expect(confirm).toBeTruthy()
    confirm.click()
    await settle()
    expect(api.freezeRun).toHaveBeenCalledWith(fixtureRun.runId, {
      validation: { selectedComboIds: ['combo-a', 'combo-b'], rankOrder: ['combo-a', 'combo-b'] },
      rankingConfig: manifestRankingConfig,
      splitConfigSha256: `sha256:${'1'.repeat(64)}`,
      frozenRankDigest,
    })
    wrapper.unmount()
  })
})
