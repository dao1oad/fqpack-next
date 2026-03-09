import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  filterExcludedPlates,
  getSegmentGainMultiple,
  passesDefaultChanlunFilter,
} from './shouban30ChanlunFilter.mjs'

const pageSource = readFileSync(new URL('./GanttShouban30Phase1.vue', import.meta.url), 'utf8')

test('filters excluded plate names', () => {
  const rows = filterExcludedPlates([
    { plate_name: '机器人' },
    { plate_name: '其他' },
    { plate_name: '公告' },
    { plate_name: 'ST股' },
    { plate_name: 'ST板块' },
    { plate_name: '芯片' },
  ])

  assert.deepEqual(rows, [
    { plate_name: '机器人' },
    { plate_name: '芯片' },
  ])
})

test('computes price multiple from segment prices', () => {
  assert.equal(
    getSegmentGainMultiple({ start_price: 10, end_price: 29.95 }),
    2.995,
  )
  assert.equal(getSegmentGainMultiple({ start_price: 0, end_price: 10 }), null)
  assert.equal(getSegmentGainMultiple({ start_price: null, end_price: 10 }), null)
})

test('passes default 30m chanlun filter only when higher segment, segment, bi all satisfy limits', () => {
  assert.deepEqual(
    passesDefaultChanlunFilter({
      ok: true,
      structure: {
        higher_segment: { start_price: 10, end_price: 29.9 },
        segment: { start_price: 8, end_price: 23.6 },
        bi: { price_change_pct: 29.8 },
      },
    }),
    {
      passed: true,
      higher_multiple: 2.99,
      segment_multiple: 2.95,
      bi_gain_percent: 29.8,
      reason: 'passed',
    },
  )

  assert.equal(
    passesDefaultChanlunFilter({
      ok: true,
      structure: {
        higher_segment: { start_price: 10, end_price: 30.1 },
        segment: { start_price: 8, end_price: 23.6 },
        bi: { price_change_pct: 29.8 },
      },
    }).reason,
    'higher_multiple_exceed',
  )
  assert.equal(
    passesDefaultChanlunFilter({
      ok: true,
      structure: {
        higher_segment: { start_price: 10, end_price: 29.9 },
        segment: { start_price: 8, end_price: 24.4 },
        bi: { price_change_pct: 29.8 },
      },
    }).reason,
    'segment_multiple_exceed',
  )
  assert.equal(
    passesDefaultChanlunFilter({
      ok: true,
      structure: {
        higher_segment: { start_price: 10, end_price: 29.9 },
        segment: { start_price: 8, end_price: 23.6 },
        bi: { price_change_pct: 30.1 },
      },
    }).reason,
    'bi_gain_exceed',
  )
})

test('treats missing structure or failed response as not passed', () => {
  assert.deepEqual(
    passesDefaultChanlunFilter({ ok: false, structure: {} }),
    {
      passed: false,
      higher_multiple: null,
      segment_multiple: null,
      bi_gain_percent: null,
      reason: 'structure_unavailable',
    },
  )

  assert.equal(
    passesDefaultChanlunFilter({
      ok: true,
      structure: {
        higher_segment: { start_price: 10, end_price: 20 },
        segment: {},
        bi: { price_change_pct: 10 },
      },
    }).reason,
    'segment_multiple_unavailable',
  )
})

test('page no longer calculates chanlun structures on the client', () => {
  assert.doesNotMatch(pageSource, /getChanlunStructure/)
  assert.doesNotMatch(pageSource, /chanlunStructureCache/)
  assert.doesNotMatch(pageSource, /chanlunRequestId/)
  assert.doesNotMatch(pageSource, /loadChanlunStructures/)
  assert.doesNotMatch(pageSource, /filterExcludedPlates/)
})

test('page binds to postclose chanlun snapshot presentation', () => {
  assert.match(pageSource, /const plateCountLabel = computed\(\(\) => '通过数'\)/)
  assert.match(pageSource, /label="高级段倍数"/)
  assert.match(pageSource, /label="段倍数"/)
  assert.match(pageSource, /label="笔涨幅%"/)
  assert.match(pageSource, /currentChanlunStats/)
  assert.match(pageSource, /原始候选/)
  assert.match(pageSource, /缠论通过/)
  assert.match(pageSource, /未通过\/不可用/)
  assert.match(pageSource, /首板缠论快照未构建完成/)
})

test('page no longer uses default overflow tooltip for reason columns and uses reason popover component', () => {
  assert.match(pageSource, /Shouban30ReasonPopover/)
  assert.doesNotMatch(pageSource, /<el-table-column prop="reason_text" label="板块理由"[^>]*show-overflow-tooltip/)
  assert.doesNotMatch(pageSource, /<el-table-column prop="latest_reason" label="最近理由"[^>]*show-overflow-tooltip/)
  assert.doesNotMatch(pageSource, /<el-table-column label="理由"[^>]*show-overflow-tooltip/)
})

test('page wires extra stock filters through helper-based intersection filtering', () => {
  assert.match(pageSource, /EXTRA_FILTER_OPTIONS/)
  assert.match(pageSource, /selectedExtraFilterKeys/)
  assert.match(pageSource, /toggleExtraFilterSelection/)
  assert.match(pageSource, /filterStockRowsByPlate/)
  assert.match(pageSource, /rebuildPlatesFromFilteredStocks/)
  assert.match(pageSource, /option\.label/)
  assert.match(pageSource, /当前筛选条件下暂无标的/)
})
