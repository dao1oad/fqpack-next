import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  HEADER_NAV_GROUPS,
  getHeaderNavTarget,
  resolveHeaderNavGroups,
  resolveDocumentTitle,
} from './pageMeta.mjs'

const LEGACY_CORE_ROUTE_SPECS = [
  {
    componentName: 'FuturesControl',
    importPath: '../views/FuturesControl.vue',
    routePath: '/futures-control',
    routeName: 'futures-control',
  },
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
    componentName: 'StockPools',
    importPath: '../components/StockPools.vue',
    routePath: '/stock-pools',
    routeName: 'stock-pools',
  },
  {
    componentName: 'StockCjsd',
    importPath: '../components/StockCjsd.vue',
    routePath: '/stock-cjsd',
    routeName: 'stock-cjsd',
  },
]

const escapeForRegex = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

test('header nav target returns label, route and tab title query', () => {
  assert.deepEqual(getHeaderNavTarget('runtime'), {
    label: '运行观测',
    path: '/runtime-observability',
    query: {
      tabTitle: '运行观测',
    },
  })
  assert.equal(getHeaderNavTarget('subjectManagement'), null)
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
    ['klineSlim', 'orders', 'positionManagement', 'tpsl', 'runtime'],
    ['gantt', 'shouban30', 'dailyScreening'],
    ['stock', 'pool', 'cjsd'],
  ])

  const groups = resolveHeaderNavGroups()
  assert.equal(groups.length, HEADER_NAV_GROUPS.length)
  assert.equal(groups[2][0].label, '行情图表')
  assert.equal(groups[2][4].query.tabTitle, '运行观测')
  assert.equal(groups[3][1].query.days, '30')
  assert.equal(groups[4][2].path, '/stock-cjsd')
  assert.equal(groups.flatMap((group) => group.map((item) => item.path)).includes('/subject-management'), false)
})

test('legacy core routes stay lazy-loaded without changing redirect or route bindings', async () => {
  const routerSource = (await readFile(new URL('./index.js', import.meta.url), 'utf8')).replace(/\r/g, '')

  assert.match(routerSource, /path:\s*'\/',\s*redirect:\s*'\/stock-control'/)
  assert.doesNotMatch(routerSource, /const\s+SubjectManagement\s*=\s*\(\)\s*=>\s*import\('\.\.\/views\/SubjectManagement\.vue'\)/)
  assert.doesNotMatch(
    routerSource,
    /path:\s*'\/subject-management',[\s\S]*?name:\s*'subject-management'/,
  )

  for (const {
    componentName,
    importPath,
    routePath,
    routeName,
  } of LEGACY_CORE_ROUTE_SPECS) {
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
