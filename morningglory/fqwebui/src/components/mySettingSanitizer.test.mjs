import test from 'node:test'
import assert from 'node:assert/strict'

import { migrateMonitorXtdataMode, sanitizeLegacySettingValue } from './mySettingSanitizer.mjs'

test('sanitizeLegacySettingValue strips removed monitor fields', () => {
  const value = sanitizeLegacySettingValue('monitor', {
    stock: {
      periods: ['1m', '5m'],
      auto_open: true,
    },
    xtdata: {
      mode: 'guardian_and_clx_15_30',
    },
  })

  assert.deepEqual(value, {
    xtdata: {
      trading_mode: true,
      screening_mode: true,
    },
  })
})

test('migrateMonitorXtdataMode maps legacy modes to dual booleans', () => {
  assert.deepEqual(migrateMonitorXtdataMode('guardian_1m'), { trading_mode: true, screening_mode: false })
  assert.deepEqual(migrateMonitorXtdataMode('guardian_and_clx_15_30'), { trading_mode: true, screening_mode: true })
  assert.deepEqual(migrateMonitorXtdataMode('clx_15_30'), { trading_mode: true, screening_mode: true })
  assert.deepEqual(migrateMonitorXtdataMode('clx_15_30_only'), { trading_mode: false, screening_mode: true })
  assert.deepEqual(migrateMonitorXtdataMode('unknown'), { trading_mode: true, screening_mode: false })
  assert.deepEqual(migrateMonitorXtdataMode(''), { trading_mode: true, screening_mode: false })
})

test('sanitizeLegacySettingValue strips removed guardian fields', () => {
  const value = sanitizeLegacySettingValue('guardian', {
    stock: {
      position_pct: 30,
      auto_open: true,
      min_amount: 1000,
      lot_amount: 5000,
      threshold: {
        mode: 'percent',
        percent: 1,
      },
    },
  })

  assert.deepEqual(value, {
    stock: {
      lot_amount: 5000,
      threshold: {
        mode: 'percent',
        percent: 1,
      },
    },
  })
})
