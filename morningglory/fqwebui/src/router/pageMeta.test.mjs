import test from 'node:test'
import assert from 'node:assert/strict'

import {
  HEADER_NAV_GROUPS,
  getHeaderNavTarget,
  resolveHeaderNavGroups,
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

test('header nav groups stay metadata-driven and preserve the expected workbench grouping order', () => {
  assert.deepEqual(HEADER_NAV_GROUPS, [
    ['systemSettings'],
    ['futures'],
    ['klineSlim', 'orders', 'positionManagement', 'subjectManagement', 'tpsl', 'runtime'],
    ['gantt', 'shouban30', 'dailyScreening'],
    ['stock', 'pool', 'cjsd'],
  ])

  const groups = resolveHeaderNavGroups()
  assert.equal(groups.length, HEADER_NAV_GROUPS.length)
  assert.equal(groups[2][0].label, '行情图表')
  assert.equal(groups[2][5].query.tabTitle, '运行观测')
  assert.equal(groups[3][1].query.days, '30')
  assert.equal(groups[4][2].path, '/stock-cjsd')
})
