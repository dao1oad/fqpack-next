import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

const componentPath = path.resolve(import.meta.dirname, 'DailyScreening.vue')

test('DailyScreening renders dense workbench layout for grouped filters and workspace detail reuse', () => {
  const source = fs.readFileSync(componentPath, 'utf8')

  assert.ok(source.includes('conditionSectionGroups'))
  assert.ok(source.includes("group.key === 'base_pool'"))
  assert.ok(source.includes('加入 pre_pools'))
  assert.ok(source.includes('must_pools'))
  assert.ok(source.includes('集合'))
  assert.ok(source.includes('分类 / 上下文'))
  assert.ok(source.includes('历史热门理由'))
  assert.ok(source.includes('输入代码或名称，全市场模糊搜索'))
  assert.ok(source.includes('searchMarketStocks'))
  assert.ok(source.includes('Shouban30ReasonPopover'))
  assert.ok(source.includes('基础池状态'))
  assert.ok(source.includes('最近一次在基础池'))
  assert.ok(source.includes('getStockMustPoolsList'))
  assert.ok(source.includes('deleteFromStockMustPoolsByCode'))
  assert.ok(source.includes('handleDeleteMustPoolRow'))
  assert.ok(source.includes('runtime-ledger daily-results-ledger'))
  assert.ok(source.includes('handleWorkspaceRowClick'))
  assert.ok(source.includes('daily-detail-card-grid'))
  assert.ok(source.includes('daily-detail-history-panel'))
  assert.ok(source.includes('buildDailyScreeningDefaultFilterState'))
  assert.match(source, /const applyDefaultFilterState = \(\) => \{/)
  assert.match(source, /const resetFilters = async \(\) => \{[\s\S]*applyDefaultFilterState\(\)/)
  assert.match(source, /watch\(selectedScopeId, async \(scopeId\) => \{[\s\S]*applyDefaultFilterState\(\)/)
  assert.ok(!source.includes('执行全链路'))
})
