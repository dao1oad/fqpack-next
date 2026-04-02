import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const readSource = (relativePath) => (
  readFileSync(new URL(relativePath, import.meta.url), 'utf8').replace(/\r/g, '')
)

const dailySource = readSource('./DailyScreening.vue')
const orderSource = readSource('./OrderManagement.vue')
const positionSource = readSource('./PositionManagement.vue')
const positionReconciliationSource = readSource('../components/position-management/PositionReconciliationPanel.vue')
const positionSubjectOverviewSource = readSource('../components/position-management/PositionSubjectOverviewPanel.vue')
const subjectSource = readSource('./SubjectManagement.vue')
const runtimeSource = readSource('./RuntimeObservability.vue')
const systemSettingsSource = readSource('./SystemSettings.vue')
const tpslSource = readSource('./TpslManagement.vue')
const shoubanSource = readSource('./GanttShouban30Phase1.vue')
const ganttSource = readSource('./GanttUnified.vue')
const ganttStocksSource = readSource('./GanttUnifiedStocks.vue')

test('daily screening keeps the page shell fixed and scrolls inside filter and result regions', () => {
  assert.match(dailySource, /\.daily-screening-page \{[\s\S]*height:\s*100vh;[\s\S]*height:\s*100dvh;[\s\S]*overflow:\s*hidden;/)
  assert.match(dailySource, /\.daily-screening-body \{[\s\S]*overflow:\s*hidden;/)
  assert.match(dailySource, /\.daily-screening-grid \{[\s\S]*overflow:\s*hidden;/)
  assert.match(dailySource, /\.daily-filter-panel \{[\s\S]*overflow-y:\s*auto;/)
  assert.match(dailySource, /\.daily-results-content \{[\s\S]*overflow:\s*hidden;/)
})

test('order, position, subject, tpsl and runtime pages no longer use page-level scrolling at desktop widths', () => {
  assert.match(orderSource, /\.order-body \{[\s\S]*overflow:\s*hidden;/)
  assert.match(orderSource, /\.order-main-grid \{[\s\S]*overflow:\s*hidden;/)
  assert.match(orderSource, /\.order-detail-grid \{[\s\S]*overflow:\s*auto;/)

  assert.match(positionSource, /\.position-body \{[\s\S]*overflow:\s*hidden;/)
  assert.match(positionSource, /\.position-workbench-column--left,[\s\S]*\.position-workbench-column--right \{[\s\S]*min-height:\s*0;[\s\S]*overflow:\s*hidden;/)
  assert.match(positionSource, /\.position-decision-panel \{[\s\S]*overflow:\s*hidden;/)
  assert.match(positionSource, /\.position-selection-panel \{[\s\S]*overflow:\s*hidden;/)
  assert.match(positionSource, /\.position-panel-body \{[\s\S]*overflow:\s*hidden;/)
  assert.match(positionSource, /\.position-state-scroll \{[\s\S]*overflow-y:\s*auto;[\s\S]*overflow-x:\s*hidden;/)
  assert.match(positionSource, /\.position-reconciliation-panel,[\s\S]*\.position-subject-overview-host,[\s\S]*\.position-selection-panel,[\s\S]*\.position-decision-panel \{[\s\S]*overflow:\s*hidden;/)
  assert.match(positionReconciliationSource, /\.position-reconciliation-ledger \{[\s\S]*overflow:\s*auto;/)
  assert.match(positionSubjectOverviewSource, /\.position-subject-overview-panel \{[\s\S]*overflow:\s*hidden;/)
  assert.match(positionSubjectOverviewSource, /\.position-subject-table-wrap \{[\s\S]*overflow:\s*hidden;/)
  assert.match(positionSubjectOverviewSource, /<el-table[\s\S]*height="100%"/)

  assert.match(subjectSource, /\.subject-management-page \{[\s\S]*height:\s*100vh;[\s\S]*height:\s*100dvh;[\s\S]*overflow:\s*hidden;/)
  assert.doesNotMatch(subjectSource, /\.subject-management-page \{[\s\S]*max-height:\s*100dvh;/)
  assert.match(subjectSource, /\.subject-management-body \{[\s\S]*overflow:\s*hidden;/)
  assert.match(subjectSource, /\.subject-editor-stack \{[\s\S]*overflow:\s*auto;/)

  assert.match(tpslSource, /\.tpsl-body \{[\s\S]*overflow:\s*hidden;/)
  assert.match(tpslSource, /\.tpsl-layout \{[\s\S]*overflow:\s*hidden;/)
  assert.match(tpslSource, /\.tpsl-main-stack \{[\s\S]*overflow:\s*auto;/)

  assert.match(runtimeSource, /\.runtime-shell \{[\s\S]*overflow:\s*hidden;/)
  assert.match(runtimeSource, /\.runtime-browse-layout \{[\s\S]*overflow:\s*hidden;/)
  assert.match(runtimeSource, /\.runtime-browser-panel--detail \{[\s\S]*overflow:\s*hidden;/)
})

test('system settings keeps the hero visible and scrolls inside editor and side panes', () => {
  assert.match(systemSettingsSource, /\.system-settings-page[\s\S]*height 100vh[\s\S]*height 100dvh[\s\S]*overflow hidden/)
  assert.match(systemSettingsSource, /\.settings-shell[\s\S]*overflow hidden/)
  assert.match(systemSettingsSource, /\.settings-dense-columns[\s\S]*overflow hidden/)
  assert.match(systemSettingsSource, /\.settings-dense-column[\s\S]*overflow auto/)
  assert.match(systemSettingsSource, /\.settings-ledger[\s\S]*overflow hidden/)
})

test('gantt routes use fixed viewport pages and keep scrolling inside content panes', () => {
  assert.match(shoubanSource, /\.shouban30-page \{[\s\S]*height:\s*100vh;[\s\S]*height:\s*100dvh;[\s\S]*overflow:\s*hidden;/)
  assert.match(shoubanSource, /\.shouban30-page-body \{[\s\S]*overflow:\s*hidden;/)
  assert.match(shoubanSource, /\.shouban30-grid \{[\s\S]*overflow:\s*hidden;/)

  assert.match(ganttSource, /<WorkbenchPage class="gantt-page">/)
  assert.match(ganttSource, /<div class="workbench-body gantt-page-body">/)
  assert.match(ganttSource, /\.gantt-page-content \{[\s\S]*overflow:\s*auto;/)

  assert.match(ganttStocksSource, /<WorkbenchPage class="gantt-page">/)
  assert.match(ganttStocksSource, /<div class="workbench-body gantt-page-body">/)
  assert.match(ganttStocksSource, /\.gantt-page-content \{[\s\S]*overflow:\s*auto;/)
})
