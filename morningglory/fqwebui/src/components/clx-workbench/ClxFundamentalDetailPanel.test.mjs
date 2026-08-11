import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const readSource = async () => {
  const source = await readFile(new URL('./ClxFundamentalDetailPanel.vue', import.meta.url), 'utf8')
  return source.replace(/\r/g, '')
}

test('detail panel closes on Escape and restores list focus contract', async () => {
  const source = await readSource()
  assert.match(source, /window\.addEventListener\('keydown', onEscape\)/)
  assert.match(source, /window\.removeEventListener\('keydown', onEscape\)/)
  assert.match(source, /if \(event\.key !== 'Escape'\) return/)
  assert.match(source, /emit\('close'\)/)
  // 列表自身 Esc（收起展开行）优先，不误关详情
  assert.match(source, /target\.closest\('\.clx-fund-list'\)/)
})

test('detail panel skips Escape when typing in inputs', async () => {
  const source = await readSource()
  assert.match(source, /target\.tagName === 'INPUT' \|\| target\.tagName === 'TEXTAREA'/)
})
