import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  SUPPORTED_CHANLUN_PERIODS,
  DEFAULT_MAIN_PERIOD,
  DEFAULT_VISIBLE_CHANLUN_PERIODS,
  PERIOD_STYLE_MAP,
  PERIOD_WIDTH_FACTOR,
  buildLegendSelectionState,
  getRealtimeRefreshPeriods
} from '../src/views/js/kline-slim-chanlun-periods.mjs'

test('supported periods stay within redis producer periods and default to 5m', () => {
  assert.deepEqual(SUPPORTED_CHANLUN_PERIODS, ['1m', '5m', '15m', '30m'])
  assert.equal(DEFAULT_MAIN_PERIOD, '5m')
  assert.deepEqual(DEFAULT_VISIBLE_CHANLUN_PERIODS, ['5m'])
})

test('period style map matches legacy color families and width factors', () => {
  assert.equal(PERIOD_STYLE_MAP['1m'].bi, '#ffffff')
  assert.equal(PERIOD_STYLE_MAP['5m'].duan, '#3b82f6')
  assert.equal(PERIOD_STYLE_MAP['15m'].higherDuan, '#ef4444')
  assert.equal(PERIOD_STYLE_MAP['30m'].duanZhongshu, '#ef4444')
  assert.deepEqual(PERIOD_WIDTH_FACTOR, { '1m': 1, '5m': 3, '15m': 4, '30m': 5 })
})

test('legend selection defaults to only 5m plus enabled zhongshu groups', () => {
  assert.deepEqual(buildLegendSelectionState(), {
    '1m': false,
    '5m': true,
    '15m': false,
    '30m': false,
    '中枢': true,
    '段中枢': true
  })
})

test('realtime refresh periods keep current period first and visible extras unique', () => {
  assert.deepEqual(
    getRealtimeRefreshPeriods({
      currentPeriod: '5m',
      visiblePeriods: ['30m', '1m', '5m', '30m']
    }),
    ['5m', '1m', '30m']
  )
})

test('kline-slim controller uses multi-period chanlun state instead of fixed overlay', async () => {
  const content = await readFile(new URL('../src/views/js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(content, /chanlunMultiData/)
  assert.match(content, /visibleChanlunPeriods/)
  assert.match(content, /loadedChanlunPeriods/)
  assert.match(content, /chanlunPeriodLoading/)
  assert.match(content, /ensureChanlunPeriodLoaded/)
  assert.match(content, /handleSlimLegendSelectChanged/)
  assert.match(content, /refreshVisibleChanlunPeriods/)
  assert.doesNotMatch(content, /overlayData/)
  assert.doesNotMatch(content, /overlayTimer/)
  assert.doesNotMatch(content, /OVERLAY_PERIOD/)
})

test('draw-slim consumes all multi-period chanlun layer fields and global zhongshu legends', async () => {
  const content = await readFile(new URL('../src/views/js/draw-slim.js', import.meta.url), 'utf8')

  assert.match(content, /higherDuanData/)
  assert.match(content, /duan_zsdata/)
  assert.match(content, /higher_duan_zsdata/)
  assert.match(content, /PERIOD_STYLE_MAP/)
  assert.match(content, /PERIOD_WIDTH_FACTOR/)
  assert.match(content, /'中枢'/)
  assert.match(content, /'段中枢'/)
  assert.match(content, /markArea/)
})
