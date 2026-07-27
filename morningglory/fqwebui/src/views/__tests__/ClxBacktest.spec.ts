import { defineComponent, h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import projectRouter from '@/router'
import ClxBacktest from '@/views/ClxBacktest.vue'
import { clxBacktestApi } from '@/api/clxBacktestApi'

vi.mock('@/api/clxBacktestApi', () => ({ clxBacktestApi: { health: vi.fn().mockResolvedValue({ status: 'ok' }) } }))
const ResultsStub = defineComponent({ name: 'ClxResultsPanel', setup: () => () => h('div', { 'data-testid': 'results-stub' }, '结果面板') })
const ExperimentsStub = defineComponent({ name: 'ClxExperimentsPanel', setup: () => () => h('div', { 'data-testid': 'experiments-stub' }, '实验面板') })
const CompareStub = defineComponent({ name: 'ClxComparePanel', setup: () => () => h('div', { 'data-testid': 'compare-stub' }, '对比面板') })

describe('CLX 工作台路由与窄屏结构', () => {
  afterEach(() => { document.body.innerHTML = '' })

  it('注册 /clx-backtest 正式路由', () => {
    const route = projectRouter.getRoutes().find(item => item.name === 'clx-backtest')
    expect(route?.path).toBe('/clx-backtest')
  })

  it('在同一路由提供 F1/F2/F3 三个工作面并同步 query', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/clx-backtest', component: ClxBacktest }] })
    await router.push('/clx-backtest')
    const wrapper = mount(ClxBacktest, {
      attachTo: document.body,
      global: { plugins: [ElementPlus, router], stubs: { ClxResultsPanel: ResultsStub, ClxExperimentsPanel: ExperimentsStub, ClxComparePanel: CompareStub } },
    })
    await router.isReady()
    expect(wrapper.get('[data-testid="clx-workbench"]').text()).toContain('CLX 大规模回测研究工作台')
    expect(wrapper.get('[data-testid="results-stub"]').exists()).toBe(true)
    await wrapper.get('[data-testid="tab-experiments"]').trigger('click')
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(wrapper.get('[data-testid="experiments-stub"]').exists()).toBe(true)
    expect(router.currentRoute.value.query.tab).toBe('experiments')
    await wrapper.get('[data-testid="tab-compare"]').trigger('click')
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(wrapper.get('[data-testid="compare-stub"]').exists()).toBe(true)
    expect(clxBacktestApi.health).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('窄屏仍保留三工作面入口和研究状态', async () => {
    Object.defineProperty(window, 'innerWidth', { value: 390, configurable: true })
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/clx-backtest', component: ClxBacktest }] })
    await router.push('/clx-backtest')
    const wrapper = mount(ClxBacktest, { global: { plugins: [ElementPlus, router], stubs: { ClxResultsPanel: ResultsStub, ClxExperimentsPanel: ExperimentsStub, ClxComparePanel: CompareStub } } })
    expect(wrapper.findAll('.clx-workbench__tabs button')).toHaveLength(3)
    expect(wrapper.text()).toContain('HOLDOUT SEALED')
    expect(document.body.classList.contains('clx-backtest-page')).toBe(true)
    wrapper.unmount()
    expect(document.body.classList.contains('clx-backtest-page')).toBe(false)
  })
})
