import test from 'node:test'
import assert from 'node:assert/strict'

import { sanitizeLegacySettingValue } from './mySettingSanitizer.mjs'

test('sanitizeLegacySettingValue strips removed monitor fields', () => {
  const value = sanitizeLegacySettingValue('monitor', {
    stock: {
      periods: ['1m', '5m'],
      auto_open: true,
    },
    xtdata: {
      mode: 'guardian_1m',
    },
  })

  assert.deepEqual(value, {
    xtdata: {
      mode: 'guardian_1m',
    },
  })
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
