import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildKlineSlimChartOption,
  buildKlineSlimChartScene,
  STRUCTURE_LINE_WIDTH_PX,
} from './kline-slim-chart-renderer.mjs'

test('structure stroke width is fixed at the white line width', () => {
  assert.equal(STRUCTURE_LINE_WIDTH_PX, 1.2)
})

test('all structure lines and box borders share the same fixed width', () => {
  const scene = buildKlineSlimChartScene({
    mainData: {
      symbol: '600000',
      date: ['2026-03-16 09:30:00', '2026-03-16 10:00:00', '2026-03-16 10:30:00'],
      open: [10, 10.1, 10.2],
      close: [10.1, 10.2, 10.3],
      low: [9.9, 10.0, 10.1],
      high: [10.2, 10.3, 10.4],
      bidata: {
        date: ['2026-03-16 09:30:00', '2026-03-16 10:00:00'],
        data: [10, 10.2]
      },
      duandata: {
        date: ['2026-03-16 09:30:00', '2026-03-16 10:30:00'],
        data: [10, 10.4]
      },
      higherDuanData: {
        date: ['2026-03-16 09:30:00', '2026-03-16 10:30:00'],
        data: [9.9, 10.4]
      },
      zsdata: [[['2026-03-16 09:30:00', 10.15], ['2026-03-16 10:00:00', 10.0]]],
      duan_zsdata: [[['2026-03-16 09:30:00', 10.2], ['2026-03-16 10:00:00', 10.05]]],
      higher_duan_zsdata: [[['2026-03-16 09:30:00', 10.25], ['2026-03-16 10:00:00', 10.1]]],
    },
    currentPeriod: '30m',
  })

  const periodScene = scene.periodScenes.find((item) => item.period === '30m')
  const bi = periodScene.lineSeries.find((item) => item.name === '30m 笔')
  const duan = periodScene.lineSeries.find((item) => item.name === '30m 段')
  const higher = periodScene.lineSeries.find((item) => item.name === '30m 高级别段')
  const biBox = periodScene.structureSeries.find((item) => item.name === '30m 笔结构')
  const duanBox = periodScene.structureSeries.find((item) => item.name === '30m 段结构')
  const higherBox = periodScene.structureSeries.find((item) => item.name === '30m 高级段结构')

  assert.equal(bi.width, STRUCTURE_LINE_WIDTH_PX)
  assert.equal(duan.width, STRUCTURE_LINE_WIDTH_PX)
  assert.equal(higher.width, STRUCTURE_LINE_WIDTH_PX)
  assert.equal(biBox.borderWidth, STRUCTURE_LINE_WIDTH_PX)
  assert.equal(duanBox.borderWidth, STRUCTURE_LINE_WIDTH_PX)
  assert.equal(higherBox.borderWidth, STRUCTURE_LINE_WIDTH_PX)

  const option = buildKlineSlimChartOption({ scene })
  const optionBiBox = option.series.find((item) => item.name === '30m 笔结构')
  assert.equal(optionBiBox.customMeta.borderWidth, STRUCTURE_LINE_WIDTH_PX)
})
