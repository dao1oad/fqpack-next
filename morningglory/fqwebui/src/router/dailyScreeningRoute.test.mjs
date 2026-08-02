import test from 'node:test'
import assert from 'node:assert/strict'

import {
  getHeaderNavTarget,
  resolveRouteMetaTitle,
} from './pageMeta.mjs'

test('legacy daily screening metadata remains resolvable for compatible deep links', () => {
  assert.deepEqual(getHeaderNavTarget('dailyScreening'), {
    label: '每日选股',
    path: '/daily-screening',
    query: {
      tabTitle: '每日选股',
    },
  })
  assert.equal(resolveRouteMetaTitle('daily-screening'), '每日选股')
})
