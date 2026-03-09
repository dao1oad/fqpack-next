import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

test('futureApi exposes stockChanlunStructure request helper', async () => {
  const content = await readFile(new URL('../src/api/futureApi.js', import.meta.url), 'utf8')

  assert.match(content, /stockChanlunStructure\s*\(/)
  assert.match(content, /\/api\/stock_data_chanlun_structure/)
})

test('KlineSlim renders chanlun structure controls and sections', async () => {
  const content = await readFile(new URL('../src/views/KlineSlim.vue', import.meta.url), 'utf8')

  assert.match(content, /缠论结构/)
  assert.match(content, /高级段/)
  assert.match(content, /刷新/)
  assert.match(content, /关闭/)
})

test('KlineSlim renders chanlun structure as three inline summaries without pivot tables', async () => {
  const content = await readFile(new URL('../src/views/KlineSlim.vue', import.meta.url), 'utf8')
  const script = await readFile(new URL('../src/views/js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(content, /高级段/)
  assert.match(content, /段/)
  assert.match(content, /笔/)
  assert.match(content, /chanlunHigherSegmentSummary/)
  assert.match(content, /chanlunSegmentSummary/)
  assert.match(content, /chanlunBiSummary/)
  assert.match(script, /label: 'K线数'/)
  assert.doesNotMatch(content, /段 ZG/)
  assert.doesNotMatch(content, /中枢 ZG/)
  assert.doesNotMatch(content, /暂无段中枢/)
  assert.doesNotMatch(content, /暂无笔中枢/)
})

test('KlineSlim script defines helpers for inline chanlun summaries', async () => {
  const content = await readFile(new URL('../src/views/js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(content, /buildChanlunSummaryItems/)
  assert.match(content, /computeChanlunBiBarCount/)
})
