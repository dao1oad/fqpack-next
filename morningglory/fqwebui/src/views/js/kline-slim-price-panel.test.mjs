import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildInitialKlineSlimPricePanelState,
  createKlineSlimPricePanelActions,
  loadSubjectPriceDetail,
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
      calls.push(['saveGuardianBuyGrid', symbol, payload.buy_1, payload.enabled])
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
    ['saveGuardianBuyGrid', '600000', 10.3, true],
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
