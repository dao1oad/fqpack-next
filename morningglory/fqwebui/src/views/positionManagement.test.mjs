import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

import { buildInventoryRows } from './positionManagement.mjs'

test('buildInventoryRows keeps single symbol position limit editable inside merged table', () => {
  const rows = buildInventoryRows({
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

  const editableRows = rows.filter((item) => item.group === 'editable_thresholds')
  const singleSymbolLimit = rows.find((item) => item.key === 'single_symbol_position_limit')

  assert.deepEqual(
    editableRows.map((item) => item.key),
    ['allow_open_min_bail', 'holding_only_min_bail', 'single_symbol_position_limit'],
  )
  assert.equal(singleSymbolLimit.value_label, '800,000.00')
  assert.equal(singleSymbolLimit.group_label, '已生效且可编辑')
  assert.equal(singleSymbolLimit.editable, true)
})

test('PositionManagement view renders merged inventory table and symbol name column', () => {
  const source = fs.readFileSync(new URL('./PositionManagement.vue', import.meta.url), 'utf8')

  assert.match(source, /inventoryRows/)
  assert.match(source, /prop="group_label" label="分组"/)
  assert.match(source, /prop="description" label="说明"/)
  assert.match(source, /prop="symbol_name_label" label="标的名称"/)
  assert.match(source, /single_symbol_position_limit/)
  assert.match(source, /v-model="editableForm\.single_symbol_position_limit"/)
  assert.doesNotMatch(source, /position-config-grid/)
  assert.doesNotMatch(source, /editableSection/)
  assert.doesNotMatch(source, /readonlySections/)
})
