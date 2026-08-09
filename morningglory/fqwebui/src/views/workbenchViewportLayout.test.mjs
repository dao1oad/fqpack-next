import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const readSource = (relativePath) => (
  readFileSync(new URL(relativePath, import.meta.url), 'utf8').replace(/\r/g, '')
)

const dailySource = readSource('./DailyScreening.vue')
const orderSource = readSource('./OrderManagement.vue')
const positionSource = readSource('./PositionManagement.vue')
const positionSubjectOverviewSource = readSource('../components/position-management/PositionSubjectOverviewPanel.vue')
const subjectSource = readSource('./SubjectManagement.vue')
const runtimeSource = readSource('./RuntimeObservability.vue')
const systemSettingsSource = readSource('./SystemSettings.vue')
const ganttSource = readSource('./GanttUnified.vue')
const ganttStocksSource = readSource('./GanttUnifiedStocks.vue')

test('daily screening workbench keeps the page shell fixed and scrolls only inside panels', () => {
  assert.match(dailySource, /\.clx-workbench-page \{[\s\S]*height:\s*100dvh;[\s\S]*overflow:\s*hidden;/)
  assert.match(dailySource, /\.clx-workbench-body \{[\s\S]*overflow:\s*hidden;/)
  assert.match(dailySource, /\.clx-workbench-grid \{[\s\S]*grid-template-columns:[\s\S]*minmax\(760px,\s*30fr\)[\s\S]*minmax\(1100px,\s*46fr\)[\s\S]*minmax\(560px,\s*24fr\);[\s\S]*min-height:\s*0;[\s\S]*overflow:\s*hidden;/)
})

test('order, position, subject, reconciliation and runtime pages no longer use page-level scrolling at desktop widths', () => {
  assert.match(orderSource, /\.order-body \{[\s\S]*overflow:\s*hidden;/)
  assert.match(orderSource, /\.order-main-grid \{[\s\S]*overflow:\s*hidden;/)
  assert.match(orderSource, /\.order-detail-grid \{[\s\S]*overflow:\s*auto;/)

  assert.match(positionSource, /\.position-body \{[\s\S]*overflow:\s*hidden;/)
  assert.match(positionSource, /\.position-workbench-column--left \{[\s\S]*grid-template-rows:\s*auto\s+minmax\(0,\s*1fr\);[\s\S]*overflow:\s*hidden;/)
  assert.match(positionSource, /\.position-workbench-column--right \{[\s\S]*grid-template-rows:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);[\s\S]*overflow:\s*hidden;/)
  assert.match(positionSource, /\.position-state-panel,[\s\S]*\.position-subject-overview-host,[\s\S]*\.position-selection-panel,[\s\S]*\.position-decision-panel \{[\s\S]*overflow:\s*hidden;/)
  assert.match(positionSource, /\.position-panel-body \{[\s\S]*overflow:\s*hidden;/)
  assert.doesNotMatch(positionSource, /\.position-state-scroll \{[\s\S]*overflow-y:\s*auto;[\s\S]*overflow-x:\s*hidden;/)
  assert.match(positionSubjectOverviewSource, /\.position-subject-overview-panel \{[\s\S]*overflow:\s*hidden;/)
  assert.match(positionSubjectOverviewSource, /\.position-subject-table-wrap \{[\s\S]*overflow:\s*hidden;/)
  assert.match(positionSubjectOverviewSource, /<el-table[\s\S]*height="100%"/)

  assert.match(subjectSource, /\.subject-management-page \{[\s\S]*height:\s*100vh;[\s\S]*height:\s*100dvh;[\s\S]*overflow:\s*hidden;/)
  assert.doesNotMatch(subjectSource, /\.subject-management-page \{[\s\S]*max-height:\s*100dvh;/)
  assert.match(subjectSource, /\.subject-management-body \{[\s\S]*overflow:\s*hidden;/)
  assert.match(subjectSource, /\.subject-editor-stack \{[\s\S]*overflow:\s*auto;/)

  assert.match(runtimeSource, /\.runtime-shell \{[\s\S]*overflow:\s*hidden;/)
  assert.match(runtimeSource, /\.runtime-browse-layout \{[\s\S]*overflow:\s*hidden;/)
  assert.match(runtimeSource, /\.runtime-browser-panel--detail \{[\s\S]*overflow:\s*hidden;/)

  assert.match(positionSource, /\.position-workbench-grid \{[\s\S]*grid-template-columns:\s*minmax\(0,[\s\S]*overflow:\s*hidden;/)
  assert.match(positionSource, /\.position-selection-tabs :deep\(\.el-tabs__content\) \{[\s\S]*overflow:\s*hidden;/)
  assert.match(positionSource, /\.position-selection-panel__body \{[\s\S]*grid-template-rows:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);[\s\S]*min-height:\s*0;/)
  assert.match(positionSource, /\.position-troubleshoot-tab-stack \{[\s\S]*overflow:\s*hidden;/)
  assert.match(positionSource, /\.position-troubleshoot-scroll \{[\s\S]*overflow-y:\s*auto;[\s\S]*overflow-x:\s*hidden;/)
  assert.match(positionSource, /\.position-selection-table-wrap--dense \{[\s\S]*overflow-y:\s*auto;[\s\S]*overflow-x:\s*hidden;/)
})

test('system settings keeps the hero visible and scrolls inside editor and side panes', () => {
  assert.match(systemSettingsSource, /\.system-settings-page[\s\S]*height 100vh[\s\S]*height 100dvh[\s\S]*overflow hidden/)
  assert.match(systemSettingsSource, /\.settings-shell[\s\S]*overflow hidden/)
  assert.match(systemSettingsSource, /\.settings-dense-columns[\s\S]*overflow hidden/)
  assert.match(systemSettingsSource, /\.settings-dense-column[\s\S]*overflow auto/)
  assert.match(systemSettingsSource, /\.settings-ledger[\s\S]*overflow hidden/)
})

test('gantt routes use fixed viewport pages and keep scrolling inside content panes', () => {
  assert.match(ganttSource, /<WorkbenchPage class="gantt-page">/)
  assert.match(ganttSource, /<div class="workbench-body gantt-page-body">/)
  assert.match(ganttSource, /\.gantt-page-content \{[\s\S]*overflow:\s*auto;/)

  assert.match(ganttStocksSource, /<WorkbenchPage class="gantt-page">/)
  assert.match(ganttStocksSource, /<div class="workbench-body gantt-page-body">/)
  assert.match(ganttStocksSource, /\.gantt-page-content \{[\s\S]*overflow:\s*auto;/)
})
