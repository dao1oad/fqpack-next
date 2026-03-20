import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildInitialKlineSlimPricePanelState,
  createKlineSlimPricePanelActions,
  loadSubjectPriceDetail,
  saveAndActivatePriceGuides,
  saveGuardianPriceGuides,
  saveTakeprofitPriceGuides,
  shouldReloadSubjectPriceDetail,
} from './kline-slim-price-panel.mjs'

const makeDetail = (symbol = '600000', overrides = {}) => ({
  subject: {
    symbol,
    name: symbol === '600000' ? '浦发银行' : '平安银行',
  },
  guardian_buy_grid_config: {
    enabled: true,
    buy_enabled: [true, false, true],
    buy_1: 10.2,
    buy_2: 9.9,
    buy_3: 9.5,
  },
  guardian_buy_grid_state: {
    buy_active: [true, false, true],
  },
  takeprofit: {
    tiers: [
      { level: 1, price: 10.8, manual_enabled: true },
      { level: 2, price: 11.2, manual_enabled: false },
      { level: 3, price: 11.8, manual_enabled: true },
    ],
    state: {
      armed_levels: { 1: true, 2: false, 3: true },
    },
  },
  ...overrides,
})

test('loadSubjectPriceDetail hydrates state and price guide version', async () => {
  const calls = []
  const actions = createKlineSlimPricePanelActions({
    async getDetail(symbol) {
      calls.push(['getDetail', symbol])
      return makeDetail(symbol)
    },
  })
  const state = buildInitialKlineSlimPricePanelState()

  await loadSubjectPriceDetail(state, {
    actions,
    symbol: '600000',
    force: true,
  })

  assert.deepEqual(calls, [['getDetail', '600000']])
  assert.equal(state.guardianDraft.buy_1, 10.2)
  assert.deepEqual(state.guardianDraft.buy_enabled, [true, false, true])
  assert.equal(state.takeprofitDrafts.length, 3)
  assert.equal(state.priceGuideVersion.includes('guardian-buy_1'), true)
  assert.equal(state.lastSubjectDetailSymbol, '600000')
})

test('shouldReloadSubjectPriceDetail only reloads when symbol changes or force is true', () => {
  assert.equal(
    shouldReloadSubjectPriceDetail({
      lastLoadedSymbol: '',
      nextSymbol: '600000',
      force: false,
    }),
    true,
  )
  assert.equal(
    shouldReloadSubjectPriceDetail({
      lastLoadedSymbol: '600000',
      nextSymbol: '600000',
      force: false,
    }),
    false,
  )
  assert.equal(
    shouldReloadSubjectPriceDetail({
      lastLoadedSymbol: '600000',
      nextSymbol: '600000',
      force: true,
    }),
    true,
  )
})

test('saveGuardianPriceGuides validates, saves, reloads and triggers render callback', async () => {
  const calls = []
  const actions = createKlineSlimPricePanelActions({
    async getDetail(symbol) {
      calls.push(['getDetail', symbol])
      return makeDetail(symbol)
    },
    async saveGuardianBuyGrid(symbol, payload) {
      calls.push(['saveGuardianBuyGrid', symbol, payload.buy_1, payload.buy_enabled, payload.enabled])
      return { symbol, ...payload }
    },
  })
  const state = buildInitialKlineSlimPricePanelState()
  let renderCount = 0

  await loadSubjectPriceDetail(state, {
    actions,
    symbol: '600000',
    force: true,
  })
  state.guardianDraft.buy_1 = 10.3
  state.guardianDraft.buy_enabled = [true, false, false]

  const result = await saveGuardianPriceGuides(state, {
    actions,
    symbol: '600000',
    notify: {},
    afterRefresh() {
      renderCount += 1
    },
  })

  assert.deepEqual(calls, [
    ['getDetail', '600000'],
    ['saveGuardianBuyGrid', '600000', 10.3, [true, false, false], true],
    ['getDetail', '600000'],
  ])
  assert.equal(result.ok, true)
  assert.equal(renderCount, 1)
})

test('saveTakeprofitPriceGuides validates, saves, reloads and triggers render callback', async () => {
  const calls = []
  const actions = createKlineSlimPricePanelActions({
    async getDetail(symbol) {
      calls.push(['getDetail', symbol])
      return makeDetail(symbol)
    },
    async saveTakeprofitProfile(symbol, payload) {
      calls.push(['saveTakeprofitProfile', symbol, payload.tiers.map((row) => row.price)])
      return { symbol, ...payload }
    },
  })
  const state = buildInitialKlineSlimPricePanelState()
  let renderCount = 0

  await loadSubjectPriceDetail(state, {
    actions,
    symbol: '600000',
    force: true,
  })
  state.takeprofitDrafts[2].price = 11.9

  const result = await saveTakeprofitPriceGuides(state, {
    actions,
    symbol: '600000',
    notify: {},
    afterRefresh() {
      renderCount += 1
    },
  })

  assert.deepEqual(calls, [
    ['getDetail', '600000'],
    ['saveTakeprofitProfile', '600000', [10.8, 11.2, 11.9]],
    ['getDetail', '600000'],
  ])
  assert.equal(result.ok, true)
  assert.equal(renderCount, 1)
})

test('saveAndActivatePriceGuides saves all six prices, enables them and re-arms active state', async () => {
  const calls = []
  const actions = createKlineSlimPricePanelActions({
    async getDetail(symbol) {
      calls.push(['getDetail', symbol])
      return makeDetail(symbol)
    },
    async saveGuardianBuyGrid(symbol, payload) {
      calls.push(['saveGuardianBuyGrid', symbol, payload.buy_enabled, payload.enabled])
      return { symbol, ...payload }
    },
    async saveGuardianBuyGridState(symbol, payload) {
      calls.push(['saveGuardianBuyGridState', symbol, payload.buy_active, payload.last_reset_reason])
      return { symbol, ...payload }
    },
    async saveTakeprofitProfile(symbol, payload) {
      calls.push([
        'saveTakeprofitProfile',
        symbol,
        payload.tiers.map((row) => ({
          level: row.level,
          price: row.price,
          manual_enabled: row.manual_enabled,
        })),
      ])
      return { symbol, ...payload }
    },
    async rearmTakeprofit(symbol) {
      calls.push(['rearmTakeprofit', symbol])
      return { symbol }
    },
  })
  const state = buildInitialKlineSlimPricePanelState()
  let renderCount = 0

  await loadSubjectPriceDetail(state, {
    actions,
    symbol: '600000',
    force: true,
  })
  state.guardianDraft.buy_enabled = [true, false, false]
  state.takeprofitDrafts[1].manual_enabled = false
  state.takeprofitDrafts[2].manual_enabled = false

  const result = await saveAndActivatePriceGuides(state, {
    actions,
    symbol: '600000',
    notify: {},
    afterRefresh() {
      renderCount += 1
    },
  })

  assert.deepEqual(calls, [
    ['getDetail', '600000'],
    ['saveGuardianBuyGrid', '600000', [true, true, true], true],
    ['saveGuardianBuyGridState', '600000', [true, true, true], 'manual_activate'],
    ['saveTakeprofitProfile', '600000', [
      { level: 1, price: 10.8, manual_enabled: true },
      { level: 2, price: 11.2, manual_enabled: true },
      { level: 3, price: 11.8, manual_enabled: true },
    ]],
    ['rearmTakeprofit', '600000'],
    ['getDetail', '600000'],
  ])
  assert.equal(result.ok, true)
  assert.equal(renderCount, 1)
})

test('loadSubjectPriceDetail ignores stale responses from older symbol requests', async () => {
  const resolvers = new Map()
  const actions = createKlineSlimPricePanelActions({
    getDetail(symbol) {
      return new Promise((resolve) => {
        resolvers.set(symbol, resolve)
      })
    },
  })
  const state = buildInitialKlineSlimPricePanelState()

  const firstLoad = loadSubjectPriceDetail(state, {
    actions,
    symbol: '600000',
    force: true,
  })
  const secondLoad = loadSubjectPriceDetail(state, {
    actions,
    symbol: '000001',
    force: true,
  })

  resolvers.get('000001')?.(makeDetail('000001', {
    guardian_buy_grid_config: {
      enabled: true,
      buy_1: 20.2,
      buy_2: 19.9,
      buy_3: 19.5,
    },
  }))
  await secondLoad
  resolvers.get('600000')?.(makeDetail('600000', {
    guardian_buy_grid_config: {
      enabled: true,
      buy_1: 10.2,
      buy_2: 9.9,
      buy_3: 9.5,
    },
  }))
  await firstLoad

  assert.equal(state.lastSubjectDetailSymbol, '000001')
  assert.equal(state.guardianDraft.buy_1, 20.2)
})

test('loadSubjectPriceDetail clears stale drafts before a different symbol load fails', async () => {
  const actions = createKlineSlimPricePanelActions({
    async getDetail(symbol) {
      if (symbol === '000001') {
        throw new Error('detail failed')
      }
      return makeDetail(symbol)
    },
  })
  const state = buildInitialKlineSlimPricePanelState()

  await loadSubjectPriceDetail(state, {
    actions,
    symbol: '600000',
    force: true,
  })

  const result = await loadSubjectPriceDetail(state, {
    actions,
    symbol: '000001',
    force: true,
  })

  assert.equal(result, false)
  assert.equal(state.subjectPriceDetail, null)
  assert.equal(state.guardianDraft.buy_1, null)
  assert.equal(state.lastSubjectDetailSymbol, '')
  assert.equal(state.subjectDetailError, 'detail failed')
})
