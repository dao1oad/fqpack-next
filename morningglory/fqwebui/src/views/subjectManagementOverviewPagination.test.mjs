import test from 'node:test'
import assert from 'node:assert/strict'

import { paginateOverviewRows } from './subjectManagementOverviewPagination.mjs'

const buildRows = (count) => Array.from({ length: count }, (_, index) => ({
  symbol: `SYM${String(index + 1).padStart(3, '0')}`,
}))

test('paginateOverviewRows returns 100 rows per page by default', () => {
  const page = paginateOverviewRows(buildRows(205), {
    page: 1,
    pageSize: 100,
  })

  assert.equal(page.page, 1)
  assert.equal(page.pageSize, 100)
  assert.equal(page.total, 205)
  assert.equal(page.totalPages, 3)
  assert.equal(page.rows.length, 100)
  assert.equal(page.rows[0].symbol, 'SYM001')
  assert.equal(page.rows.at(-1).symbol, 'SYM100')
})

test('paginateOverviewRows clamps page number to the last available page', () => {
  const page = paginateOverviewRows(buildRows(205), {
    page: 9,
    pageSize: 100,
  })

  assert.equal(page.page, 3)
  assert.equal(page.rows.length, 5)
  assert.deepEqual(
    page.rows.map((row) => row.symbol),
    ['SYM201', 'SYM202', 'SYM203', 'SYM204', 'SYM205'],
  )
})

test('paginateOverviewRows keeps page 1 when there are no rows', () => {
  const page = paginateOverviewRows([], {
    page: 4,
    pageSize: 100,
  })

  assert.equal(page.page, 1)
  assert.equal(page.total, 0)
  assert.equal(page.totalPages, 1)
  assert.deepEqual(page.rows, [])
})
