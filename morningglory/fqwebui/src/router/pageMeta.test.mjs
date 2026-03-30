import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  HEADER_NAV_GROUPS,
  getHeaderNavTarget,
  resolveHeaderNavGroups,
  resolveDocumentTitle,
} from './pageMeta.mjs'

const ACTIVE_CORE_ROUTE_SPECS = [
  {
    componentName: 'StockControl',
    importPath: '../views/StockControl.vue',
    routePath: '/stock-control',
    routeName: 'stock-control',
  },
  {
    componentName: 'MultiPeriod',
    importPath: '../views/MultiPeriod.vue',
    routePath: '/multi-period',
    routeName: 'multi-period',
  },
  {
    componentName: 'KlineBig',
    importPath: '../views/KlineBig.vue',
    routePath: '/kline-big',
    routeName: 'kline-big',
  },
  {
    componentName: 'KlineSlim',
    importPath: '../views/KlineSlim.vue',
    routePath: '/kline-slim',
    routeName: 'kline-slim',
  },
  {
    componentName: 'RuntimeObservability',
    importPath: '../views/RuntimeObservability.vue',
    routePath: '/runtime-observability',
    routeName: 'runtime-observability',
  },
]

const escapeForRegex = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

test('runtime remains a valid header nav target', () => {
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

test('header nav groups remove deprecated pages while preserving active workbench order', () => {
  assert.deepEqual(HEADER_NAV_GROUPS, [
    ['systemSettings'],
    ['klineSlim', 'orders', 'positionManagement', 'subjectManagement', 'tpsl', 'runtime'],
    ['gantt', 'shouban30', 'dailyScreening'],
    ['stock'],
  ])

  const groups = resolveHeaderNavGroups().map((group) => group.map(({ label, path, query }) => ({
    label,
    path,
    query,
  })))

  assert.deepEqual(groups, [
    [
      {
        label: '设置',
        path: '/system-settings',
        query: {
          tabTitle: '设置',
        },
      },
    ],
    [
      {
        label: '行情图表',
        path: '/kline-slim',
        query: {
          tabTitle: '行情图表',
        },
      },
      {
        label: '订单管理',
        path: '/order-management',
        query: {
          tabTitle: '订单管理',
        },
      },
      {
        label: '仓位管理',
        path: '/position-management',
        query: {
          tabTitle: '仓位管理',
        },
      },
      {
        label: '标的管理',
        path: '/subject-management',
        query: {
          tabTitle: '标的管理',
        },
      },
      {
        label: 'TPSL',
        path: '/tpsl',
        query: {
          tabTitle: 'TPSL',
        },
      },
      {
        label: '运行观测',
        path: '/runtime-observability',
        query: {
          tabTitle: '运行观测',
        },
      },
    ],
    [
      {
        label: '板块趋势',
        path: '/gantt',
        query: {
          p: 'xgb',
          tabTitle: '板块趋势',
        },
      },
      {
        label: '首板选股',
        path: '/gantt/shouban30',
        query: {
          p: 'xgb',
          days: '30',
          tabTitle: '首板选股',
        },
      },
      {
        label: '每日选股',
        path: '/daily-screening',
        query: {
          tabTitle: '每日选股',
        },
      },
    ],
    [
      {
        label: '股票',
        path: '/stock-control',
        query: {
          tabTitle: '股票',
        },
      },
    ],
  ])
  assert.deepEqual(
    HEADER_NAV_GROUPS.flat().filter((key) => ['futures', 'pool', 'cjsd'].includes(key)),
    [],
  )
})

test('router redirects root to runtime observability and keeps active core routes lazy-loaded with route bindings', async () => {
  const routerSource = (await readFile(new URL('./index.js', import.meta.url), 'utf8')).replace(/\r/g, '')

  assert.match(routerSource, /path:\s*'\/',\s*redirect:\s*'\/runtime-observability'/)
  assert.doesNotMatch(routerSource, /path:\s*'\/',\s*redirect:\s*'\/stock-control'/)

  for (const {
    componentName,
    importPath,
    routePath,
    routeName,
  } of ACTIVE_CORE_ROUTE_SPECS) {
    assert.doesNotMatch(
      routerSource,
      new RegExp(`import\\s+${componentName}\\s+from\\s+'${escapeForRegex(importPath)}'`),
    )
    assert.match(
      routerSource,
      new RegExp(`const\\s+${componentName}\\s*=\\s*\\(\\)\\s*=>\\s*import\\('${escapeForRegex(importPath)}'\\)`),
    )
    assert.match(
      routerSource,
      new RegExp(
        `path:\\s*'${escapeForRegex(routePath)}',[\\s\\S]*?name:\\s*'${escapeForRegex(routeName)}',[\\s\\S]*?component:\\s*${componentName}`,
      ),
    )
  }
})
