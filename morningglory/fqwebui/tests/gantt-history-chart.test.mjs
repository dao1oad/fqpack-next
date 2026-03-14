import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  getResetViewportWindow,
  getStreakColor,
  processSeriesWithStreaks
} from '../src/views/js/gantt-history-chart.mjs'

test('getStreakColor returns legacy palette entries', () => {
  assert.equal(getStreakColor(1, 1), '#ffd666')
  assert.equal(getStreakColor(4, 4), '#52c41a')
})

test('processSeriesWithStreaks appends color and streak metadata', () => {
  const result = processSeriesWithStreaks({
    dates: ['2026-03-05', '2026-03-06'],
    yAxisRaw: [{ id: 1, name: '机器人' }],
    seriesData: [
      [0, 0, 1, 5, 2, ['000001']],
      [1, 0, 1, 4, 1, ['000001']]
    ],
    level: 'plate'
  })

  assert.equal(result.seriesData[0][6], '#ffd666')
  assert.equal(result.seriesData[0][7], 1)
  assert.equal(result.seriesData[1][8], 2)
})

test('getResetViewportWindow keeps latest x-span and top y-span', () => {
  assert.deepEqual(
    getResetViewportWindow({ start: 30, end: 90 }, { start: 20, end: 60 }),
    { xStart: 40, xEnd: 100, yStart: 0, yEnd: 40 }
  )
})

test('getResetViewportWindow preserves exact small spans from the current viewport', () => {
  assert.deepEqual(
    getResetViewportWindow({ start: 94, end: 99 }, { start: 10, end: 18 }),
    { xStart: 95, xEnd: 100, yStart: 0, yEnd: 8 }
  )
})

test('GanttHistory restores legend and legacy hover config', async () => {
  const content = await readFile(
    new URL('../src/views/components/GanttHistory.vue', import.meta.url),
    'utf8'
  )

  assert.match(content, /class="color-legend"/)
  assert.match(content, /axisPointer:/)
  assert.match(content, /updateAxisPointer/)
  assert.match(content, /position: \(point, params, dom, rect, size\) =>/)
})

test('GanttHistory keeps stock drag-pan fallback and viewport-synced sidebar', async () => {
  const content = await readFile(
    new URL('../src/views/components/GanttHistory.vue', import.meta.url),
    'utf8'
  )

  assert.match(content, /const syncPlateSidebarFromChart = \(\) =>/)
  assert.match(content, /chartInstance\.on\('dataZoom'/)
  assert.match(content, /const handleStockPanMouseDown = \(evt\) =>/)
})

test('GanttHistory aligns the plate sidebar with chart grid padding', async () => {
  const content = await readFile(
    new URL('../src/views/components/GanttHistory.vue', import.meta.url),
    'utf8'
  )

  assert.match(content, /class="gantt-sidebar"/)
  assert.match(content, /paddingTop: `\$\{GRID_TOP\}px`/)
  assert.match(content, /paddingBottom: `\$\{GRID_BOTTOM\}px`/)
  assert.doesNotMatch(content, /class="sidebar-head"/)
})

test('GanttHistory fits sidebar rows to the visible chart window instead of clamping them to 24px', async () => {
  const content = await readFile(
    new URL('../src/views/components/GanttHistory.vue', import.meta.url),
    'utf8'
  )

  assert.match(content, /\.sidebar-list\s*\{[\s\S]*overflow-y:\s*auto;/)
  assert.match(content, /\.sidebar-list\s*\{[\s\S]*overflow-x:\s*hidden;/)
  assert.match(content, /minHeight: `\$\{sidebarRowHeight\}px`/)
  assert.match(content, /Math\.max\(1, usableHeight \/ visibleCount\)/)
  assert.doesNotMatch(content, /Math\.max\(24, usableHeight \/ visibleCount\)/)
  assert.doesNotMatch(content, /min-height:\s*24px;/)
})

test('Gantt pages use a viewport shell instead of stacking document-level 100vh blocks', async () => {
  const [platesPage, stocksPage] = await Promise.all([
    readFile(new URL('../src/views/GanttUnified.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/GanttUnifiedStocks.vue', import.meta.url), 'utf8')
  ])

  assert.doesNotMatch(platesPage, /\.gantt-page\s*\{[\s\S]*min-height:\s*100vh;/)
  assert.match(platesPage, /\.gantt-page\s*\{[\s\S]*overflow:\s*hidden;/)
  assert.match(platesPage, /\.gantt-page-body\s*\{[\s\S]*min-height:\s*0;/)

  assert.doesNotMatch(stocksPage, /\.gantt-page\s*\{[\s\S]*min-height:\s*100vh;/)
  assert.match(stocksPage, /\.gantt-page\s*\{[\s\S]*overflow:\s*hidden;/)
  assert.match(stocksPage, /\.gantt-page-body\s*\{[\s\S]*min-height:\s*0;/)
})

test('GanttHistory consumes parent height instead of recalculating viewport height', async () => {
  const content = await readFile(
    new URL('../src/views/components/GanttHistory.vue', import.meta.url),
    'utf8'
  )

  assert.doesNotMatch(content, /calc\(100vh - /)
  assert.match(content, /\.gantt-history\s*\{[\s\S]*min-height:\s*0;/)
  assert.match(content, /\.gantt-chart\s*\{[\s\S]*min-height:\s*0;/)
})
