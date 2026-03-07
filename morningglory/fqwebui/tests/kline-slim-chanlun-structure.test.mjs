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
