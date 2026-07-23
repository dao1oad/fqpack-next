import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  getHeaderNavTarget,
  resolveRouteMetaTitle,
} from './pageMeta.mjs'

test('position review is exposed immediately after position management in header navigation', async () => {
  assert.deepEqual(getHeaderNavTarget('positionReview'), {
    label: '持仓复盘',
    path: '/position-review',
    query: {
      tabTitle: '持仓复盘',
    },
  })
  assert.equal(resolveRouteMetaTitle('position-review'), '持仓复盘')

  const pageMetaSource = await readFile(new URL('./pageMeta.mjs', import.meta.url), 'utf8')
  assert.match(
    pageMetaSource.replace(/\r/g, ''),
    /\['klineSlim', 'positionManagement', 'positionReview', 'runtime'\]/,
  )
})

test('position review route stays lazy loaded', async () => {
  const routerSource = await readFile(new URL('./index.js', import.meta.url), 'utf8')
  const source = routerSource.replace(/\r/g, '')

  assert.match(
    source,
    /const PositionReview = \(\) => import\('\.\.\/views\/PositionReview\.vue'\)/,
  )
  assert.match(
    source,
    /path: '\/position-review',[\s\S]*?name: 'position-review',[\s\S]*?component: PositionReview/,
  )
  assert.doesNotMatch(
    source,
    /import PositionReview from '\.\.\/views\/PositionReview\.vue'/,
  )
})
