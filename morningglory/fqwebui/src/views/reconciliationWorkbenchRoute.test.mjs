import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const readSource = (relativePath) => (
  readFileSync(new URL(relativePath, import.meta.url), 'utf8').replace(/\r/g, '')
)

const routerSource = readSource('../router/index.js')
const pageMetaSource = readSource('../router/pageMeta.mjs')
const workbenchSource = readSource('./ReconciliationWorkbench.vue')

test('router exposes /reconciliation and removes /order-management', () => {
  assert.match(routerSource, /path:\s*'\/reconciliation'/)
  assert.match(routerSource, /name:\s*'reconciliation'/)
  assert.doesNotMatch(routerSource, /path:\s*'\/order-management'/)
  assert.doesNotMatch(routerSource, /name:\s*'order-management'/)
  assert.doesNotMatch(routerSource, /path:\s*'\/tpsl'/)
  assert.doesNotMatch(routerSource, /path:\s*'\/futures-control'/)
  assert.doesNotMatch(routerSource, /path:\s*'\/stock-cjsd'/)
})

test('header nav exposes 对账中心 and removes retired pages', () => {
  assert.match(pageMetaSource, /label:\s*'对账中心'/)
  assert.match(pageMetaSource, /path:\s*'\/reconciliation'/)
  assert.doesNotMatch(pageMetaSource, /label:\s*'订单管理'/)
  assert.doesNotMatch(pageMetaSource, /path:\s*'\/order-management'/)
  assert.doesNotMatch(pageMetaSource, /label:\s*'TPSL'/)
  assert.doesNotMatch(pageMetaSource, /path:\s*'\/tpsl'/)
  assert.doesNotMatch(pageMetaSource, /label:\s*'期货'/)
  assert.doesNotMatch(pageMetaSource, /path:\s*'\/futures-control'/)
  assert.doesNotMatch(pageMetaSource, /label:\s*'超级赛道'/)
  assert.doesNotMatch(pageMetaSource, /path:\s*'\/stock-cjsd'/)
})

test('route title mapping includes reconciliation and no longer includes order management', () => {
  assert.match(pageMetaSource, /'reconciliation':\s*'对账中心'/)
  assert.doesNotMatch(pageMetaSource, /'order-management':\s*'订单管理'/)
})

test('reconciliation workbench uses the shared workbench shell and exposes the five troubleshooting tabs', () => {
  assert.match(workbenchSource, /<WorkbenchPage class="reconciliation-page">/)
  assert.match(workbenchSource, /<WorkbenchToolbar class="reconciliation-toolbar">/)
  assert.match(workbenchSource, /name="overview"/)
  assert.match(workbenchSource, /name="orders"/)
  assert.match(workbenchSource, /name="ledger"/)
  assert.match(workbenchSource, /name="resolution"/)
  assert.doesNotMatch(workbenchSource, /name="entries"/)
  assert.doesNotMatch(workbenchSource, /name="slices"/)
})

test('reconciliation workbench wires controller state and existing APIs into real workbench tables', () => {
  assert.match(workbenchSource, /import \{ createReconciliationWorkbenchActions \} from '\.\/reconciliationWorkbench\.mjs'/)
  assert.match(workbenchSource, /import \{ createReconciliationWorkbenchPageController \} from '\.\/reconciliationWorkbenchPage\.mjs'/)
  assert.match(workbenchSource, /import \{ positionManagementApi \} from '@\/api\/positionManagementApi'/)
  assert.match(workbenchSource, /import \{ orderManagementApi \} from '@\/api\/orderManagementApi'/)
  assert.match(workbenchSource, /import \{ tpslApi \} from '@\/api\/tpslApi'/)
  assert.match(workbenchSource, /createReconciliationWorkbenchActions\(\{ positionApi: positionManagementApi, orderApi: orderManagementApi, tpslApi, reconciliationApi: positionManagementApi \}\)/)
  assert.match(workbenchSource, /<el-table[\s\S]*:data="filteredOverviewRows"/)
  assert.match(workbenchSource, /<el-table[\s\S]*:data="orderRows"/)
  assert.match(workbenchSource, /<el-table[\s\S]*:data="workspaceEntries"/)
  assert.match(workbenchSource, /<el-table[\s\S]*:data="selectedEntrySlices"/)
  assert.match(workbenchSource, /<el-table[\s\S]*:data="resolutionRows"/)
  assert.match(workbenchSource, /entry_short_id/)
  assert.match(workbenchSource, /entry_market_value_label/)
  assert.match(workbenchSource, /remaining_ratio_label/)
  assert.match(workbenchSource, /entry_slice_short_id/)
  assert.match(workbenchSource, /remaining_amount_label/)
})
