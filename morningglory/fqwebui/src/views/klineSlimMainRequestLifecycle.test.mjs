import test from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function payload(label) {
  return { date: [label], close: [1] }
}

let server
let component
let futureApi
let stockData

test.before(async () => {
  server = await createServer({
    configFile: false,
    appType: 'custom',
    server: { middlewareMode: true },
    optimizeDeps: { noDiscovery: true },
    resolve: { alias: { '@': new URL('../', import.meta.url).pathname } }
  })
  ;({ futureApi } = await server.ssrLoadModule('/src/api/futureApi.js'))
  stockData = futureApi.stockData
  ;({ default: component } = await server.ssrLoadModule('/src/views/js/kline-slim.js'))
})

test.after(async () => {
  await server?.close()
})

function createVm() {
  const vm = {
    ...component.data(),
    routeToken: 1,
    routeSymbol: 'OLD',
    currentPeriod: '5m',
    endDateModel: '',
    isRealtimeMode: true,
    showOrderReview: false,
    scheduleRender() {},
    cacheChanlunPeriodPayload: component.methods.cacheChanlunPeriodPayload,
    abortMainDataRequest: component.methods.abortMainDataRequest,
    resetOrderReviewState() {},
    resetClxHistoryState() {}
  }
  return vm
}

test('order review overlay is enabled by default', () => {
  const initial = component.data()
  assert.equal(initial.showOrderReview, true)
})

test('futureApi.stockData forwards request config to http', async () => {
  const controller = new AbortController()
  let receivedConfig
  const result = await stockData(
    { symbol: 'TEST', period: '1d' },
    {
      signal: controller.signal,
      adapter: async (config) => {
        receivedConfig = config
        return {
          data: { ok: true },
          status: 200,
          statusText: 'OK',
          headers: {},
          config
        }
      }
    }
  )

  assert.deepEqual(result, { ok: true })
  assert.equal(receivedConfig.signal, controller.signal)
})

test('different main request owner aborts the old request and ignores its late resolve and reject', async () => {
  const calls = []
  const oldRequest = deferred()
  const newRequest = deferred()
  futureApi.stockData = (data, config) => {
    calls.push({ data, config })
    return calls.length === 1 ? oldRequest.promise : newRequest.promise
  }

  const vm = createVm()
  const first = component.methods.fetchMainData.call(vm, 1)
  const oldSignal = calls[0].config.signal

  vm.routeToken = 2
  vm.routeSymbol = 'NEW'
  vm.currentPeriod = '1d'
  const second = component.methods.fetchMainData.call(vm, 2)

  assert.equal(calls.length, 2)
  assert.equal(oldSignal.aborted, true)
  assert.equal(vm.mainLoading, true)

  oldRequest.resolve(payload('old'))
  await first
  assert.equal(vm.mainData, null)
  assert.equal(vm.mainLoading, true)
  assert.equal(vm.lastError, '')

  newRequest.resolve(payload('new'))
  await second
  assert.equal(vm.mainData.date[0], 'new')
  assert.equal(vm.lastMainBarLabel, 'new')
  assert.equal(vm.mainLoading, false)
  assert.equal(calls[1].data.period, '1d')
  assert.equal(calls[1].config.signal.aborted, false)

  const staleReject = deferred()
  const latest = deferred()
  futureApi.stockData = (_data, config) => {
    calls.push({ config })
    return calls.length === 3 ? staleReject.promise : latest.promise
  }
  vm.routeToken = 3
  vm.routeSymbol = 'STALE'
  const third = component.methods.fetchMainData.call(vm, 3)
  vm.routeToken = 4
  vm.routeSymbol = 'LATEST'
  const fourth = component.methods.fetchMainData.call(vm, 4)
  staleReject.reject(new Error('late failure'))
  await third
  assert.equal(vm.lastError, '')
  assert.equal(vm.mainLoading, true)
  latest.resolve(payload('latest'))
  await fourth
  assert.equal(vm.mainData.date[0], 'latest')
})

test('same active request key is deduplicated and route reset invalidates its owner', async () => {
  const request = deferred()
  let calls = 0
  futureApi.stockData = () => {
    calls += 1
    return request.promise
  }
  const vm = createVm()

  const first = component.methods.fetchMainData.call(vm, 1)
  await component.methods.fetchMainData.call(vm, 1)
  assert.equal(calls, 1)

  const signal = vm.mainAbortController.signal
  component.methods.resetSlimDataState.call(vm)
  assert.equal(signal.aborted, true)
  assert.equal(vm.mainLoading, false)

  vm.routeToken = 2
  request.resolve(payload('stale'))
  await first
  assert.equal(vm.mainData, null)
})

test('first 1d chart route discards the data default 5m legend selection', () => {
  const refreshes = []
  const vm = {
    ...component.data(),
    $route: { query: { symbol: 'TEST', period: '1d' } },
    $router: { replace() {} },
    routeSymbol: 'TEST',
    subjectPanelState: { lastSubjectSymbol: '' },
    chart: null,
    chartController: null,
    showPriceGuidePanel: false,
    showClxWorkbench: false,
    lastSubjectDetailSymbol: '',
    applyClxRouteState() {},
    resetChanlunStructureState() {},
    resetSlimDataState() {},
    stopPolling() {},
    loadSubjectPriceDetail() {},
    refreshVisibleChanlunPeriods: component.methods.refreshVisibleChanlunPeriods,
    ensureChanlunPeriodLoaded(period) {
      refreshes.push(period)
      return Promise.resolve()
    },
    ensureRealtimePolling() {}
  }

  component.methods.handleRouteChange.call(vm)

  assert.equal(vm.periodLegendSelected['1d'], true)
  assert.equal(vm.periodLegendSelected['5m'], false)
  assert.deepEqual(vm.visibleChanlunPeriods, [])
  assert.deepEqual(refreshes, ['1d'])
})


test('main period switch resets chanlun period legend to the new current period only', () => {
  const refreshes = []
  const vm = {
    ...component.data(),
    $route: { query: { symbol: 'TEST', period: '15m' } },
    $router: { replace() {} },
    routeSymbol: 'TEST',
    subjectPanelState: { lastSubjectSymbol: '' },
    chart: null,
    chartController: null,
    showPriceGuidePanel: false,
    showClxWorkbench: false,
    lastHandledChartRouteKey: 'TEST|30m|',
    currentPeriod: '30m',
    periodLegendSelected: { '1m': true, '5m': true, '15m': false, '30m': true, '1d': true },
    priceGuideLegendSelected: { '价格辅助线': true },
    clxLegendSelected: true,
    lastSubjectDetailSymbol: '',
    applyClxRouteState() {},
    resetChanlunStructureState() {},
    resetSlimDataState() {},
    stopPolling() {},
    loadSubjectPriceDetail() {},
    refreshVisibleChanlunPeriods: component.methods.refreshVisibleChanlunPeriods,
    ensureChanlunPeriodLoaded(period) {
      refreshes.push(period)
      return Promise.resolve()
    },
    ensureRealtimePolling() {}
  }

  component.methods.handleRouteChange.call(vm)

  assert.equal(vm.periodLegendSelected['15m'], true)
  assert.equal(vm.periodLegendSelected['1m'], false)
  assert.equal(vm.periodLegendSelected['5m'], false)
  assert.equal(vm.periodLegendSelected['30m'], false)
  assert.equal(vm.periodLegendSelected['1d'], false)
  assert.deepEqual(vm.visibleChanlunPeriods, [])
  assert.deepEqual(vm.priceGuideLegendSelected, { '价格辅助线': true })
  assert.equal(vm.clxLegendSelected, true)
  assert.deepEqual(refreshes, ['15m'])
})
