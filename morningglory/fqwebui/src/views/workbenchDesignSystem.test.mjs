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
const positionReconciliationSource = readSource('../components/position-management/PositionReconciliationPanel.vue')
const positionSubjectOverviewSource = readSource('../components/position-management/PositionSubjectOverviewPanel.vue')
const orderSource = readSource('./OrderManagement.vue')
const tpslSource = readSource('./TpslManagement.vue')
const subjectSource = readSource('./SubjectManagement.vue')
const dailySource = readSource('./DailyScreening.vue')
const klineSlimSource = readSource('./KlineSlim.vue')
const stockControlSource = readSource('./StockControl.vue')
const stockPoolsSource = readSource('../components/StockPools.vue')
const stockCjsdSource = readSource('../components/StockCjsd.vue')
const ganttSource = readSource('./GanttUnified.vue')
const ganttStocksSource = readSource('./GanttUnifiedStocks.vue')
const futuresSource = readSource('./FuturesControl.vue')
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
  assert.match(runtimeSource, /<StatusChip class="runtime-inline-status" :variant="row\.trace_status_chip_variant \|\| statusChipVariant\(row\.trace_status\)">/)
  assert.match(runtimeSource, /<StatusChip class="runtime-inline-status" :variant="statusChipVariant\(row\.status\)">/)
  assert.doesNotMatch(runtimeSource, /<span class="runtime-inline-status" :class="statusClass\(item\.status\)">/)
  assert.doesNotMatch(runtimeSource, /<span class="runtime-inline-status" :class="statusClass\(row\.trace_status\)">/)
  assert.doesNotMatch(runtimeSource, /<span class="runtime-inline-status" :class="statusClass\(row\.status\)">/)
})

test('PositionManagement.vue reuses StatusChip for summary chips and inline ledger states', () => {
  assert.match(positionSource, /import StatusChip from '\.\.\/components\/workbench\/StatusChip\.vue'/)
  assert.match(positionSource, /<StatusChip :variant="stateToneChipVariant">/)
  assert.match(positionSource, /<StatusChip :variant="staleChipVariant">/)
  assert.match(positionSource, /<StatusChip variant="muted">\s*raw state <strong>\{\{\s*statePanel\.hero\.raw_state_label\s*\}\}<\/strong>/)
  assert.match(positionSource, /<StatusChip variant="muted">\s*配置时间 <strong>\{\{\s*configUpdatedAt\s*\}\}<\/strong>/)
  assert.match(positionSource, /<StatusChip variant="muted">\s*当前标的 <strong>\{\{\s*selectedSubjectSymbol/)
  assert.match(positionSource, /<StatusChip variant="muted">\s*当前页 <strong>\{\{\s*pagedDecisionRows\.length\s*\}\}<\/strong>/)
  assert.match(positionSource, /<StatusChip variant="muted">\s*默认分页 <strong>\{\{\s*decisionPagination\.pageSize\s*\}\} \/ 页<\/strong>/)
  assert.match(positionSource, /<StatusChip variant="muted">\s*当前页码 <strong>\{\{\s*decisionPagination\.page\s*\}\}<\/strong>/)
  assert.match(positionSource, /<StatusChip class="runtime-inline-status" :variant="ruleStatusChipVariant\(row\.allowed\)">/)
  assert.match(positionSource, /<StatusChip class="runtime-inline-status" :variant="decisionStatusChipVariant\(row\.tone\)">/)
  assert.match(positionSource, /<PositionReconciliationPanel/)
  assert.match(positionSource, /<PositionSubjectOverviewPanel/)
  assert.doesNotMatch(positionSource, /<span class="runtime-inline-status" :class="resolveRuleStatusClass\(row\.allowed\)">/)
  assert.doesNotMatch(positionSource, /<span class="runtime-inline-status" :class="resolveDecisionStatusClass\(row\.tone\)">/)
})

test('PositionManagement.vue consumes shared workbench page and panel primitives for state limits and decisions', () => {
  assert.match(positionSource, /import WorkbenchPage from ['"][^'"]*WorkbenchPage\.vue['"]/)
  assert.match(positionSource, /import WorkbenchDetailPanel from ['"][^'"]*WorkbenchDetailPanel\.vue['"]/)
  assert.match(positionSource, /import WorkbenchLedgerPanel from ['"][^'"]*WorkbenchLedgerPanel\.vue['"]/)
  assert.match(positionSource, /<WorkbenchPage class="position-page">/)
  assert.match(positionSource, /<WorkbenchDetailPanel class="position-state-panel">/)
  assert.match(positionSource, /<PositionReconciliationPanel[\s\S]*class="position-reconciliation-panel"/)
  assert.match(positionSource, /<PositionSubjectOverviewPanel class="position-subject-overview-host"/)
  assert.match(positionSource, /<WorkbenchLedgerPanel class="position-selection-panel">/)
  assert.match(positionSource, /<WorkbenchLedgerPanel class="position-decision-panel">/)
})

test('PositionReconciliationPanel.vue consumes shared workbench panel and status chip primitives for dense audit ledgers', () => {
  assert.match(positionReconciliationSource, /import StatusChip from '\.\.\/workbench\/StatusChip\.vue'/)
  assert.match(positionReconciliationSource, /import WorkbenchLedgerPanel from '\.\.\/workbench\/WorkbenchLedgerPanel\.vue'/)
  assert.match(positionReconciliationSource, /<WorkbenchLedgerPanel class="position-reconciliation-panel">/)
  assert.match(positionReconciliationSource, /<StatusChip variant="danger">\s*ERROR <strong>\{\{\s*summary\.audit_status_counts\?\.ERROR \|\| 0\s*\}\}<\/strong>/)
  assert.match(positionReconciliationSource, /<StatusChip class="runtime-inline-status" :variant="row\.audit_status_chip_variant">/)
  assert.match(positionReconciliationSource, /<StatusChip class="runtime-inline-status" :variant="row\.reconciliation_state_chip_variant">/)
  assert.match(positionReconciliationSource, /position-reconciliation-ledger/)
  assert.doesNotMatch(positionReconciliationSource, /position-audit-row/)
})

test('PositionSubjectOverviewPanel.vue consumes shared workbench panel and status chip primitives for the dense selected-symbol overview table', () => {
  assert.match(positionSubjectOverviewSource, /import StatusChip from '\.\.\/workbench\/StatusChip\.vue'/)
  assert.match(positionSubjectOverviewSource, /import WorkbenchLedgerPanel from '\.\.\/workbench\/WorkbenchLedgerPanel\.vue'/)
  assert.match(positionSubjectOverviewSource, /<WorkbenchLedgerPanel class="position-subject-overview-panel">/)
  assert.match(positionSubjectOverviewSource, /defineEmits\(\['symbol-select'\]\)/)
  assert.match(positionSubjectOverviewSource, /highlight-current-row/)
  assert.match(positionSubjectOverviewSource, /label="Guardian 层级买入"/)
  assert.match(positionSubjectOverviewSource, /label="止盈价格"/)
  assert.match(positionSubjectOverviewSource, /label="全仓止损价"/)
  assert.match(positionSubjectOverviewSource, /label="首笔买入金额"/)
  assert.match(positionSubjectOverviewSource, /label="默认买入金额"/)
  assert.match(positionSubjectOverviewSource, /label="单标的仓位上限"/)
  assert.match(positionSubjectOverviewSource, /label="保存"/)
  assert.match(positionSubjectOverviewSource, /<StatusChip variant="muted">\s*总标的 <strong>\{\{\s*overviewRows\.length\s*\}\}<\/strong>/)
  assert.match(positionSubjectOverviewSource, /<StatusChip variant="success">\s*已加载详情 <strong>\{\{\s*loadedDetailCount\s*\}\}<\/strong>/)
  assert.match(positionSubjectOverviewSource, /<StatusChip variant="warning">\s*活跃单笔止损 <strong>\{\{\s*activeStoplossCount\s*\}\}<\/strong>/)
  assert.doesNotMatch(positionSubjectOverviewSource, /label="止损价"/)
  assert.doesNotMatch(positionSubjectOverviewSource, /position-subject-entry-card/)
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
  assert.match(orderSource, /import WorkbenchPanel from ['"][^'"]*WorkbenchPanel\.vue['"]/)
  assert.match(orderSource, /import WorkbenchLedgerPanel from ['"][^'"]*WorkbenchLedgerPanel\.vue['"]/)
  assert.match(orderSource, /import WorkbenchDetailPanel from ['"][^'"]*WorkbenchDetailPanel\.vue['"]/)
  assert.match(orderSource, /<WorkbenchPage class="order-page">/)
  assert.match(orderSource, /<WorkbenchToolbar class="order-toolbar">/)
  assert.match(orderSource, /<WorkbenchPanel class="order-stats-panel"/)
  assert.match(orderSource, /<WorkbenchLedgerPanel class="order-list-panel"/)
  assert.match(orderSource, /<WorkbenchDetailPanel class="order-detail-panel"/)
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
  assert.match(tpslSource, /import WorkbenchSidebarPanel from ['"][^'"]*WorkbenchSidebarPanel\.vue['"]/)
  assert.match(tpslSource, /import WorkbenchLedgerPanel from ['"][^'"]*WorkbenchLedgerPanel\.vue['"]/)
  assert.match(tpslSource, /import WorkbenchDetailPanel from ['"][^'"]*WorkbenchDetailPanel\.vue['"]/)
  assert.match(tpslSource, /<WorkbenchPage class="tpsl-page">/)
  assert.match(tpslSource, /<WorkbenchToolbar class="tpsl-toolbar">/)
  assert.match(tpslSource, /<WorkbenchSidebarPanel class="tpsl-sidebar-panel">/)
  assert.match(tpslSource, /<WorkbenchDetailPanel v-if="detail" class="tpsl-detail-panel">/)
  assert.match(tpslSource, /<WorkbenchLedgerPanel v-if="detail" class="tpsl-ledger-panel">/)
})

test('SubjectManagement.vue reuses StatusChip for summary and editor chips', () => {
  assert.match(subjectSource, /import StatusChip from '\.\.\/components\/workbench\/StatusChip\.vue'/)
  assert.match(subjectSource, /<StatusChip>\s*总标的 <strong>\{\{\s*overviewRows\.length\s*\}\}<\/strong>/)
  assert.match(subjectSource, /<StatusChip variant="muted">\s*当前筛选 <strong>\{\{\s*filteredOverviewRows\.length\s*\}\}<\/strong>/)
  assert.match(subjectSource, /<StatusChip variant="success">\s*持仓中 <strong>\{\{\s*holdingCount\s*\}\}<\/strong>/)
  assert.match(subjectSource, /<StatusChip variant="warning">\s*活跃止损 <strong>\{\{\s*activeStoplossCount\s*\}\}<\/strong>/)
  assert.match(subjectSource, /<StatusChip v-if="pmSummary\.effective_state" :variant="pmSummary\.effective_state_chip_variant">/)
  assert.match(subjectSource, /<StatusChip[\s\S]*v-for="chip in detailSummaryChips"/)
})

test('SubjectManagement.vue consumes shared workbench page toolbar and panel primitives for overview and editor stacks', () => {
  assert.match(subjectSource, /import WorkbenchPage from ['"][^'"]*WorkbenchPage\.vue['"]/)
  assert.match(subjectSource, /import WorkbenchToolbar from ['"][^'"]*WorkbenchToolbar\.vue['"]/)
  assert.match(subjectSource, /import WorkbenchLedgerPanel from ['"][^'"]*WorkbenchLedgerPanel\.vue['"]/)
  assert.match(subjectSource, /import WorkbenchDetailPanel from ['"][^'"]*WorkbenchDetailPanel\.vue['"]/)
  assert.match(subjectSource, /<WorkbenchPage class="subject-management-page">/)
  assert.match(subjectSource, /<WorkbenchToolbar class="subject-management-toolbar">/)
  assert.match(subjectSource, /<WorkbenchLedgerPanel class="subject-overview-panel">/)
  assert.match(subjectSource, /<WorkbenchDetailPanel class="subject-editor-table-panel">/)
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
  assert.match(dailySource, /import WorkbenchSidebarPanel from ['"][^'"]*WorkbenchSidebarPanel\.vue['"]/)
  assert.match(dailySource, /import WorkbenchLedgerPanel from ['"][^'"]*WorkbenchLedgerPanel\.vue['"]/)
  assert.match(dailySource, /import WorkbenchDetailPanel from ['"][^'"]*WorkbenchDetailPanel\.vue['"]/)
  assert.match(dailySource, /<WorkbenchPage class="daily-screening-page">/)
  assert.match(dailySource, /<WorkbenchToolbar class="daily-screening-toolbar">/)
  assert.match(dailySource, /<WorkbenchSidebarPanel class="daily-filter-panel"/)
  assert.match(dailySource, /<WorkbenchLedgerPanel class="daily-results-panel"/)
  assert.match(dailySource, /<WorkbenchLedgerPanel class="daily-workspace-panel"/)
  assert.match(dailySource, /<WorkbenchDetailPanel class="daily-detail-overview-panel"/)
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
})

test('KlineSlim.vue consumes WorkbenchPage for the chart workbench shell', () => {
  assert.match(klineSlimSource, /import WorkbenchPage from ['"][^'"]*WorkbenchPage\.vue['"]/)
  assert.match(klineSlimSource, /<WorkbenchPage class="kline-big-main kline-slim-main">/)
})

test('StockControl.vue consumes shared workbench page and ledger panel primitives for the three signal columns', () => {
  assert.match(stockControlSource, /import WorkbenchPage from ['"][^'"]*WorkbenchPage\.vue['"]/)
  assert.match(stockControlSource, /import WorkbenchToolbar from ['"][^'"]*WorkbenchToolbar\.vue['"]/)
  assert.match(stockControlSource, /import WorkbenchLedgerPanel from ['"][^'"]*WorkbenchLedgerPanel\.vue['"]/)
  assert.match(stockControlSource, /<WorkbenchPage class="stock-control-page">/)
  assert.match(stockControlSource, /<WorkbenchToolbar class="stock-control-toolbar">/)
  assert.match(stockControlSource, /<WorkbenchLedgerPanel class="stock-control-panel">/)
  assert.doesNotMatch(stockControlSource, /class="panel-card"/)
})

test('StockPools.vue consumes shared workbench page toolbar and sidebar panel primitives', () => {
  assert.match(stockPoolsSource, /import WorkbenchPage from ['"][^'"]*WorkbenchPage\.vue['"]/)
  assert.match(stockPoolsSource, /import WorkbenchToolbar from ['"][^'"]*WorkbenchToolbar\.vue['"]/)
  assert.match(stockPoolsSource, /import WorkbenchLedgerPanel from ['"][^'"]*WorkbenchLedgerPanel\.vue['"]/)
  assert.match(stockPoolsSource, /import WorkbenchSidebarPanel from ['"][^'"]*WorkbenchSidebarPanel\.vue['"]/)
  assert.match(stockPoolsSource, /<WorkbenchPage class="stock-pool-page">/)
  assert.match(stockPoolsSource, /<WorkbenchToolbar class="stock-pool-toolbar">/)
  assert.match(stockPoolsSource, /<WorkbenchLedgerPanel class="stock-pool-panel stock-pool-panel--main">/)
  assert.match(stockPoolsSource, /<WorkbenchSidebarPanel class="stock-pool-panel stock-pool-panel--side">/)
  assert.doesNotMatch(stockPoolsSource, /<section class="stock-pool-panel">/)
})

test('StockCjsd.vue consumes shared workbench page toolbar and ledger panel primitives', () => {
  assert.match(stockCjsdSource, /import WorkbenchPage from ['"][^'"]*WorkbenchPage\.vue['"]/)
  assert.match(stockCjsdSource, /import WorkbenchToolbar from ['"][^'"]*WorkbenchToolbar\.vue['"]/)
  assert.match(stockCjsdSource, /import WorkbenchLedgerPanel from ['"][^'"]*WorkbenchLedgerPanel\.vue['"]/)
  assert.match(stockCjsdSource, /<WorkbenchPage class="stock-cjsd-page">/)
  assert.match(stockCjsdSource, /<WorkbenchToolbar class="stock-cjsd-toolbar">/)
  assert.match(stockCjsdSource, /<WorkbenchLedgerPanel class="stock-cjsd-panel">/)
  assert.doesNotMatch(stockCjsdSource, /<section class="stock-cjsd-panel">/)
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

test('legacy chart and control routes still consume WorkbenchPage as the shared shell even when they keep specialized internals', () => {
  for (const [label, source] of [
    ['FuturesControl.vue', futuresSource],
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
  assert.match(systemSettingsSource, /import StatusChip from ['"][^'"]*StatusChip\.vue['"]/)
  assert.match(systemSettingsSource, /<WorkbenchPage class="system-settings-page system-settings-shell">/)
  assert.match(systemSettingsSource, /<WorkbenchToolbar class="settings-dense-toolbar">/)
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
