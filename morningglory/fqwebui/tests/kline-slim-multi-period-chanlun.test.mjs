import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  SUPPORTED_CHANLUN_PERIODS,
  DEFAULT_MAIN_PERIOD,
  DEFAULT_VISIBLE_CHANLUN_PERIODS,
  PERIOD_STYLE_MAP,
  PERIOD_WIDTH_FACTOR,
  PERIOD_DURATION_MS,
  buildPeriodLegendSelectionState,
  getVisibleChanlunPeriods,
  getRealtimeRefreshPeriods
} from '../src/views/js/kline-slim-chanlun-periods.mjs'

test('supported periods stay within redis producer periods and default to 5m main chart', () => {
  assert.deepEqual(SUPPORTED_CHANLUN_PERIODS, ['1m', '5m', '15m', '30m', '1d'])
  assert.equal(DEFAULT_MAIN_PERIOD, '5m')
  assert.deepEqual(DEFAULT_VISIBLE_CHANLUN_PERIODS, [])
})

test('period style map and duration map stay aligned with current multi-period renderer', () => {
  assert.equal(PERIOD_STYLE_MAP['1m'].bi, '#ffffff')
  assert.equal(PERIOD_STYLE_MAP['5m'].duan, '#3b82f6')
  assert.equal(PERIOD_STYLE_MAP['15m'].higherDuan, '#ef4444')
  assert.equal(PERIOD_STYLE_MAP['30m'].higherDuanZhongshu, '#22c55e')
  assert.equal(PERIOD_STYLE_MAP['1d'].higherDuanZhongshu, '#a855f7')
  assert.deepEqual(PERIOD_WIDTH_FACTOR, { '1m': 1, '5m': 3, '15m': 4, '30m': 5, '1d': 7 })
  assert.deepEqual(PERIOD_DURATION_MS, {
    '1m': 60 * 1000,
    '5m': 5 * 60 * 1000,
    '15m': 15 * 60 * 1000,
    '30m': 30 * 60 * 1000,
    '1d': 24 * 60 * 60 * 1000
  })
})

test('legend selection includes current main period while visible extras still exclude it', () => {
  assert.deepEqual(
    buildPeriodLegendSelectionState({
      currentPeriod: '5m'
    }),
    {
      '1m': false,
      '5m': true,
      '15m': false,
      '30m': false,
      '1d': false
    }
  )

  assert.deepEqual(
    buildPeriodLegendSelectionState({
      currentPeriod: '15m',
      previousSelected: {
        '1m': true,
        '5m': false,
        '15m': true,
        '30m': true,
        中枢: true,
        段中枢: false
      }
    }),
    {
      '1m': true,
      '5m': false,
      '15m': true,
      '30m': true,
      '1d': false
    }
  )

  assert.deepEqual(
    getVisibleChanlunPeriods({
      currentPeriod: '15m',
      selected: {
        '1m': true,
        '5m': false,
        '15m': true,
        '30m': true
      }
    }),
    ['1m', '30m']
  )
})

test('realtime refresh periods keep current period first and append visible extras without duplicates', () => {
  assert.deepEqual(
    getRealtimeRefreshPeriods({
      currentPeriod: '5m',
      visiblePeriods: ['30m', '1m', '30m']
    }),
    ['5m', '1m', '30m']
  )
})

test('kline-slim controller imports new chart renderer/controller and removes legacy draw-slim state machine', async () => {
  const scriptContent = await readFile(new URL('../src/views/js/kline-slim.js', import.meta.url), 'utf8')
  const controllerContent = await readFile(new URL('../src/views/klineSlimController.mjs', import.meta.url), 'utf8')

  assert.match(scriptContent, /createKlineSlimChartController/)
  assert.match(scriptContent, /chartController/)
  assert.match(scriptContent, /periodLegendSelected/)
  assert.match(scriptContent, /resetViewportOnNextRender/)
  assert.match(controllerContent, /buildKlineSlimChartScene/)
  assert.doesNotMatch(`${scriptContent}\n${controllerContent}`, /import drawSlim/)
  assert.doesNotMatch(`${scriptContent}\n${controllerContent}`, /lastStructuralRouteKey/)
  assert.doesNotMatch(`${scriptContent}\n${controllerContent}`, /handleSlimLegendSelectChanged/)
})

test('kline-slim controller schedules scene rendering through chartController instead of draw-slim', async () => {
  const content = await readFile(new URL('../src/views/klineSlimController.mjs', import.meta.url), 'utf8')
  const scheduleRenderSection = content
    .split('scheduleRender() {')[1]
    ?.split('applySymbol() {')[0]

  assert.ok(scheduleRenderSection, 'expected scheduleRender section in controller')
  assert.match(scheduleRenderSection, /const scene = buildKlineSlimChartScene\(/)
  assert.match(scheduleRenderSection, /this\.chartController\.applyScene\(scene, \{/)
  assert.match(scheduleRenderSection, /resetViewport: this\.resetViewportOnNextRender/)
  assert.match(scheduleRenderSection, /this\.chartViewport = this\.chartController\.getViewport\(\)/)
  assert.doesNotMatch(scheduleRenderSection, /drawSlim\(/)
})

test('initChart creates chart controller and browser hooks publish the controller for regression tests', async () => {
  const scriptContent = await readFile(new URL('../src/views/js/kline-slim.js', import.meta.url), 'utf8')
  const controllerContent = await readFile(new URL('../src/views/klineSlimController.mjs', import.meta.url), 'utf8')

  assert.match(scriptContent, /this\.chartController = createKlineSlimChartController\(/)
  assert.match(scriptContent, /window\.__klineSlimChartController = this\.chartController \|\| null/)
  assert.match(controllerContent, /this\.chartController\.dispose\(\)/)
})

test('KlineSlim keeps extra-period legend guidance and removes fixed overlay copy', async () => {
  const content = await readFile(new URL('../src/views/KlineSlim.vue', import.meta.url), 'utf8')

  assert.match(content, /图例控制主图缠论层与额外周期叠加/)
  assert.doesNotMatch(content, /固定叠加/)
})
