import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('system settings uses a three-column dense ledger workspace instead of card panels', async () => {
  const content = await readFile(new URL('./SystemSettings.vue', import.meta.url), 'utf8')

  assert.match(content, /<WorkbenchToolbar class="settings-dense-toolbar">/)
  assert.match(content, /<StatusChip class="settings-toolbar-chip settings-toolbar-chip--path" variant="info"/)
  assert.match(content, /class="settings-dense-column__body"/)
  assert.match(content, /class="settings-dense-section__header"/)
  assert.match(content, /<section[\s\S]*?<header class="settings-dense-column__head">[\s\S]*?<div class="settings-dense-column__body">/)
  assert.match(content, /<article[\s\S]*?<div class="settings-dense-section__header">[\s\S]*?<\/div>\s*<div[\s\S]*class="settings-ledger"/)
  assert.match(content, /<StatusChip class="settings-inline-chip" :variant="sectionModeChipVariant\(section\)">/)
  assert.match(content, /<StatusChip class="settings-inline-chip" :variant="restartModeChipVariant\(row\.restart_required\)">/)
  assert.match(content, /<StatusChip class="settings-inline-chip" :variant="stateChipVariant\(row\)">/)
  assert.match(content, /settings-dense-toolbar/)
  assert.match(content, /settings-dense-columns/)
  assert.match(content, /settings-dense-column/)
  assert.match(content, /settings-ledger__header/)
  assert.match(content, /settings-ledger__row/)
  assert.doesNotMatch(content, /class="settings-dense-section__sticky"/)
  assert.doesNotMatch(content, /panel-card/)
})
