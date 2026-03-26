import test from 'node:test'
import assert from 'node:assert/strict'

import {
  formatBeijingClockTime,
  formatBeijingDateTimeParts,
  formatBeijingTimestamp,
} from './beijingTime.mjs'

test('formatBeijingTimestamp converts utc iso strings and epoch seconds to beijing second-level labels', () => {
  assert.equal(formatBeijingTimestamp('2026-03-25T05:46:10+00:00'), '2026-03-25 13:46:10')
  assert.equal(formatBeijingTimestamp(1774417570), '2026-03-25 13:46:10')
  assert.equal(formatBeijingTimestamp('2026-03-25 13:46:10'), '2026-03-25 13:46:10')
})

test('formatBeijingDateTimeParts keeps separate local date and time values at second precision', () => {
  assert.equal(formatBeijingDateTimeParts(20260325, '13:46:10'), '2026-03-25 13:46:10')
  assert.equal(formatBeijingClockTime('13:46'), '13:46:00')
})
