import assert from 'node:assert/strict'
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
