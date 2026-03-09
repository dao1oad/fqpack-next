import test from 'node:test'
import assert from 'node:assert/strict'

import {
  CHANLUN_EXCLUDED_PLATE_NAMES,
  filterExcludedPlates,
  getSegmentGainMultiple,
  passesDefaultChanlunFilter
} from './shouban30ChanlunFilter.mjs'

test('filters excluded plate names', () => {
  assert.deepEqual(
    filterExcludedPlates([
      { plate_name: '机器人' },
      { plate_name: 'ST股' },
      { plate_name: '公告' },
      { plate_name: 'ST板块' },
      { plate_name: '其他' }
    ]).map((item) => item.plate_name),
    ['机器人']
  )

  assert.deepEqual(
    [...CHANLUN_EXCLUDED_PLATE_NAMES].sort(),
    ['ST股', 'ST板块', '公告', '其他'].sort()
  )
})

test('computes price multiple from segment prices', () => {
  assert.equal(getSegmentGainMultiple({ start_price: 10, end_price: 30 }), 3)
  assert.equal(getSegmentGainMultiple({ start_price: 0, end_price: 30 }), null)
  assert.equal(getSegmentGainMultiple({ start_price: 10, end_price: null }), null)
})

test('passes default 30m chanlun filter only when higher segment, segment, bi all satisfy limits', () => {
  assert.deepEqual(
    passesDefaultChanlunFilter({
      ok: true,
      structure: {
        higher_segment: { start_price: 10, end_price: 20 },
        segment: { start_price: 10, end_price: 29.9 },
        bi: { price_change_pct: 30 }
      }
    }),
    {
      passed: true,
      higher_multiple: 2,
      segment_multiple: 2.99,
      bi_gain_percent: 30,
      reason: 'passed'
    }
  )

  assert.equal(
    passesDefaultChanlunFilter({
      ok: true,
      structure: {
        higher_segment: { start_price: 10, end_price: 31 },
        segment: { start_price: 10, end_price: 20 },
        bi: { price_change_pct: 10 }
      }
    }).passed,
    false
  )

  assert.equal(
    passesDefaultChanlunFilter({
      ok: true,
      structure: {
        higher_segment: { start_price: 10, end_price: 20 },
        segment: { start_price: 10, end_price: 31 },
        bi: { price_change_pct: 10 }
      }
    }).reason,
    'segment_multiple_exceed'
  )

  assert.equal(
    passesDefaultChanlunFilter({
      ok: true,
      structure: {
        higher_segment: { start_price: 10, end_price: 20 },
        segment: { start_price: 10, end_price: 20 },
        bi: { price_change_pct: 30.1 }
      }
    }).reason,
    'bi_gain_exceed'
  )
})

test('treats missing structure or failed response as not passed', () => {
  assert.equal(
    passesDefaultChanlunFilter({ ok: false, structure: {} }).reason,
    'structure_unavailable'
  )
  assert.equal(
    passesDefaultChanlunFilter({
      ok: true,
      structure: {
        higher_segment: null,
        segment: { start_price: 10, end_price: 20 },
        bi: { price_change_pct: 10 }
      }
    }).passed,
    false
  )
})
