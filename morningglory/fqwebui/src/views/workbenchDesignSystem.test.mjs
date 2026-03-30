import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'

const readSource = (relativePath) => (
  readFileSync(new URL(relativePath, import.meta.url), 'utf8').replace(/\r/g, '')
)

const mainSource = readSource('../main.js')
const appShellSource = readSource('../../index.html')
const headerSource = readSource('./MyHeader.vue')
const headerStyleSource = readSource('../style/my-header.styl')
const runtimeSource = readSource('./RuntimeObservability.vue')
const positionSource = readSource('./PositionManagement.vue')
const orderSource = readSource('./OrderManagement.vue')
const tpslSource = readSource('./TpslManagement.vue')
const subjectSource = readSource('./SubjectManagement.vue')
const dailySource = readSource('./DailyScreening.vue')
const klineHeaderSource = readSource('./KlineHeader.vue')
const klineSlimSource = readSource('./KlineSlim.vue')
const stockControlSource = readSource('./StockControl.vue')
const ganttSource = readSource('./GanttUnified.vue')
const ganttStocksSource = readSource('./GanttUnifiedStocks.vue')
const systemSettingsSource = readSource('./SystemSettings.vue')
const shoubanSource = readSource('./GanttShouban30Phase1.vue')
const klineBigSource = readSource('./KlineBig.vue')
const multiPeriodSource = readSource('./MultiPeriod.vue')

const tokenFileUrl = new URL('../style/workbench-tokens.css', import.meta.url)
const componentFiles = [
  ['WorkbenchPage', '../components/workbench/WorkbenchPage.vue', /class="workbench-page"/],
  ['WorkbenchToolbar', '../components/workbench/WorkbenchToolbar.vue', /class="workbench-toolbar"/],
  ['WorkbenchSummaryRow', '../components/workbench/WorkbenchSummaryRow.vue', /class="workbench-summary-row"/],
  ['WorkbenchPanel', '../components/workbench/WorkbenchPanel.vue', /class="workbench-panel"/],
  ['WorkbenchSidebarPanel', '../components/workbench/WorkbenchSidebarPanel.vue', /workbench-panel--sidebar/],
  ['WorkbenchLedgerPanel', '../components/workbench/WorkbenchLedgerPanel.vue', /workbench-panel--ledger/],
  ['WorkbenchDetailPanel', '../components/workbench/WorkbenchDetailPanel.vue', /workbench-panel--detail/],
  ['StatusChip', '../components/workbench/StatusChip.vue', /workbench-summary-chip/],
]

test('main.js imports workbench tokens before the shared workbench density stylesheet', () => {
  const tokenImportIndex = mainSource.indexOf("import './style/workbench-tokens.css'")
  const densityImportIndex = mainSource.indexOf("import './style/workbench-density.css'")

  assert.notEqual(tokenImportIndex, -1, 'missing token layer import')
  assert.notEqual(densityImportIndex, -1, 'missing shared workbench density import')
  assert.ok(tokenImportIndex < densityImportIndex, 'token layer must load before density rules')
})

test('index.html keeps the production app shell free of temporary figma capture scripts', () => {
  assert.doesNotMatch(appShellSource, /mcp\.figma\.com\/mcp\/html-to-design\/capture\.js/)
})

test('workbench token layer defines the core page panel status spacing radius and desktop breakpoint variables', () => {
  assert.ok(existsSync(tokenFileUrl), 'missing workbench-tokens.css')

  const tokensSource = readFileSync(tokenFileUrl, 'utf8').replace(/\r/g, '')
  assert.match(tokensSource, /--fq-bg-page:\s*#f5f7fa;/)
  assert.match(tokensSource, /--fq-panel-bg:\s*#ffffff;/)
  assert.match(tokensSource, /--fq-status-primary:\s*#409eff;/)
  assert.match(tokensSource, /--fq-space-3:\s*12px;/)
  assert.match(tokensSource, /--fq-radius-md:\s*8px;/)
  assert.match(tokensSource, /--fq-breakpoint-desktop:\s*1440px;/)
  assert.match(tokensSource, /--fq-breakpoint-wide:\s*1920px;/)
})

test('workbench primitive components exist and expose slot-based root containers', () => {
  for (const [name, relativePath, classPattern] of componentFiles) {
    const fileUrl = new URL(relativePath, import.meta.url)
    assert.ok(existsSync(fileUrl), `missing ${name}`)
    const source = readFileSync(fileUrl, 'utf8').replace(/\r/g, '')
    assert.match(source, classPattern, `${name} is missing its root workbench class`)
    assert.match(source, /<slot/, `${name} should remain slot-driven`)
  }
})

test('RuntimeObservability.vue consumes workbench primitives for the page shell instead of only raw div markup', () => {
  assert.match(runtimeSource, /import WorkbenchPage from '\.\.\/components\/workbench\/WorkbenchPage\.vue'/)
  assert.match(runtimeSource, /import WorkbenchToolbar from '\.\.\/components\/workbench\/WorkbenchToolbar\.vue'/)
  assert.match(runtimeSource, /import WorkbenchSummaryRow from '\.\.\/components\/workbench\/WorkbenchSummaryRow\.vue'/)
  assert.match(runtimeSource, /import WorkbenchSidebarPanel from '\.\.\/components\/workbench\/WorkbenchSidebarPanel\.vue'/)
  assert.match(runtimeSource, /import WorkbenchLedgerPanel from '\.\.\/components\/workbench\/WorkbenchLedgerPanel\.vue'/)
  assert.match(runtimeSource, /import WorkbenchDetailPanel from '\.\.\/components\/workbench\/WorkbenchDetailPanel\.vue'/)
  assert.match(runtimeSource, /<WorkbenchPage class="runtime-page">/)
  assert.match(runtimeSource, /<WorkbenchToolbar class="runtime-section runtime-section--workbench">/)
  assert.match(runtimeSource, /<WorkbenchSummaryRow class="runtime-summary-row">/)
  assert.match(runtimeSource, /<WorkbenchSidebarPanel class="runtime-browser-panel runtime-browser-panel--components">/)
  assert.match(runtimeSource, /<WorkbenchLedgerPanel class="runtime-browser-panel runtime-browser-panel--feed">/)
  assert.match(runtimeSource, /<WorkbenchDetailPanel class="runtime-browser-panel runtime-browser-panel--detail">/)
})

test('RuntimeObservability.vue uses StatusChip for read-only workbench summary badges instead of raw span pills', () => {
  assert.match(runtimeSource, /import StatusChip from '\.\.\/components\/workbench\/StatusChip\.vue'/)
  assert.match(runtimeSource, /<StatusChip>\s*可见 Trace <strong>\{\{\s*traceListSummary\.trace_count\s*\}\}<\/strong>/)
  assert.match(runtimeSource, /<StatusChip v-if="timeRangeDisplayLabel" variant="muted">/)
  assert.match(runtimeSource, /<StatusChip\s+v-if="filterChips\.length === 0"[\s\S]*variant="muted"[\s\S]*当前无筛选/)
  assert.match(runtimeSource, /<StatusChip variant="muted" :title="item\.runtime_summary_title">/)
  assert.match(runtimeSource, /<StatusChip variant="muted">\s*Trace \{\{\s*item\.trace_count\s*\}\}/)
})

test('RuntimeObservability.vue routes runtime status badges through StatusChip variants instead of page-local pill colors', () => {
  assert.match(runtimeSource, /const statusChipVariant = \(status\) => \{/)
  assert.match(runtimeSource, /<StatusChip class="runtime-inline-status" :variant="statusChipVariant\(item\.status\)">/)
  assert.match(runtimeSource, /<StatusChip class="runtime-inline-status" :variant="statusChipVariant\(row\.trace_status\)">/)
  assert.match(runtimeSource, /<StatusChip class="runtime-inline-status" :variant="statusChipVariant\(row\.status\)">/)
  assert.doesNotMatch(runtimeSource, /<span class="runtime-inline-status" :class="statusClass\(item\.status\)">/)
  assert.doesNotMatch(runtimeSource, /<span class="runtime-inline-status" :class="statusClass\(row\.trace_status\)">/)
  assert.doesNotMatch(runtimeSource, /<span class="runtime-inline-status" :class="statusClass\(row\.status\)">/)
})

test('RuntimeObservability.vue stays the canonical workbench template with header, toolbar, summary, panel stack, and page-state hooks', () => {
  assert.match(runtimeSource, /<WorkbenchPage class="runtime-page">/)
  assert.match(runtimeSource, /<MyHeader\s*\/>/)
  assert.match(runtimeSource, /<WorkbenchToolbar class="runtime-section runtime-section--workbench">/)
  assert.match(runtimeSource, /<div class="workbench-page-title">运行观测<\/div>/)
  assert.match(runtimeSource, /<div class="workbench-page-meta">/)
  assert.match(runtimeSource, /<el-button type="primary" :loading="loading\.overview" @click="loadOverview">刷新<\/el-button>/)
  assert.match(runtimeSource, /<el-alert[\s\S]*v-if="pageError"[\s\S]*class="workbench-alert"[\s\S]*type="error"/)
  assert.match(runtimeSource, /<WorkbenchSummaryRow class="runtime-summary-row">/)
  assert.match(runtimeSource, /<WorkbenchSidebarPanel class="runtime-browser-panel runtime-browser-panel--components">/)
  assert.match(runtimeSource, /<WorkbenchLedgerPanel class="runtime-browser-panel runtime-browser-panel--feed">/)
  assert.match(runtimeSource, /<WorkbenchDetailPanel class="runtime-browser-panel runtime-browser-panel--detail">/)
  assert.match(runtimeSource, /<div v-else-if="!traceLedgerRows\.length" class="runtime-empty-panel">[\s\S]*暂无最近 Trace/)
  assert.match(runtimeSource, /<div v-else-if="!eventLedgerRows\.length" class="runtime-empty-panel">[\s\S]*componentEventEmptyState\.title/)
  assert.match(runtimeSource, /<el-button plain :loading="loading\.traces" @click="loadMoreTraces">加载更多 Trace<\/el-button>/)
  assert.match(runtimeSource, /<el-button plain :loading="loading\.events" @click="loadMoreEvents">加载更多 Event<\/el-button>/)
})

test('PositionManagement.vue reuses StatusChip for summary chips and inline ledger states', () => {
  assert.match(positionSource, /import StatusChip from '\.\.\/components\/workbench\/StatusChip\.vue'/)
  assert.match(positionSource, /<StatusChip :variant="stateToneChipVariant">/)
  assert.match(positionSource, /<StatusChip :variant="staleChipVariant">/)
  assert.match(positionSource, /<StatusChip variant="muted">\s*raw state <strong>\{\{\s*statePanel\.hero\.raw_state_label\s*\}\}<\/strong>/)
  assert.match(positionSource, /<StatusChip variant="muted">\s*配置时间 <strong>\{\{\s*configUpdatedAt\s*\}\}<\/strong>/)
  assert.match(positionSource, /<StatusChip variant="warning">\s*仓位不一致 <strong>\{\{\s*mismatchSymbolCount\s*\}\}<\/strong>/)
  assert.match(positionSource, /<StatusChip class="runtime-inline-status" :variant="ruleStatusChipVariant\(row\.allowed\)">/)
  assert.match(positionSource, /<StatusChip class="runtime-inline-status" :variant="positionConsistencyChipVariant\(row\.quantity_mismatch\)">/)
  assert.match(positionSource, /<StatusChip class="runtime-inline-status" :variant="symbolLimitStatusChipVariant\(row\.blocked\)">/)
  assert.match(positionSource, /<StatusChip class="runtime-inline-status" :variant="decisionStatusChipVariant\(row\.tone\)">/)
  assert.doesNotMatch(positionSource, /<span class="runtime-inline-status" :class="resolveRuleStatusClass\(row\.allowed\)">/)
  assert.doesNotMatch(positionSource, /<span class="runtime-inline-status" :class="resolvePositionConsistencyStatusClass\(row\.quantity_mismatch\)">/)
  assert.doesNotMatch(positionSource, /<span class="runtime-inline-status" :class="resolveSymbolLimitStatusClass\(row\.blocked\)">/)
  assert.doesNotMatch(positionSource, /<span class="runtime-inline-status" :class="resolveDecisionStatusClass\(row\.tone\)">/)
})

test('PositionManagement.vue consumes shared workbench page and panel primitives for state limits and decisions', () => {
  assert.match(positionSource, /import WorkbenchPage from ['"][^'"]*WorkbenchPage\.vue['"]/)
  assert.match(positionSource, /import WorkbenchToolbar from ['"][^'"]*WorkbenchToolbar\.vue['"]/)
  assert.match(positionSource, /import WorkbenchSummaryRow from ['"][^'"]*WorkbenchSummaryRow\.vue['"]/)
  assert.match(positionSource, /import WorkbenchDetailPanel from ['"][^'"]*WorkbenchDetailPanel\.vue['"]/)
  assert.match(positionSource, /import WorkbenchLedgerPanel from ['"][^'"]*WorkbenchLedgerPanel\.vue['"]/)
  assert.match(positionSource, /<WorkbenchPage class="position-page">/)
  assert.match(positionSource, /<MyHeader\s*\/>/)
  assert.match(positionSource, /<WorkbenchToolbar class="position-toolbar">/)
  assert.match(positionSource, /<div class="workbench-page-title">仓位管理<\/div>/)
  assert.match(positionSource, /<div class="workbench-page-meta">[\s\S]*统一查看 PM 状态、单标的上限和最近决策。/)
  assert.match(positionSource, /<WorkbenchSummaryRow class="position-summary-row">/)
  assert.match(positionSource, /<el-alert[\s\S]*v-if="pageError"[\s\S]*class="workbench-alert"[\s\S]*type="error"/)
  assert.match(positionSource, /<WorkbenchDetailPanel class="position-top-panel position-state-panel">/)
  assert.match(positionSource, /<WorkbenchLedgerPanel class="position-top-panel position-symbol-limit-panel">/)
  assert.match(positionSource, /<WorkbenchLedgerPanel class="position-decision-panel">/)
})

test('OrderManagement.vue reuses StatusChip for summary and identifier chips', () => {
  assert.match(orderSource, /import StatusChip from '\.\.\/components\/workbench\/StatusChip\.vue'/)
  assert.match(orderSource, /<StatusChip[\s\S]*v-if="activeFilterChips\.length === 0"[\s\S]*variant="muted"[\s\S]*当前无额外筛选/)
  assert.match(orderSource, /<StatusChip>\s*总订单 <strong>\{\{\s*stats\.total\s*\}\}<\/strong>/)
  assert.match(orderSource, /<StatusChip variant="warning">\s*缺 broker 单号 <strong>\{\{\s*stats\.missing_broker_order_count\s*\}\}<\/strong>/)
  assert.match(orderSource, /<StatusChip variant="success">\s*已成交 \/ 部分成交 <strong>\{\{\s*stats\.filled_count\s*\}\} \/ \{\{\s*stats\.partial_filled_count\s*\}\}<\/strong>/)
  assert.match(orderSource, /<StatusChip variant="muted">\s*\{\{\s*detail\.order\.side \|\| '-'\s*\}\}\s*<\/StatusChip>/)
  assert.match(orderSource, /<StatusChip[\s\S]*v-for="item in detail\.identifierRows"/)
})

test('OrderManagement.vue consumes shared workbench page toolbar and panel primitives for stats list and detail', () => {
  assert.match(orderSource, /import WorkbenchPage from ['"][^'"]*WorkbenchPage\.vue['"]/)
  assert.match(orderSource, /import WorkbenchToolbar from ['"][^'"]*WorkbenchToolbar\.vue['"]/)
  assert.match(orderSource, /import WorkbenchSummaryRow from ['"][^'"]*WorkbenchSummaryRow\.vue['"]/)
  assert.match(orderSource, /import WorkbenchPanel from ['"][^'"]*WorkbenchPanel\.vue['"]/)
  assert.match(orderSource, /import WorkbenchLedgerPanel from ['"][^'"]*WorkbenchLedgerPanel\.vue['"]/)
  assert.match(orderSource, /import WorkbenchDetailPanel from ['"][^'"]*WorkbenchDetailPanel\.vue['"]/)
  assert.match(orderSource, /<WorkbenchPage class="order-page">/)
  assert.match(orderSource, /<MyHeader\s*\/>/)
  assert.match(orderSource, /<WorkbenchToolbar class="order-toolbar">/)
  assert.match(orderSource, /<div class="workbench-page-title">订单管理<\/div>/)
  assert.match(orderSource, /<div class="workbench-page-meta">[\s\S]*订单账本、请求上下文、状态流转、成交回报/)
  assert.match(orderSource, /<WorkbenchSummaryRow class="order-filter-chips">/)
  assert.match(orderSource, /<el-alert[\s\S]*v-if="pageError"[\s\S]*class="workbench-alert"[\s\S]*type="error"/)
  assert.match(orderSource, /<WorkbenchPanel class="order-stats-panel"/)
  assert.match(orderSource, /<div class="workbench-panel__title">订单摘要<\/div>/)
  assert.match(orderSource, /<WorkbenchLedgerPanel class="order-list-panel"/)
  assert.match(orderSource, /<div class="workbench-panel__title">订单列表<\/div>/)
  assert.match(orderSource, /<el-empty v-if="rows\.length === 0" description="当前筛选下没有订单。"/)
  assert.match(orderSource, /<WorkbenchDetailPanel class="order-detail-panel"/)
  assert.match(orderSource, /<div class="workbench-panel__title">\{\{\s*detail\.headerTitle\s*\}\}<\/div>/)
  assert.match(orderSource, /<div v-else class="workbench-empty">先从左侧订单列表选择一笔订单。<\/div>/)
})

test('TpslManagement.vue reuses StatusChip for toolbar and symbol-list badges', () => {
  assert.match(tpslSource, /import StatusChip from '\.\.\/components\/workbench\/StatusChip\.vue'/)
  assert.match(tpslSource, /<StatusChip>\s*标的数 <strong>\{\{\s*overviewRows\.length\s*\}\}<\/strong>/)
  assert.match(tpslSource, /<StatusChip variant="success">\s*持仓中 <strong>\{\{\s*holdingCount\s*\}\}<\/strong>/)
  assert.match(tpslSource, /<StatusChip variant="warning">\s*活跃止损 <strong>\{\{\s*activeStoplossCount\s*\}\}<\/strong>/)
  assert.match(tpslSource, /<StatusChip variant="muted">\s*\{\{\s*row\.position_amount_label\s*\}\}\s*<\/StatusChip>/)
  assert.match(tpslSource, /<StatusChip[\s\S]*v-for="badge in row\.badges"/)
  assert.match(tpslSource, /<StatusChip[\s\S]*v-for="tierLabel in row\.takeprofitSummary"/)
  assert.doesNotMatch(tpslSource, /<span class="workbench-summary-chip workbench-summary-chip--muted">\s*\{\{\s*row\.position_amount_label\s*\}\}\s*<\/span>/)
})

test('TpslManagement.vue consumes shared workbench page toolbar and panel primitives for sidebar and detail ledgers', () => {
  assert.match(tpslSource, /import WorkbenchPage from ['"][^'"]*WorkbenchPage\.vue['"]/)
  assert.match(tpslSource, /import WorkbenchToolbar from ['"][^'"]*WorkbenchToolbar\.vue['"]/)
  assert.match(tpslSource, /import WorkbenchSummaryRow from ['"][^'"]*WorkbenchSummaryRow\.vue['"]/)
  assert.match(tpslSource, /import WorkbenchSidebarPanel from ['"][^'"]*WorkbenchSidebarPanel\.vue['"]/)
  assert.match(tpslSource, /import WorkbenchLedgerPanel from ['"][^'"]*WorkbenchLedgerPanel\.vue['"]/)
  assert.match(tpslSource, /import WorkbenchDetailPanel from ['"][^'"]*WorkbenchDetailPanel\.vue['"]/)
  assert.match(tpslSource, /<WorkbenchPage class="tpsl-page">/)
  assert.match(tpslSource, /<MyHeader\s*\/>/)
  assert.match(tpslSource, /<WorkbenchToolbar class="tpsl-toolbar">/)
  assert.match(tpslSource, /<div class="workbench-page-title">股票止盈止损管理<\/div>/)
  assert.match(tpslSource, /<div class="workbench-page-meta">[\s\S]*左侧只读展示三层止盈价格[\s\S]*右侧按持仓 entry 维护止损/)
  assert.match(tpslSource, /<WorkbenchSummaryRow class="tpsl-summary-row">/)
  assert.match(tpslSource, /<el-alert[\s\S]*v-if="pageError"[\s\S]*class="workbench-alert"[\s\S]*type="error"/)
  assert.match(tpslSource, /<WorkbenchSidebarPanel class="tpsl-sidebar-panel">/)
  assert.match(tpslSource, /<div class="workbench-panel__title">标的列表<\/div>/)
  assert.match(tpslSource, /<WorkbenchDetailPanel v-if="detail" class="tpsl-detail-panel">/)
  assert.match(tpslSource, /<div class="workbench-panel__title">[\s\S]*\{\{\s*detail\.name \|\| detail\.symbol\s*\}\}/)
  assert.match(tpslSource, /<WorkbenchLedgerPanel v-if="detail" class="tpsl-ledger-panel">/)
  assert.match(tpslSource, /<div class="workbench-panel__title">按持仓入口止损<\/div>/)
  assert.match(tpslSource, /<el-empty v-if="detail\.entrySlices\.length === 0" description="当前没有 entry slice 记录。"/)
  assert.match(tpslSource, /<el-empty v-if="detail\.historyRows\.length === 0" description="当前没有历史事件。"/)
  assert.match(tpslSource, /<section v-else class="workbench-empty">[\s\S]*左侧先选择一个标的。[\s\S]*<\/section>/)
})

test('SubjectManagement.vue reuses StatusChip for summary and editor chips', () => {
  assert.match(subjectSource, /import StatusChip from '\.\.\/components\/workbench\/StatusChip\.vue'/)
  assert.match(subjectSource, /<StatusChip>\s*总标的 <strong>\{\{\s*overviewRows\.length\s*\}\}<\/strong>/)
  assert.match(subjectSource, /<StatusChip variant="muted">\s*当前筛选 <strong>\{\{\s*filteredOverviewRows\.length\s*\}\}<\/strong>/)
  assert.match(subjectSource, /<StatusChip variant="success">\s*持仓中 <strong>\{\{\s*holdingCount\s*\}\}<\/strong>/)
  assert.match(subjectSource, /<StatusChip variant="warning">\s*活跃止损 <strong>\{\{\s*activeStoplossCount\s*\}\}<\/strong>/)
  assert.match(subjectSource, /<StatusChip v-if="pmSummary\.effective_state" :variant="pmStateChipVariant">/)
  assert.match(subjectSource, /<StatusChip[\s\S]*v-for="chip in detailSummaryChips"/)
})

test('SubjectManagement.vue consumes shared workbench page toolbar and panel primitives for overview and editor stacks', () => {
  assert.match(subjectSource, /import WorkbenchPage from ['"][^'"]*WorkbenchPage\.vue['"]/)
  assert.match(subjectSource, /import WorkbenchToolbar from ['"][^'"]*WorkbenchToolbar\.vue['"]/)
  assert.match(subjectSource, /import WorkbenchSummaryRow from ['"][^'"]*WorkbenchSummaryRow\.vue['"]/)
  assert.match(subjectSource, /import WorkbenchLedgerPanel from ['"][^'"]*WorkbenchLedgerPanel\.vue['"]/)
  assert.match(subjectSource, /import WorkbenchDetailPanel from ['"][^'"]*WorkbenchDetailPanel\.vue['"]/)
  assert.match(subjectSource, /<WorkbenchPage class="subject-management-page">/)
  assert.match(subjectSource, /<MyHeader\s*\/>/)
  assert.match(subjectSource, /<WorkbenchToolbar class="subject-management-toolbar">/)
  assert.match(subjectSource, /<div class="workbench-page-title">标的管理<\/div>/)
  assert.match(subjectSource, /<div class="workbench-page-meta">[\s\S]*左侧高密度汇总当前配置[\s\S]*右侧集中编辑基础设置/)
  assert.match(subjectSource, /<WorkbenchSummaryRow class="subject-management-summary">/)
  assert.match(subjectSource, /<el-alert[\s\S]*v-if="pageError"[\s\S]*class="workbench-alert"[\s\S]*type="error"/)
  assert.match(subjectSource, /<WorkbenchLedgerPanel class="subject-overview-panel">/)
  assert.match(subjectSource, /<div class="workbench-panel__title">标的总览<\/div>/)
  assert.match(subjectSource, /<WorkbenchDetailPanel class="subject-editor-table-panel">/)
  assert.match(subjectSource, /<div class="workbench-panel__header subject-editor-table-header">/)
  assert.match(subjectSource, /<div class="workbench-panel__title">基础配置 \+ 单标的仓位上限<\/div>/)
  assert.match(subjectSource, /<div class="workbench-panel__title">按持仓入口止损<\/div>/)
  assert.match(subjectSource, /<section v-else class="workbench-empty">[\s\S]*左侧先选择一个标的。[\s\S]*<\/section>/)
})

test('DailyScreening.vue reuses StatusChip for toolbar guide summary and detail membership chips', () => {
  assert.match(dailySource, /import StatusChip from '\.\.\/components\/workbench\/StatusChip\.vue'/)
  assert.match(dailySource, /<StatusChip[\s\S]*v-for="line in workbenchGuideLines"[\s\S]*variant="muted"/)
  assert.match(dailySource, /<StatusChip variant="muted">\s*当前 scope <strong>\{\{\s*selectedScopeLabel\s*\}\}<\/strong>/)
  assert.match(dailySource, /<StatusChip variant="success">\s*基础池 <strong>\{\{\s*scopeSummary\?\.stock_count \?\? 0\s*\}\}<\/strong>/)
  assert.match(dailySource, /<StatusChip variant="warning">\s*当前结果 <strong>\{\{\s*resultRows\.length\s*\}\}<\/strong>/)
  assert.match(dailySource, /<StatusChip[\s\S]*v-for="item in detail\.clsMemberships"[\s\S]*variant="muted"/)
  assert.match(dailySource, /<StatusChip[\s\S]*v-for="item in detail\.hotMemberships"[\s\S]*variant="warning"/)
  assert.match(dailySource, /<StatusChip[\s\S]*v-for="item in detail\.marketFlagMemberships"[\s\S]*variant="success"/)
  assert.match(dailySource, /<StatusChip[\s\S]*:variant="detailBasePoolStatus\.inBasePool \? 'success' : 'warning'"/)
})

test('DailyScreening.vue consumes shared workbench page toolbar and panel primitives for the filter result and detail workspace', () => {
  assert.match(dailySource, /import WorkbenchPage from ['"][^'"]*WorkbenchPage\.vue['"]/)
  assert.match(dailySource, /import WorkbenchToolbar from ['"][^'"]*WorkbenchToolbar\.vue['"]/)
  assert.match(dailySource, /import WorkbenchSummaryRow from ['"][^'"]*WorkbenchSummaryRow\.vue['"]/)
  assert.match(dailySource, /import WorkbenchSidebarPanel from ['"][^'"]*WorkbenchSidebarPanel\.vue['"]/)
  assert.match(dailySource, /import WorkbenchLedgerPanel from ['"][^'"]*WorkbenchLedgerPanel\.vue['"]/)
  assert.match(dailySource, /import WorkbenchDetailPanel from ['"][^'"]*WorkbenchDetailPanel\.vue['"]/)
  assert.match(dailySource, /<WorkbenchPage class="daily-screening-page">/)
  assert.match(dailySource, /<MyHeader\s*\/>/)
  assert.match(dailySource, /<WorkbenchToolbar class="daily-screening-toolbar">/)
  assert.match(dailySource, /<div class="workbench-page-title">每日选股<\/div>/)
  assert.match(dailySource, /<div class="workbench-page-meta">[\s\S]*Dagster 预计算[\s\S]*统一条件池交集/)
  assert.match(dailySource, /<WorkbenchSummaryRow class="daily-screening-summary">/)
  assert.match(dailySource, /<el-alert[\s\S]*v-if="pageError"[\s\S]*class="workbench-alert"[\s\S]*type="error"/)
  assert.match(dailySource, /<WorkbenchSidebarPanel class="daily-filter-panel"/)
  assert.match(dailySource, /<WorkbenchLedgerPanel class="daily-results-panel"/)
  assert.match(dailySource, /<div class="workbench-panel__header daily-results-header">/)
  assert.match(dailySource, /<div class="workbench-panel__title">交集列表<\/div>/)
  assert.match(dailySource, /<div v-else class="runtime-empty-panel daily-empty-panel">[\s\S]*当前筛选暂无结果/)
  assert.match(dailySource, /<WorkbenchLedgerPanel class="daily-workspace-panel"/)
  assert.match(dailySource, /<div class="workbench-panel__title">工作区<\/div>/)
  assert.match(dailySource, /<WorkbenchDetailPanel class="daily-detail-overview-panel"/)
  assert.match(dailySource, /<div class="workbench-panel__title">标的详情<\/div>/)
  assert.match(dailySource, /<div v-else class="workbench-empty daily-empty">请先选择一只股票。<\/div>/)
})

test('KlineSlim.vue reuses StatusChip for toolbar, overlay summaries and chanlun summary rows', () => {
  assert.match(klineSlimSource, /import StatusChip from '\.\.\/components\/workbench\/StatusChip\.vue'/)
  assert.match(klineSlimSource, /<StatusChip[\s\S]*variant="muted"[\s\S]*>\s*主图 \{\{\s*currentPeriod\s*\}\}/)
  assert.match(klineSlimSource, /<StatusChip[\s\S]*:variant="toolbarStatusChipVariant"/)
  assert.match(klineSlimSource, /<StatusChip[\s\S]*variant="muted"[\s\S]*>\s*当前止损/)
  assert.match(klineSlimSource, /<StatusChip[\s\S]*:variant="subjectPositionLimitChipVariant"/)
  assert.match(klineSlimSource, /<StatusChip[\s\S]*:variant="takeprofitRuntimeChipVariant"/)
  assert.match(klineSlimSource, /<StatusChip[\s\S]*:variant="guardianRuntimeChipVariant"/)
  assert.match(klineSlimSource, /<StatusChip[\s\S]*v-for="field in chanlunHigherSegmentSummary"[\s\S]*variant="info"/)
  assert.match(klineSlimSource, /<StatusChip[\s\S]*v-for="field in chanlunSegmentSummary"[\s\S]*variant="info"/)
  assert.match(klineSlimSource, /<StatusChip[\s\S]*v-for="field in chanlunBiSummary"[\s\S]*variant="info"/)
  assert.match(klineSlimSource, /<el-alert[\s\S]*v-if="pageAlertVisible"[\s\S]*class="workbench-alert kline-slim-page-alert"[\s\S]*:type="pageAlertType"[\s\S]*:title="pageAlertTitle"/)
})

test('KlineHeader.vue no longer exposes a retired futures main-entry button', () => {
  assert.match(klineHeaderSource, /jumpToControl\('stock'\)/)
  assert.match(klineHeaderSource, />股票<\/el-button/)
  assert.match(klineHeaderSource, />多周期<\/el-button/)
  assert.doesNotMatch(klineHeaderSource, /jumpToControl\('futures'\)/)
  assert.doesNotMatch(klineHeaderSource, />期货<\/el-button/)
})

test('KlineSlim.vue consumes WorkbenchPage for the chart workbench shell', () => {
  assert.match(klineSlimSource, /import WorkbenchPage from ['"][^'"]*WorkbenchPage\.vue['"]/)
  assert.match(klineSlimSource, /import WorkbenchToolbar from ['"][^'"]*WorkbenchToolbar\.vue['"]/)
  assert.match(klineSlimSource, /import MyHeader from ['"][^'"]*MyHeader\.vue['"]/)
  assert.match(klineSlimSource, /<WorkbenchPage class="kline-big-main kline-slim-main">/)
  assert.match(klineSlimSource, /<MyHeader\s*\/>/)
  assert.match(klineSlimSource, /<WorkbenchToolbar class="kline-slim-toolbar">/)
  assert.match(klineSlimSource, /<div class="workbench-page-title">焦点图表<\/div>/)
  assert.match(klineSlimSource, /<div class="workbench-page-meta">[\s\S]*主图 \+ 侧栏观察清单[\s\S]*标的设置、画线编辑、缠论结构/)
  assert.match(klineSlimSource, /<span class="workbench-panel__title">\{\{\s*section\.label\s*\}\}<\/span>/)
  assert.match(klineSlimSource, /<span class="price-panel-title workbench-panel__title">标的设置<\/span>/)
  assert.match(klineSlimSource, /<span class="price-panel-title workbench-panel__title">画线编辑<\/span>/)
  assert.match(klineSlimSource, /<span class="chanlun-panel-title workbench-panel__title">缠论结构<\/span>/)
  assert.match(klineSlimSource, /<div v-if="!routeSymbol" class="workbench-empty kline-slim-empty">/)
})

test('StockControl.vue consumes shared workbench page and ledger panel primitives for the three signal columns', () => {
  assert.match(stockControlSource, /import WorkbenchPage from ['"][^'"]*WorkbenchPage\.vue['"]/)
  assert.match(stockControlSource, /import WorkbenchToolbar from ['"][^'"]*WorkbenchToolbar\.vue['"]/)
  assert.match(stockControlSource, /import WorkbenchSummaryRow from ['"][^'"]*WorkbenchSummaryRow\.vue['"]/)
  assert.match(stockControlSource, /import WorkbenchLedgerPanel from ['"][^'"]*WorkbenchLedgerPanel\.vue['"]/)
  assert.match(stockControlSource, /<WorkbenchPage class="stock-control-page">/)
  assert.match(stockControlSource, /<MyHeader\s*\/>/)
  assert.match(stockControlSource, /<WorkbenchToolbar class="stock-control-toolbar">/)
  assert.match(stockControlSource, /<WorkbenchLedgerPanel class="stock-control-panel">/)
  assert.doesNotMatch(stockControlSource, /class="panel-card"/)
})

test('StockControl.vue follows the main workbench contract instead of a stock-only special shell', () => {
  assert.match(stockControlSource, /<div class="workbench-page-title">股票<\/div>/)
  assert.match(stockControlSource, /<div class="workbench-page-meta">[\s\S]*三栏信号工作台[\s\S]*持仓股、模型信号、must_pool 买入信号/)
  assert.match(stockControlSource, /<el-alert[\s\S]*class="workbench-alert"[\s\S]*type="info"[\s\S]*title="各栏独立加载；无信号时保持统一空表结构。"/)
  assert.match(stockControlSource, /<WorkbenchSummaryRow class="stock-control-summary">/)
  assert.match(stockControlSource, /<StatusChip variant="muted">持仓股信号<\/StatusChip>/)
  assert.match(stockControlSource, /<StatusChip variant="info">stock_pools 模型信号<\/StatusChip>/)
  assert.match(stockControlSource, /<StatusChip variant="warning">must_pool 买入信号<\/StatusChip>/)
  assert.match(stockControlSource, /<div class="workbench-panel__title">持仓股信号<\/div>/)
  assert.match(stockControlSource, /<div class="workbench-panel__title">stock_pools 模型信号<\/div>/)
  assert.match(stockControlSource, /<div class="workbench-panel__title">must_pool 买入信号<\/div>/)
  assert.doesNotMatch(stockControlSource, /<div class="stock-control-page-title">/)
})

test('retired standalone workbench pages are removed from the design-system surface', () => {
  const retiredPageFiles = [
    new URL('../components/StockPools.vue', import.meta.url),
    new URL('../components/StockCjsd.vue', import.meta.url),
    new URL('./FuturesControl.vue', import.meta.url),
  ]

  for (const fileUrl of retiredPageFiles) {
    assert.equal(existsSync(fileUrl), false, `${fileUrl} should be removed`)
  }
})

test('GanttUnified.vue consumes shared workbench page and toolbar primitives while keeping provider switch radio buttons', () => {
  assert.match(ganttSource, /import WorkbenchPage from ['"][^'"]*WorkbenchPage\.vue['"]/)
  assert.match(ganttSource, /import WorkbenchToolbar from ['"][^'"]*WorkbenchToolbar\.vue['"]/)
  assert.match(ganttSource, /<WorkbenchPage class="gantt-page">/)
  assert.match(ganttSource, /<WorkbenchToolbar class="gantt-toolbar">/)
  assert.match(ganttSource, /<el-radio-group v-model="activeProvider"/)
  assert.doesNotMatch(ganttSource, /<div class="gantt-tabs">/)
})

test('GanttUnifiedStocks.vue consumes shared workbench page and toolbar primitives while keeping provider switch radio buttons', () => {
  assert.match(ganttStocksSource, /import WorkbenchPage from ['"][^'"]*WorkbenchPage\.vue['"]/)
  assert.match(ganttStocksSource, /import WorkbenchToolbar from ['"][^'"]*WorkbenchToolbar\.vue['"]/)
  assert.match(ganttStocksSource, /<WorkbenchPage class="gantt-page">/)
  assert.match(ganttStocksSource, /<WorkbenchToolbar class="gantt-toolbar">/)
  assert.match(ganttStocksSource, /<el-radio-group v-model="activeProvider"/)
  assert.doesNotMatch(ganttStocksSource, /<div class="gantt-tabs">/)
})

test('active chart routes still consume WorkbenchPage as the shared shell even when they keep specialized internals', () => {
  for (const [label, source] of [
    ['KlineBig.vue', klineBigSource],
    ['KlineSlim.vue', klineSlimSource],
    ['MultiPeriod.vue', multiPeriodSource],
  ]) {
    assert.match(source, /import WorkbenchPage from ['"][^'"]*WorkbenchPage\.vue['"]/)
    assert.match(source, /<WorkbenchPage\b/, `${label} should opt into the shared WorkbenchPage shell`)
  }
})

test('SystemSettings.vue reuses shared workbench page toolbar and status chip primitives', () => {
  assert.match(systemSettingsSource, /import WorkbenchPage from ['"][^'"]*WorkbenchPage\.vue['"]/)
  assert.match(systemSettingsSource, /import WorkbenchToolbar from ['"][^'"]*WorkbenchToolbar\.vue['"]/)
  assert.match(systemSettingsSource, /import WorkbenchSummaryRow from ['"][^'"]*WorkbenchSummaryRow\.vue['"]/)
  assert.match(systemSettingsSource, /import StatusChip from ['"][^'"]*StatusChip\.vue['"]/)
  assert.match(systemSettingsSource, /<WorkbenchPage class="system-settings-page system-settings-shell">/)
  assert.match(systemSettingsSource, /<MyHeader\s*\/>/)
  assert.match(systemSettingsSource, /<WorkbenchToolbar class="settings-dense-toolbar">/)
  assert.match(systemSettingsSource, /<div class="workbench-page-title">系统设置<\/div>/)
  assert.match(systemSettingsSource, /<div class="workbench-page-meta">[\s\S]*正式真值只保留 Bootstrap 文件与 Mongo。[\s\S]*当前页面直接以内嵌列表编辑全部正式设置项。/)
  assert.match(systemSettingsSource, /<WorkbenchSummaryRow class="settings-toolbar-meta">/)
  assert.match(systemSettingsSource, /<el-alert[\s\S]*v-if="pageError"[\s\S]*class="workbench-alert page-error"[\s\S]*type="error"/)
  assert.match(systemSettingsSource, /<StatusChip class="settings-toolbar-chip settings-toolbar-chip--path" variant="info"/)
  assert.match(systemSettingsSource, /<StatusChip class="settings-inline-chip" :variant="sectionModeChipVariant\(section\)">/)
  assert.match(systemSettingsSource, /<StatusChip class="settings-inline-chip" :variant="restartModeChipVariant\(row\.restart_required\)">/)
  assert.match(systemSettingsSource, /<StatusChip class="settings-inline-chip is-source" variant="info"/)
  assert.match(systemSettingsSource, /<StatusChip class="settings-inline-chip" :variant="stateChipVariant\(row\)">/)
})

test('GanttShouban30Phase1.vue reuses shared workbench toolbar and panel primitives and no longer relies on provider el-tabs', () => {
  assert.match(shoubanSource, /import WorkbenchPage from ['"][^'"]*WorkbenchPage\.vue['"]/)
  assert.match(shoubanSource, /import WorkbenchToolbar from ['"][^'"]*WorkbenchToolbar\.vue['"]/)
  assert.match(shoubanSource, /import WorkbenchLedgerPanel from ['"][^'"]*WorkbenchLedgerPanel\.vue['"]/)
  assert.match(shoubanSource, /import WorkbenchSidebarPanel from ['"][^'"]*WorkbenchSidebarPanel\.vue['"]/)
  assert.match(shoubanSource, /import WorkbenchDetailPanel from ['"][^'"]*WorkbenchDetailPanel\.vue['"]/)
  assert.match(shoubanSource, /import StatusChip from ['"][^'"]*StatusChip\.vue['"]/)
  assert.match(shoubanSource, /<WorkbenchPage class="shouban30-page shouban30-shell">/)
  assert.match(shoubanSource, /<WorkbenchToolbar class="shouban30-toolbar">/)
  assert.match(shoubanSource, /<WorkbenchSidebarPanel class="shouban30-panel shouban30-panel--plates">/)
  assert.match(shoubanSource, /<WorkbenchLedgerPanel class="shouban30-panel shouban30-panel--stocks">/)
  assert.match(shoubanSource, /<WorkbenchDetailPanel class="shouban30-panel shouban30-panel--detail">/)
  assert.match(shoubanSource, /<WorkbenchLedgerPanel class="shouban30-panel shouban30-panel--workspace">/)
  assert.match(shoubanSource, /<el-radio-group[\s\S]*:model-value="activeViewProvider"/)
  assert.match(shoubanSource, /<el-radio-button[\s\S]*v-for="option in VIEW_PROVIDER_OPTIONS"/)
  assert.doesNotMatch(shoubanSource, /<el-tabs[\s\S]*class="provider-tabs"/)
  assert.doesNotMatch(shoubanSource, /<section class="panel-card"/)
})

test('MyHeader.vue renders navigation from grouped metadata instead of hardcoded buttons', () => {
  assert.match(headerSource, /import \{[\s\S]*HEADER_NAV_GROUPS[\s\S]*HEADER_NAV_TARGETS[\s\S]*getHeaderNavTarget[\s\S]*\} from '@\/router\/pageMeta\.mjs'/)
  assert.match(headerSource, /headerNavGroups\(\)\s*\{\s*return HEADER_NAV_GROUPS\.map/)
  assert.match(headerSource, /const meta = HEADER_NAV_TARGETS\[key\] \|\| \{\}/)
  assert.match(headerSource, /<el-button-group v-for="\(\s*group,\s*groupIndex\s*\) in headerNavGroups"/)
  assert.match(headerSource, /<el-button\s+v-for="item in group"/)
  assert.doesNotMatch(headerSource, /@click="goSetting"/)
  assert.doesNotMatch(headerSource, /jumpToControl\('futures'\)/)
  assert.doesNotMatch(headerSource, /jumpToControl\('runtime'\)/)
})

test('my-header.styl adds wrap and overflow safety so the navigation does not clip at desktop widths', () => {
  assert.match(headerStyleSource, /\.header-main[\s\S]*flex-wrap wrap/)
  assert.match(headerStyleSource, /\.header-menu[\s\S]*flex-wrap wrap/)
  assert.match(headerStyleSource, /\.header-menu[\s\S]*overflow-x auto/)
  assert.match(headerStyleSource, /\.header-tip[\s\S]*min-width 240px/)
  assert.match(headerStyleSource, /@media \(max-width: 1440px\)/)
})
