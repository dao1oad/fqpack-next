import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const readSource = (relativePath) => {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8').replace(/\r/g, '')
}

const appSource = readSource('../App.vue')
const workbenchDensitySource = readSource('../style/workbench-density.css')
const runtimeSource = readSource('./RuntimeObservability.vue')
const orderSource = readSource('./OrderManagement.vue')
const subjectSource = readSource('./SubjectManagement.vue')
const tpslSource = readSource('./TpslManagement.vue')
const dailySource = readSource('./DailyScreening.vue')
const shoubanSource = readSource('./GanttShouban30Phase1.vue')
const ganttSource = readSource('./GanttUnified.vue')
const ganttStocksSource = readSource('./GanttUnifiedStocks.vue')

test('app shell and workbench base keep browser-level scrolling available', () => {
  assert.doesNotMatch(appSource, /html,\s*body,\s*#app\s*\{[\s\S]*overflow:\s*hidden;/)
  assert.match(appSource, /body\s*\{[\s\S]*overflow-y:\s*auto;/)
  assert.match(appSource, /body\s*\{[\s\S]*overflow-x:\s*auto;/)
  assert.match(workbenchDensitySource, /\.workbench-page \{[\s\S]*min-height:\s*100vh;[\s\S]*min-height:\s*100dvh;/)
  assert.doesNotMatch(workbenchDensitySource, /\.workbench-page \{[\s\S]*\n\s+height:\s*100vh;/)
  assert.match(workbenchDensitySource, /\.workbench-body \{[\s\S]*overflow:\s*auto;/)
})

test('runtime, order, subject, tpsl and daily pages stop clipping the viewport and add earlier responsive fallbacks', () => {
  assert.doesNotMatch(runtimeSource, /\.runtime-page \{[^}]*\n\s+height:\s*100vh;[^}]*overflow:\s*hidden;/)
  assert.doesNotMatch(runtimeSource, /\.runtime-shell \{[^}]*overflow:\s*hidden;/)
  assert.match(runtimeSource, /\.runtime-time-range \{[^}]*width:\s*min\(100%,\s*340px\);[^}]*min-width:\s*0;/)
  assert.match(runtimeSource, /\.runtime-browse-layout \{[^}]*overflow:\s*auto;/)
  assert.match(runtimeSource, /@media \(max-width:\s*1600px\)/)

  assert.match(orderSource, /\.order-body \{[^}]*overflow:\s*auto;/)
  assert.match(subjectSource, /\.subject-management-body \{[^}]*overflow:\s*auto;/)
  assert.doesNotMatch(subjectSource, /\.subject-layout \{[^}]*min-height:\s*calc\(100vh - 228px\);/)
  assert.match(subjectSource, /@media \(max-width:\s*1500px\)/)

  assert.match(tpslSource, /\.tpsl-body \{[^}]*overflow:\s*auto;/)
  assert.doesNotMatch(tpslSource, /\.tpsl-layout \{[^}]*overflow:\s*hidden;/)

  assert.doesNotMatch(dailySource, /\.daily-screening-grid \{[^}]*overflow:\s*hidden;/)
  assert.match(dailySource, /@media \(max-width:\s*1440px\)/)
})

test('gantt pages use min-height shells and scrollable bodies instead of fixed viewport clipping', () => {
  assert.match(shoubanSource, /\.shouban30-page \{[\s\S]*min-height:\s*100vh;[\s\S]*min-height:\s*100dvh;/)
  assert.doesNotMatch(shoubanSource, /\.shouban30-page \{[\s\S]*\n\s+height:\s*100vh;/)
  assert.match(shoubanSource, /\.shouban30-page-body \{[\s\S]*overflow:\s*auto;/)
  assert.match(shoubanSource, /@media \(max-width:\s*1520px\)/)

  assert.match(ganttSource, /\.gantt-page \{[\s\S]*min-height:\s*100vh;[\s\S]*min-height:\s*100dvh;/)
  assert.doesNotMatch(ganttSource, /\.gantt-page \{[\s\S]*\n\s+height:\s*100vh;/)
  assert.match(ganttSource, /\.gantt-page-content \{[\s\S]*overflow:\s*auto;/)

  assert.match(ganttStocksSource, /\.gantt-page \{[\s\S]*min-height:\s*100vh;[\s\S]*min-height:\s*100dvh;/)
  assert.doesNotMatch(ganttStocksSource, /\.gantt-page \{[\s\S]*\n\s+height:\s*100vh;/)
  assert.match(ganttStocksSource, /\.gantt-page-content \{[\s\S]*overflow:\s*auto;/)
})
