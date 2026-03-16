import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('system settings uses list-based summary sections instead of panel cards', async () => {
  const content = await readFile(new URL('./SystemSettings.vue', import.meta.url), 'utf8')

  assert.match(content, /settings-summary-list/)
  assert.match(content, /settings-strategy-list/)
  assert.doesNotMatch(content, /class="panel-card"/)
})
