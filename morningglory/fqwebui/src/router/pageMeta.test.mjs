import test from 'node:test'
import assert from 'node:assert/strict'

import {
  getHeaderNavTarget,
  resolveDocumentTitle,
} from './pageMeta.mjs'

test('header nav target returns label, route and tab title query', () => {
  assert.deepEqual(getHeaderNavTarget('runtime'), {
    label: '运行观测',
    path: '/runtime-observability',
    query: {
      tabTitle: '运行观测',
    },
  })
})

test('resolveDocumentTitle prefers query title then route meta title', () => {
  assert.equal(resolveDocumentTitle({
    query: {
      tabTitle: '首板选股',
    },
    meta: {
      title: '板块趋势',
    },
  }), '首板选股')

  assert.equal(resolveDocumentTitle({
    query: {},
    meta: {
      title: '股票',
    },
  }), '股票')
})
