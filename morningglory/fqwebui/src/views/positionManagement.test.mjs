import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

import { buildConfigSections } from './positionManagement.mjs'

test('buildConfigSections keeps single symbol position limit in editable thresholds', () => {
  const sections = buildConfigSections({
    config: {
      inventory: [
        {
          key: 'holding_only_min_bail',
          label: '仅允许持仓内买入最低保证金',
          value: 100000,
          editable: true,
          group: 'editable_thresholds',
          description: '',
        },
        {
          key: 'single_symbol_position_limit',
          label: '单标的实时仓位上限',
          value: 800000,
          editable: true,
          group: 'editable_thresholds',
          description: '',
        },
        {
          key: 'allow_open_min_bail',
          label: '允许开新仓最低保证金',
          value: 800000,
          editable: true,
          group: 'editable_thresholds',
          description: '',
        },
      ],
    },
  })

  const editable = sections.find((item) => item.key === 'editable_thresholds')

  assert.deepEqual(
    editable.items.map((item) => item.key),
    ['allow_open_min_bail', 'holding_only_min_bail', 'single_symbol_position_limit'],
  )
  assert.equal(editable.items[2].value_label, '800,000.00')
})

test('PositionManagement view renders single symbol position limit editor', () => {
  const source = fs.readFileSync(new URL('./PositionManagement.vue', import.meta.url), 'utf8')

  assert.match(source, /single_symbol_position_limit/)
  assert.match(source, /v-model="editableForm\.single_symbol_position_limit"/)
})
