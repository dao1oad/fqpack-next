import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  getHeaderNavTarget,
  resolveRouteMetaTitle,
} from './pageMeta.mjs'

test('CLX daily screening is exposed by metadata-driven navigation', () => {
  assert.deepEqual(getHeaderNavTarget('clxDailyScreening'), {
    label: 'CLX日线选股',
    path: '/clx-daily-screening',
    query: { tabTitle: 'CLX日线选股' },
  })
  assert.equal(resolveRouteMetaTitle('clx-daily-screening'), 'CLX日线选股')
})

test('CLX daily screening route is lazy loaded', async () => {
  const source = await readFile(new URL('./index.js', import.meta.url), 'utf8')
  assert.match(source, /const ClxDailyScreening = \(\) => import\('\.\.\/views\/ClxDailyScreening\.vue'\)/)
  assert.match(source, /path: '\/clx-daily-screening',[\s\S]*name: 'clx-daily-screening',[\s\S]*component: ClxDailyScreening/)
})
