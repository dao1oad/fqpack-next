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
const positionSubjectOverviewSource = readSource('../components/position-management/PositionSubjectOverviewPanel.vue')
const dailySource = readSource('./DailyScreening.vue')
const klineSlimSource = readSource('./KlineSlim.vue')
const stockControlSource = readSource('./StockControl.vue')
const stockPoolsSource = readSource('../components/StockPools.vue')
const ganttSource = readSource('./GanttUnified.vue')
const ganttStocksSource = readSource('./GanttUnifiedStocks.vue')
const systemSettingsSource = readSource('./SystemSettings.vue')
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
  assert.match(positionSource, /class="position-state-hero"/)
  assert.match(positionSource, /class="position-state-hero__chips"/)
  assert.match(positionSource, /<StatusChip variant="muted">\s*raw state <strong>\{\{\s*statePanel\.hero\.raw_state_label\s*\}\}<\/strong>/)
  assert.match(positionSource, /class="position-state-actions"/)
  assert.match(positionSource, /class="position-state-action-chip"/)
  assert.match(positionSource, /class="[^"]*position-state-note[^"]*"/)
  assert.match(positionSource, /<span>当前命中规则<\/span>\s*<strong>\{\{\s*statePanel\.hero\.matched_rule_title\s*\}\}<\/strong>/)
  assert.match(positionSource, /<StatusChip variant="muted">\s*当前标的 <strong>\{\{\s*selectedSubjectSymbol/)
  assert.match(positionSource, /<StatusChip variant="muted">\s*当前页 <strong>\{\{\s*pagedDecisionRows\.length\s*\}\}<\/strong>/)
  assert.match(positionSource, /<StatusChip variant="muted">\s*默认分页 <strong>\{\{\s*decisionPagination\.pageSize\s*\}\} \/ 页<\/strong>/)
  assert.match(positionSource, /<StatusChip variant="muted">\s*当前页码 <strong>\{\{\s*decisionPagination\.page\s*\}\}<\/strong>/)
  assert.match(positionSource, /<StatusChip class="runtime-inline-status" :variant="ruleStatusChipVariant\(row\.allowed\)">/)
  assert.match(positionSource, /<StatusChip class="runtime-inline-status" :variant="decisionStatusChipVariant\(row\.tone\)">/)
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
  assert.match(positionSource, /<PositionSubjectOverviewPanel[\s\S]*class="position-subject-overview-host"/)
  assert.match(positionSource, /<WorkbenchLedgerPanel class="position-selection-panel">/)
  assert.match(positionSource, /<WorkbenchLedgerPanel class="position-decision-panel">/)
  assert.doesNotMatch(positionSource, /PositionReconciliationPanel/)
  assert.doesNotMatch(positionSource, /position-reconciliation-entry-panel/)
})

test('PositionManagement.vue is the sole workbench host for audit and order troubleshooting', () => {
  assert.match(positionSource, /import StatusChip from '\.\.\/components\/workbench\/StatusChip\.vue'/)
  assert.match(positionSource, /import WorkbenchPage from '\.\.\/components\/workbench\/WorkbenchPage\.vue'/)
  assert.match(positionSource, /import WorkbenchLedgerPanel from '\.\.\/components\/workbench\/WorkbenchLedgerPanel\.vue'/)
  assert.match(positionSource, /import WorkbenchDetailPanel from '\.\.\/components\/workbench\/WorkbenchDetailPanel\.vue'/)
  assert.match(positionSource, /<WorkbenchPage class="position-page">/)
  assert.match(positionSource, /<WorkbenchLedgerPanel class="position-selection-panel">/)
  assert.match(positionSource, /<WorkbenchDetailPanel class="position-state-panel">/)
  assert.match(positionSource, /<el-tab-pane name="overview" label="对账结果"/)
  assert.match(positionSource, /<el-tab-pane name="orders" label="相关订单"/)
  assert.match(positionSource, /<el-tab-pane name="ledger" label="持仓账本"/)
  assert.match(positionSource, /<el-tab-pane name="resolution" label="差异处理"/)
  assert.match(positionSource, /class="position-troubleshoot-tab-stack"/)
  assert.match(positionSource, /class="position-selection-panel__body"/)
  assert.doesNotMatch(positionSource, /reconciliation-ledger-workspace/)
  assert.doesNotMatch(positionSource, /reconciliation-ledger-side/)
})

test('PositionSubjectOverviewPanel.vue consumes shared workbench panel and status chip primitives for the dense selected-symbol overview table', () => {
  assert.match(positionSubjectOverviewSource, /import StatusChip from '\.\.\/workbench\/StatusChip\.vue'/)
  assert.match(positionSubjectOverviewSource, /import WorkbenchLedgerPanel from '\.\.\/workbench\/WorkbenchLedgerPanel\.vue'/)
  assert.match(positionSubjectOverviewSource, /<WorkbenchLedgerPanel class="position-subject-overview-panel">/)
  assert.match(positionSubjectOverviewSource, /defineEmits\(\['symbol-select'\]\)/)
  assert.match(positionSubjectOverviewSource, /highlight-current-row/)
  assert.match(positionSubjectOverviewSource, /label="持仓"/)
  assert.match(positionSubjectOverviewSource, /label="订单状态"/)
  assert.match(positionSubjectOverviewSource, /label="Guardian 层级触发"/)
  assert.match(positionSubjectOverviewSource, /label="止盈层级触发"/)
  assert.match(positionSubjectOverviewSource, /label="Guardian 买入层级"/)
  assert.match(positionSubjectOverviewSource, /label="止盈价格层级"/)
  assert.match(positionSubjectOverviewSource, /label="单标的仓位上限"/)
  assert.match(positionSubjectOverviewSource, /guardianLevelSummary/)
  assert.match(positionSubjectOverviewSource, /position-subject-trigger-line/)
  assert.match(positionSubjectOverviewSource, /label="保存"/)
  assert.match(positionSubjectOverviewSource, /<StatusChip variant="muted">\s*总标的 <strong>\{\{\s*overviewRows\.length\s*\}\}<\/strong>/)
  assert.match(positionSubjectOverviewSource, /<StatusChip variant="success">\s*已加载详情 <strong>\{\{\s*loadedDetailCount\s*\}\}<\/strong>/)
  assert.match(positionSubjectOverviewSource, /rgba\(245,\s*108,\s*108,\s*0\.12\)/)
  assert.doesNotMatch(positionSubjectOverviewSource, /label="止损价"/)
  assert.doesNotMatch(positionSubjectOverviewSource, /label="全仓止损价"/)
  assert.doesNotMatch(positionSubjectOverviewSource, /label="持仓股数"/)
  assert.doesNotMatch(positionSubjectOverviewSource, /label="持仓市值"/)
  assert.doesNotMatch(positionSubjectOverviewSource, /label="活跃单笔止损"/)
  assert.doesNotMatch(positionSubjectOverviewSource, /label="Open Entry"/)
  assert.doesNotMatch(positionSubjectOverviewSource, /label="门禁"/)
  assert.doesNotMatch(positionSubjectOverviewSource, /label="TPLS触发"/)
  assert.doesNotMatch(positionSubjectOverviewSource, /label="最近TPLS触发"/)
  assert.doesNotMatch(positionSubjectOverviewSource, /label="Guardian 层级买入"/)
  assert.doesNotMatch(positionSubjectOverviewSource, /label="Guardian层级触发"/)
  assert.doesNotMatch(positionSubjectOverviewSource, /label="止盈价格"/)
  assert.doesNotMatch(positionSubjectOverviewSource, /label="首笔买入金额"/)
  assert.doesNotMatch(positionSubjectOverviewSource, /label="默认买入金额"/)
  assert.doesNotMatch(positionSubjectOverviewSource, /position-subject-entry-card/)
})







test('DailyScreening.vue reuses StatusChip for the workbench pre-sync status', () => {
  assert.match(dailySource, /import StatusChip from '\.\.\/components\/workbench\/StatusChip\.vue'/)
  assert.match(dailySource, /<StatusChip variant="info">\{\{\s*preStatusLabel\(\)\s*\}\}<\/StatusChip>/)
  assert.match(dailySource, /<StatusChip :variant="gateStatus === 'passed' \? 'success' : 'warning'">/)
})

test('DailyScreening.vue consumes shared workbench page primitives and the three fundamental regions', () => {
  assert.match(dailySource, /import WorkbenchPage from ['"][^'"]*WorkbenchPage\.vue['"]/)
  assert.match(dailySource, /import ClxFundamentalRankingPanel from '\.\.\/components\/clx-workbench\/ClxFundamentalRankingPanel\.vue'/)
  assert.match(dailySource, /import ClxFundamentalDetailPanel from '\.\.\/components\/clx-workbench\/ClxFundamentalDetailPanel\.vue'/)
  assert.match(dailySource, /import ClxFundamentalStatsPanel from '\.\.\/components\/clx-workbench\/ClxFundamentalStatsPanel\.vue'/)
  assert.match(dailySource, /<WorkbenchPage class="clx-workbench-page">/)
  assert.match(dailySource, /class="clx-workbench-grid"/)
  assert.doesNotMatch(dailySource, /PoolWorkspacePanel/)
})

test('KlineSlim.vue reuses StatusChip for toolbar, overlay summaries and chanlun summary rows', () => {
  assert.match(klineSlimSource, /import StatusChip from '\.\.\/components\/workbench\/StatusChip\.vue'/)
  assert.match(klineSlimSource, /<StatusChip[\s\S]*variant="muted"[\s\S]*>\s*主图 \{\{\s*currentPeriod\s*\}\}/)
  assert.match(klineSlimSource, /<StatusChip[\s\S]*:variant="toolbarStatusChipVariant"/)
  assert.doesNotMatch(klineSlimSource, /<StatusChip[\s\S]*variant="muted"[\s\S]*>\s*当前止损/)
  assert.doesNotMatch(klineSlimSource, /<StatusChip[\s\S]*:variant="subjectPositionLimitChipVariant"/)
  assert.match(klineSlimSource, /<StatusChip[\s\S]*:variant="takeprofitRuntimeChipVariant"/)
  assert.doesNotMatch(klineSlimSource, /guardianRuntimeChipVariant/)
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

test('legacy chart routes that remain in code keep WorkbenchPage as the shared shell', () => {
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
  assert.match(systemSettingsSource, /import StatusChip from ['"][^'"]*StatusChip\.vue['"]/)
  assert.match(systemSettingsSource, /<WorkbenchPage class="system-settings-page system-settings-shell">/)
  assert.match(systemSettingsSource, /<WorkbenchToolbar class="settings-dense-toolbar">/)
  assert.match(systemSettingsSource, /<StatusChip class="settings-toolbar-chip settings-toolbar-chip--path" variant="info"/)
  assert.match(systemSettingsSource, /<StatusChip class="settings-inline-chip" :variant="sectionModeChipVariant\(section\)">/)
  assert.match(systemSettingsSource, /<StatusChip class="settings-inline-chip" :variant="restartModeChipVariant\(row\.restart_required\)">/)
  assert.match(systemSettingsSource, /<StatusChip class="settings-inline-chip is-source" variant="info"/)
  assert.match(systemSettingsSource, /<StatusChip class="settings-inline-chip" :variant="stateChipVariant\(row\)">/)
})

test('MyHeader.vue renders navigation from grouped metadata instead of hardcoded buttons', () => {
  assert.match(headerSource, /import \{[\s\S]*HEADER_NAV_GROUPS[\s\S]*HEADER_NAV_TARGETS[\s\S]*getHeaderNavTarget[\s\S]*\} from '@\/router\/pageMeta\.mjs'/)
  assert.match(headerSource, /headerNavGroups\(\)\s*\{\s*return HEADER_NAV_GROUPS\.map/)
  assert.match(headerSource, /const meta = HEADER_NAV_TARGETS\[key\] \|\| \{\}/)
  assert.match(headerSource, /<el-button-group v-for="\(\s*group,\s*groupIndex\s*\) in headerNavGroups"/)
  assert.match(headerSource, /<el-button\s+v-for="item in group"/)
  assert.match(headerSource, /this\.\$router\.push\(\{[\s\S]*path: target\.path,[\s\S]*query: target\.query/)
  assert.doesNotMatch(headerSource, /window\.open/)
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
