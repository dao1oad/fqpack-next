import test from 'node:test'
import assert from 'node:assert/strict'

import { createReconciliationWorkbenchActions } from './reconciliationWorkbench.mjs'
import { createReconciliationWorkbenchPageController } from './reconciliationWorkbenchPage.mjs'

test('reconciliation workbench actions compose overview rows and symbol workspace from existing APIs', async () => {
  const calls = []
  const actions = createReconciliationWorkbenchActions({
    positionApi: {
      async getReconciliation() {
        calls.push(['getReconciliation'])
        return {
          summary: {
            row_count: 1,
            audit_status_counts: { ERROR: 1, WARN: 0, OK: 0 },
            rule_counts: {
              R1: { OK: 0, WARN: 0, ERROR: 1 },
              R2: { OK: 1, WARN: 0, ERROR: 0 },
              R3: { OK: 1, WARN: 0, ERROR: 0 },
              R4: { OK: 0, WARN: 0, ERROR: 1 },
            },
            reconciliation_state_counts: {
              ALIGNED: 0,
              OBSERVING: 0,
              AUTO_RECONCILED: 0,
              BROKEN: 0,
              DRIFT: 1,
            },
          },
          rows: [
            {
              symbol: '600000',
              name: '浦发银行',
              audit_status: 'ERROR',
              broker: { quantity: 500 },
              snapshot: { quantity: 500 },
              entry_ledger: { quantity: 0 },
              slice_ledger: { quantity: 0 },
              compat_projection: { quantity: 0 },
              stock_fills_projection: { quantity: 0 },
              reconciliation: {
                state: 'DRIFT',
                signed_gap_quantity: 500,
                open_gap_count: 1,
              },
              rule_results: {},
              surface_values: {},
              evidence_sections: {
                surfaces: [],
                rules: [],
                reconciliation: { state: 'DRIFT' },
              },
              mismatch_codes: ['broker_vs_entry_quantity_mismatch'],
            },
          ],
        }
      },
    },
    orderApi: {
      async listOrders(params) {
        calls.push(['listOrders', params.symbol])
        return { rows: [], total: 0, page: 1, size: 20 }
      },
      async getOrderDetail(orderId) {
        calls.push(['getOrderDetail', orderId])
        return {
          order: { internal_order_id: orderId, symbol: '600000', side: 'buy', state: 'FILLED' },
          request: {},
          events: [],
          trades: [],
          identifiers: {},
        }
      },
      async getStats(params) {
        calls.push(['getStats', params.symbol])
        return {
          total: 0,
          side_distribution: { buy: 0, sell: 0 },
          state_distribution: {},
          missing_broker_order_count: 0,
        }
      },
    },
    tpslApi: {
      async getManagementDetail(symbol) {
        calls.push(['getManagementDetail', symbol])
        return {
          symbol,
          name: '浦发银行',
          position: { quantity: 500, amount: 500000 },
          entries: [],
          entry_slices: [],
          reconciliation: { state: 'aligned' },
          history: [],
        }
      },
    },
    reconciliationApi: {
      async getSymbolWorkspace(symbol) {
        calls.push(['getSymbolWorkspace', symbol])
        return {
          detail: {
            symbol,
            reconciliation: { state: 'OBSERVING' },
          },
          gaps: [{ gap_id: 'gap_1', state: 'OPEN' }],
          resolutions: [{ resolution_id: 'resolution_1', gap_id: 'gap_1' }],
          rejections: [{ rejection_id: 'rejection_1', reason_code: 'non_board_lot_quantity' }],
        }
      },
    },
  })

  const overview = await actions.loadOverview()
  const workspace = await actions.loadSymbolWorkspace('600000')

  assert.equal(overview.summary.row_count, 1)
  assert.equal(overview.rows[0].symbol, '600000')
  assert.equal(overview.rows[0].audit_status, 'ERROR')
  assert.equal(workspace.symbol, '600000')
  assert.equal(workspace.reconciliation.state, 'ALIGNED')
  assert.equal(workspace.reconciliationDetail.reconciliation.state, 'OBSERVING')
  assert.equal(workspace.resolutionDataStatus, 'loaded')
  assert.equal(workspace.gaps[0].gap_id, 'gap_1')
  assert.equal(workspace.resolutions[0].resolution_id, 'resolution_1')
  assert.equal(workspace.rejections[0].rejection_id, 'rejection_1')
  assert.deepEqual(calls, [
    ['getReconciliation'],
    ['getManagementDetail', '600000'],
    ['getSymbolWorkspace', '600000'],
  ])
})

test('reconciliation workbench actions fall back to TPSL detail when reconciliation workspace endpoint returns 404', async () => {
  const calls = []
  const actions = createReconciliationWorkbenchActions({
    positionApi: {
      async getReconciliation() {
        return { summary: {}, rows: [] }
      },
    },
    orderApi: {
      async listOrders() {
        return { rows: [], total: 0, page: 1, size: 20 }
      },
      async getOrderDetail() {
        return null
      },
      async getStats() {
        return { total: 0, missing_broker_order_count: 0 }
      },
    },
    tpslApi: {
      async getManagementDetail(symbol) {
        calls.push(['getManagementDetail', symbol])
        return {
          symbol,
          name: '证券ETF',
          position: { quantity: 1200, amount: 120000 },
          entries: [{ entry_id: 'entry_512070_1' }],
          entry_slices: [{ entry_slice_id: 'slice_512070_1', entry_id: 'entry_512070_1' }],
          reconciliation: { state: 'aligned' },
          history: [],
        }
      },
    },
    reconciliationApi: {
      async getSymbolWorkspace(symbol) {
        calls.push(['getSymbolWorkspace', symbol])
        const error = new Error('Request failed with status code 404')
        error.response = { status: 404 }
        throw error
      },
    },
  })

  const workspace = await actions.loadSymbolWorkspace('512070')

  assert.equal(workspace.symbol, '512070')
  assert.equal(workspace.entries[0].entry_id, 'entry_512070_1')
  assert.equal(workspace.entry_slices[0].entry_slice_id, 'slice_512070_1')
  assert.deepEqual(workspace.gaps, [])
  assert.deepEqual(workspace.resolutions, [])
  assert.deepEqual(workspace.rejections, [])
  assert.equal(workspace.reconciliationDetail, null)
  assert.equal(workspace.resolutionDataStatus, 'workspace_endpoint_missing')
  assert.deepEqual(calls, [
    ['getManagementDetail', '512070'],
    ['getSymbolWorkspace', '512070'],
  ])
})

test('reconciliation workbench actions surface tracked-symbol 404s separately from endpoint-missing 404s', async () => {
  const actions = createReconciliationWorkbenchActions({
    positionApi: {
      async getReconciliation() {
        return { summary: {}, rows: [] }
      },
    },
    orderApi: {
      async listOrders() {
        return { rows: [], total: 0, page: 1, size: 20 }
      },
      async getOrderDetail() {
        return null
      },
      async getStats() {
        return { total: 0, missing_broker_order_count: 0 }
      },
    },
    tpslApi: {
      async getManagementDetail(symbol) {
        return {
          symbol,
          entries: [{ entry_id: 'entry_300760_1' }],
          entry_slices: [],
          reconciliation: { state: 'aligned' },
          history: [],
        }
      },
    },
    reconciliationApi: {
      async getSymbolWorkspace() {
        const error = new Error('symbol is not tracked')
        error.response = {
          status: 404,
          data: {
            error: 'symbol is not tracked',
          },
        }
        throw error
      },
    },
  })

  const workspace = await actions.loadSymbolWorkspace('300760')

  assert.equal(workspace.symbol, '300760')
  assert.equal(workspace.entries[0].entry_id, 'entry_300760_1')
  assert.equal(workspace.resolutionDataStatus, 'workspace_symbol_not_tracked')
  assert.equal(workspace.resolutionErrorMessage, 'symbol is not tracked')
})

test('reconciliation workbench controller loads overview and hydrates the first symbol workspace', async () => {
  const calls = []
  const controller = createReconciliationWorkbenchPageController({
    actions: {
      async loadOverview() {
        calls.push(['loadOverview'])
        return {
          summary: {
            row_count: 2,
            audit_status_counts: { ERROR: 1, WARN: 0, OK: 1 },
          },
          stateCards: [],
          ruleCards: [],
          rows: [
            { symbol: '600000', name: '浦发银行', audit_status: 'ERROR' },
            { symbol: '000001', name: '平安银行', audit_status: 'OK' },
          ],
        }
      },
      async loadOrders(filters) {
        calls.push(['loadOrders', filters.symbol || '', filters.page, filters.size])
        return {
          rows: [
            {
              internal_order_id: 'ord_1',
              orderLookupId: 'ord_1',
              symbol: filters.symbol,
              side: 'buy',
              state: 'FILLED',
            },
          ],
          total: 1,
          page: filters.page,
          size: filters.size,
        }
      },
      async loadOrderStats(filters) {
        calls.push(['loadOrderStats', filters.symbol || ''])
        return {
          total: 1,
          missing_broker_order_count: 0,
        }
      },
      async loadOrderDetail(orderId) {
        calls.push(['loadOrderDetail', orderId])
        return {
          order: {
            internal_order_id: orderId,
            symbol: '600000',
          },
          identifierRows: [],
          timelineRows: [],
          tradeRows: [],
        }
      },
      async loadSymbolWorkspace(symbol) {
        calls.push(['loadSymbolWorkspace', symbol])
        return {
          symbol,
          entries: [{ entry_id: 'entry_1' }],
          entrySlices: [{ entry_slice_id: 'slice_1', entry_id: 'entry_1' }],
          reconciliation: { state: 'ALIGNED' },
          historyRows: [],
          gaps: [],
          resolutions: [],
          rejections: [],
        }
      },
    },
  })

  await controller.refreshOverview()

  assert.equal(controller.state.selectedSymbol, '600000')
  assert.equal(controller.state.orderFilters.symbol, '600000')
  assert.equal(controller.state.orderRows[0].internal_order_id, 'ord_1')
  assert.equal(controller.state.selectedOrderId, 'ord_1')
  assert.equal(controller.state.workspaceDetail.symbol, '600000')
  assert.equal(controller.state.selectedEntryId, 'entry_1')
  assert.deepEqual(calls, [
    ['loadOverview'],
    ['loadOrders', '600000', 1, 20],
    ['loadOrderStats', '600000'],
    ['loadSymbolWorkspace', '600000'],
    ['loadOrderDetail', 'ord_1'],
  ])
})

test('reconciliation workbench lookup resolves broker order ids and switches to orders tab', async () => {
  const calls = []
  const controller = createReconciliationWorkbenchPageController({
    actions: {
      async loadOverview() {
        return {
          summary: {
            row_count: 1,
            audit_status_counts: { ERROR: 1, WARN: 0, OK: 0 },
          },
          stateCards: [],
          ruleCards: [],
          rows: [{ symbol: '600104', name: '上汽集团', audit_status: 'ERROR' }],
        }
      },
      async loadOrders(filters) {
        calls.push([
          'loadOrders',
          filters.symbol || '',
          filters.internal_order_id || '',
          filters.request_id || '',
          filters.broker_order_id || '',
        ])
        if (filters.internal_order_id || filters.request_id) {
          return { rows: [], total: 0, page: 1, size: 20 }
        }
        if (filters.broker_order_id === '403701761' && !filters.symbol) {
          return {
            rows: [
              {
                internal_order_id: '',
                broker_order_id: '403701761',
                orderLookupId: '403701761',
                symbol: '600104',
                side: 'sell',
                state: 'FILLED',
              },
            ],
            total: 1,
            page: 1,
            size: 20,
          }
        }
        return {
          rows: [
            {
              internal_order_id: '',
              broker_order_id: '403701761',
              orderLookupId: '403701761',
              symbol: filters.symbol || '600104',
              side: 'sell',
              state: 'FILLED',
            },
          ],
          total: 1,
          page: filters.page || 1,
          size: filters.size || 20,
        }
      },
      async loadOrderStats(filters) {
        calls.push(['loadOrderStats', filters.symbol || ''])
        return {
          total: 1,
          missing_broker_order_count: 0,
        }
      },
      async loadOrderDetail(orderId) {
        calls.push(['loadOrderDetail', orderId])
        return {
          order: {
            broker_order_id: orderId,
            symbol: '600104',
          },
          identifierRows: [],
          timelineRows: [],
          tradeRows: [],
        }
      },
      async loadSymbolWorkspace(symbol) {
        calls.push(['loadSymbolWorkspace', symbol])
        return {
          symbol,
          entries: [],
          entrySlices: [],
          reconciliation: { state: 'DRIFT' },
          historyRows: [],
          gaps: [],
          resolutions: [],
          rejections: [],
        }
      },
    },
  })

  controller.state.lookupDraft = '403701761'
  await controller.applyLookup()

  assert.equal(controller.state.activeTab, 'orders')
  assert.equal(controller.state.selectedSymbol, '600104')
  assert.equal(controller.state.selectedOrderId, '403701761')
  assert.equal(controller.state.workspaceDetail.symbol, '600104')
  assert.deepEqual(calls, [
    ['loadOrders', '', '403701761', '', ''],
    ['loadOrders', '', '', '403701761', ''],
    ['loadOrders', '', '', '', '403701761'],
    ['loadOrders', '600104', '', '', ''],
    ['loadOrderStats', '600104'],
    ['loadSymbolWorkspace', '600104'],
    ['loadOrderDetail', '403701761'],
  ])
})

test('reconciliation workbench filters overview rows by query and audit status', async () => {
  const controller = createReconciliationWorkbenchPageController({
    actions: {
      async loadOverview() {
        return {
          summary: {
            row_count: 2,
            audit_status_counts: { ERROR: 1, WARN: 1, OK: 0 },
          },
          stateCards: [],
          ruleCards: [],
          rows: [
            { symbol: '600000', name: '浦发银行', audit_status: 'ERROR', reconciliation_state: 'DRIFT' },
            { symbol: '000001', name: '平安银行', audit_status: 'WARN', reconciliation_state: 'OBSERVING' },
          ],
        }
      },
      async loadOrders() {
        return { rows: [], total: 0, page: 1, size: 20 }
      },
      async loadOrderStats() {
        return { total: 0, missing_broker_order_count: 0 }
      },
      async loadOrderDetail() {
        return null
      },
      async loadSymbolWorkspace(symbol) {
        return {
          symbol,
          entries: [],
          entrySlices: [],
          reconciliation: { state: 'DRIFT' },
          historyRows: [],
          gaps: [],
          resolutions: [],
          rejections: [],
        }
      },
    },
  })

  await controller.refreshOverview()
  controller.state.overviewFilters.query = '浦发'
  controller.state.overviewFilters.auditStatus = 'ERROR'

  assert.equal(controller.filteredOverviewRows.value.length, 1)
  assert.equal(controller.filteredOverviewRows.value[0].symbol, '600000')
})

test('reconciliation workbench controller keeps child-load errors after overview refresh', async () => {
  const controller = createReconciliationWorkbenchPageController({
    actions: {
      async loadOverview() {
        return {
          summary: {
            row_count: 1,
            audit_status_counts: { ERROR: 1, WARN: 0, OK: 0 },
          },
          stateCards: [],
          ruleCards: [],
          rows: [{ symbol: '300760', name: '迈瑞医疗', audit_status: 'ERROR' }],
        }
      },
      async loadOrders() {
        throw new Error('orders api unavailable')
      },
      async loadOrderStats() {
        return { total: 0, missing_broker_order_count: 0 }
      },
      async loadOrderDetail() {
        return null
      },
      async loadSymbolWorkspace(symbol) {
        return {
          symbol,
          entries: [],
          entrySlices: [],
          reconciliation: { state: 'DRIFT' },
          historyRows: [],
          gaps: [],
          resolutions: [],
          rejections: [],
        }
      },
    },
  })

  await controller.refreshOverview()

  assert.equal(controller.state.selectedSymbol, '300760')
  assert.equal(controller.state.pageError, 'orders api unavailable')
})

test('reconciliation workbench actions derive compact ledger ids and value labels for entry and slice rows', async () => {
  const actions = createReconciliationWorkbenchActions({
    positionApi: {
      async getReconciliation() {
        return { summary: {}, rows: [] }
      },
    },
    orderApi: {
      async listOrders() {
        return { rows: [], total: 0, page: 1, size: 20 }
      },
      async getOrderDetail() {
        return null
      },
      async getStats() {
        return { total: 0, missing_broker_order_count: 0 }
      },
    },
    tpslApi: {
      async getManagementDetail(symbol) {
        return {
          symbol,
          entries: [
            {
              entry_id: 'entry_abcdef123456',
              entry_price: 123.45,
              original_quantity: 1000,
              remaining_quantity: 250,
              date: 20260405,
              time: '10:30:00',
            },
          ],
          entry_slices: [
            {
              entry_slice_id: 'entryslice_998877665544',
              entry_id: 'entry_abcdef123456',
              slice_seq: 3,
              guardian_price: 128.5,
              remaining_quantity: 100,
              remaining_amount: 12850,
            },
          ],
          reconciliation: { state: 'aligned' },
          history: [],
        }
      },
    },
    reconciliationApi: {
      async getSymbolWorkspace() {
        return {
          detail: { reconciliation: { state: 'ALIGNED' } },
          gaps: [],
          resolutions: [],
          rejections: [],
        }
      },
    },
  })

  const workspace = await actions.loadSymbolWorkspace('300760')

  assert.equal(workspace.entries[0].entry_short_id, '123456')
  assert.equal(workspace.entries[0].entry_market_value, 30862.5)
  assert.equal(workspace.entries[0].entry_market_value_label, '3.09万')
  assert.equal(workspace.entries[0].remaining_ratio_label, '25.0%')
  assert.equal(workspace.entrySlices[0].entry_slice_short_id, '665544')
  assert.equal(workspace.entrySlices[0].entry_short_id, '123456')
  assert.equal(workspace.entrySlices[0].remaining_amount_label, '1.28万')
})
