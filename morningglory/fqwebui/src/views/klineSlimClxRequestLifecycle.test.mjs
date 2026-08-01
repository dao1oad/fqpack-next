import assert from 'node:assert/strict'
import test from 'node:test'

import { createServer } from 'vite'

const createDeferred = () => {
  let resolve
  const promise = new Promise((resolver) => {
    resolve = resolver
  })
  return { promise, resolve }
}

const nextTask = () => new Promise((resolve) => setTimeout(resolve, 0))

const createScopePayload = (scopeId) => ({
  items: [{
    batch_id: scopeId,
    trade_date: '2026-08-01',
    status: 'running',
    release_status: 'partial',
    is_final: false,
    partitions: {
      stock: { status: 'completed' },
      etf: { status: 'running' },
    },
  }],
})

const createHistoryPayload = (markerId, triggerDate) => ({
  calculation_profile: {
    id: 'production_v1',
    switch_opt: 1,
  },
  future_function_guard: { passed: true },
  markers_by_model: {
    S0002: [{ marker_id: markerId, trigger_date: triggerDate }],
  },
})

test('Kline CLX request lifecycle aborts old keys and ignores late history and sidebar responses', async () => {
  const server = await createServer({
    root: process.cwd(),
    server: { middlewareMode: true },
    appType: 'custom',
    logLevel: 'silent',
  })

  try {
    const [{ default: component }, { clxDailySelectionApi }] = await Promise.all([
      server.ssrLoadModule('/src/views/js/kline-slim.js'),
      server.ssrLoadModule('/src/api/clxDailySelectionApi.js'),
    ])
    const originalApi = {
      getSignalHistory: clxDailySelectionApi.getSignalHistory,
      getBatches: clxDailySelectionApi.getBatches,
      queryBatchResults: clxDailySelectionApi.queryBatchResults,
    }

    try {
      const historyCalls = []
      clxDailySelectionApi.getSignalHistory = (params, config) => {
        const pending = createDeferred()
        historyCalls.push({ params, signal: config.signal, pending })
        return pending.promise
      }

      const historyVm = {
        ...component.data(),
        routeSymbol: 'sz000001',
        showClxWorkbench: true,
        clxAssetType: 'stock',
        endDateModel: '2026-08-01',
        scheduleRender() {},
      }
      historyVm.abortClxHistoryRequest = component.methods.abortClxHistoryRequest.bind(historyVm)
      historyVm.loadClxHistory = component.methods.loadClxHistory.bind(historyVm)

      const oldHistoryRequest = historyVm.loadClxHistory()
      historyVm.clxAssetType = 'etf'
      const currentHistoryRequest = historyVm.loadClxHistory()

      assert.equal(historyCalls.length, 2)
      assert.equal(historyCalls[0].signal.aborted, true)
      assert.deepEqual(historyCalls.map(({ params }) => params.assetType), ['stock', 'etf'])

      historyCalls[1].pending.resolve(createHistoryPayload('current-marker', '2026-08-01'))
      await currentHistoryRequest
      historyCalls[0].pending.resolve(createHistoryPayload('late-marker', '2026-07-31'))
      await oldHistoryRequest

      assert.equal(historyVm.clxSignalHistory.markers[0].id, 'current-marker')
      assert.equal(historyVm.clxHistoryLoadedKey, 'sz000001__etf__2026-08-01__250')

      const batchCalls = []
      const resultCalls = []
      clxDailySelectionApi.getBatches = (params, config) => {
        const pending = createDeferred()
        batchCalls.push({ params, signal: config.signal, pending })
        return pending.promise
      }
      clxDailySelectionApi.queryBatchResults = (scopeId, data, config) => {
        const pending = createDeferred()
        resultCalls.push({ scopeId, data, signal: config.signal, pending })
        return pending.promise
      }

      const sidebarVm = {
        ...component.data(),
        $route: { query: { clxScope: 'scope-a' } },
        loadClxCatalog: async () => null,
      }
      sidebarVm.loadClxSidebar = component.methods.loadClxSidebar.bind(sidebarVm)

      const oldSidebarRequest = sidebarVm.loadClxSidebar()
      sidebarVm.$route.query = {
        clxScope: 'scope-b',
        clxModels: 'S0003',
      }
      sidebarVm.clxSidebarOnlyCurrentFilters = true
      const currentSidebarRequest = sidebarVm.loadClxSidebar()

      assert.equal(batchCalls.length, 2)
      assert.equal(batchCalls[0].signal.aborted, true)

      batchCalls[1].pending.resolve(createScopePayload('scope-b'))
      await nextTask()
      assert.deepEqual(resultCalls.map(({ scopeId }) => scopeId), ['scope-b'])
      assert.deepEqual(resultCalls[0].data.model_keys, ['S0003'])

      resultCalls[0].pending.resolve({
        rows: [{
          asset_type: 'stock',
          symbol: 'sz000002',
          name: 'current-result',
          model_keys: ['S0003'],
          condition_keys: ['buy'],
        }],
        total: 1,
      })
      await currentSidebarRequest
      batchCalls[0].pending.resolve(createScopePayload('scope-a'))
      await oldSidebarRequest

      assert.equal(sidebarVm.clxSidebarScope.scopeId, 'scope-b')
      assert.deepEqual(sidebarVm.clxSelectionItems.map(({ symbol }) => symbol), ['sz000002'])
      assert.equal(sidebarVm.clxSidebarLoadedKey, 'scope-b__S0003|')
    } finally {
      Object.assign(clxDailySelectionApi, originalApi)
    }
  } finally {
    await server.close()
  }
})
