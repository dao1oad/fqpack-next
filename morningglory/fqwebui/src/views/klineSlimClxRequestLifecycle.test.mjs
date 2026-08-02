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

test('Kline CLX request lifecycle aborts old keys and ignores late history responses', async () => {
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
    } finally {
      Object.assign(clxDailySelectionApi, originalApi)
    }
  } finally {
    await server.close()
  }
})
