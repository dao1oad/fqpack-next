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
  assert.ok(source.includes('syncShouban30MustPoolToTdx'))
  assert.ok(source.includes('clearShouban30MustPool'))
  assert.ok(source.includes('handleSyncMustPoolToTdx'))
  assert.ok(source.includes('handleClearMustPool'))
  assert.ok(source.includes("workspace:must:sync-tdx"))
  assert.ok(source.includes("workspace:must:clear"))
  assert.ok(source.includes('runtime-ledger daily-results-ledger'))
  assert.ok(source.includes('handleWorkspaceRowClick'))
  assert.ok(source.includes('daily-detail-card-grid'))
  assert.ok(source.includes('daily-detail-history-panel'))
  assert.ok(source.includes('buildDailyScreeningFilterDefaults'))
  assert.match(source, /const applyDefaultFilterState = \(\) => \{/)
  assert.match(source, /const resetFilters = async \(\) => \{[\s\S]*applyDefaultFilterState\(\)/)
  assert.match(source, /watch\(selectedScopeId, async \(scopeId\) => \{[\s\S]*applyDefaultFilterState\(\)/)
  assert.ok(!source.includes('执行全链路'))
})

test('DailyScreening moves scope into the top guide area and paginates intersection rows', () => {
  const source = fs.readFileSync(componentPath, 'utf8')

  assert.ok(source.includes('class="daily-toolbar-scope"'))
  assert.ok(source.includes('const resultPage = ref(1)'))
  assert.ok(source.includes('paginatedResultRows'))
  assert.ok(source.includes('class="daily-results-pagination"'))
  assert.ok(source.includes('<el-pagination'))
  assert.ok(!source.includes('筛选工作台'))
  assert.ok(!source.includes('前端只做组合查询，不再触发运行，不再展示 SSE。'))
  assert.doesNotMatch(
    source,
    /<section class="workbench-panel daily-filter-panel"[\s\S]*<div class="workbench-panel__title">Scope<\/div>/,
  )
})

test('DailyScreening ledgers keep headers outside the viewport and avoid horizontal scrollbars', () => {
  const source = fs.readFileSync(componentPath, 'utf8')

  assert.match(source, /<div class="runtime-ledger__viewport">[\s\S]*paginatedResultRows/)
  assert.match(source, /<div class="runtime-ledger__viewport">[\s\S]*v-for="row in tab\.rows"/)
  assert.match(source, /<div class="runtime-ledger__viewport">[\s\S]*v-for="\(row,\s*index\) in detail\.hot_reasons"/)
  assert.match(source, /\.runtime-ledger__viewport \{[\s\S]*overflow-y:\s*auto;/)
  assert.match(source, /\.runtime-ledger__header \{[\s\S]*flex:\s*0 0 auto;/)
  assert.match(source, /@media \(min-width:\s*961px\) \{[\s\S]*\.daily-results-ledger,\s*\.daily-history-ledger \{[\s\S]*overflow-x:\s*hidden;[\s\S]*overflow-y:\s*hidden;/)
  assert.match(source, /@media \(min-width:\s*961px\) \{[\s\S]*\.daily-results-ledger \.runtime-ledger__viewport,\s*\.daily-history-ledger \.runtime-ledger__viewport \{[\s\S]*min-width:\s*0;[\s\S]*width:\s*100%;[\s\S]*overflow-y:\s*auto;[\s\S]*overflow-x:\s*hidden;/)
  assert.match(source, /@media \(max-width:\s*960px\) \{[\s\S]*\.daily-results-ledger,\s*\.daily-history-ledger \{[\s\S]*overflow-x:\s*auto;[\s\S]*overflow-y:\s*hidden;/)
  assert.match(source, /@media \(max-width:\s*960px\) \{[\s\S]*\.daily-results-ledger \.runtime-ledger__viewport,\s*\.daily-history-ledger \.runtime-ledger__viewport \{[\s\S]*min-width:\s*100%;[\s\S]*width:\s*max-content;[\s\S]*overflow-y:\s*auto;[\s\S]*overflow-x:\s*visible;/)
  assert.doesNotMatch(source, /\.runtime-ledger__header \{[\s\S]*position:\s*sticky;/)
})

test('DailyScreening routes guide summary and detail chips through shared StatusChip', () => {
  const source = fs.readFileSync(componentPath, 'utf8')

  assert.match(source, /import StatusChip from '\.\.\/components\/workbench\/StatusChip\.vue'/)
  assert.match(source, /<StatusChip[\s\S]*v-for="line in workbenchGuideLines"[\s\S]*variant="muted"/)
  assert.match(source, /<StatusChip variant="muted">\s*当前 scope <strong>\{\{\s*selectedScopeLabel\s*\}\}<\/strong>/)
  assert.match(source, /<StatusChip variant="success">\s*基础池 <strong>\{\{\s*scopeSummary\?\.stock_count \?\? 0\s*\}\}<\/strong>/)
  assert.match(source, /<StatusChip variant="warning">\s*当前结果 <strong>\{\{\s*resultRows\.length\s*\}\}<\/strong>/)
  assert.match(source, /<StatusChip[\s\S]*v-for="item in detail\.clsMemberships"[\s\S]*variant="muted"/)
  assert.match(source, /<StatusChip[\s\S]*v-for="item in detail\.hotMemberships"[\s\S]*variant="warning"/)
  assert.match(source, /<StatusChip[\s\S]*v-for="item in detail\.marketFlagMemberships"[\s\S]*variant="success"/)
  assert.match(source, /<StatusChip[\s\S]*:variant="detailBasePoolStatus\.inBasePool \? 'success' : 'warning'"/)
})

test('DailyScreening.vue imports split filter, workspace, and detail modules', async () => {
  const content = await fs.promises.readFile(componentPath, 'utf8')

  assert.match(content, /from '\.\/dailyScreeningFilters\.mjs'/)
  assert.match(content, /from '\.\/dailyScreeningWorkspace\.mjs'/)
  assert.match(content, /from '\.\/dailyScreeningDetail\.mjs'/)
})
