import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('system settings uses a three-column dense ledger workspace instead of card panels', async () => {
  const content = await readFile(new URL('./SystemSettings.vue', import.meta.url), 'utf8')

  assert.match(content, /settings-dense-toolbar/)
  assert.match(content, /settings-dense-columns/)
  assert.match(content, /settings-dense-column/)
  assert.match(content, /settings-ledger__header/)
  assert.match(content, /settings-ledger__row/)
  assert.doesNotMatch(content, /panel-card/)
})
