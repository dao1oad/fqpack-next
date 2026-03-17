import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildDailyScreeningCliPreview,
  buildDailyScreeningForms,
  getDailyScreeningGuide,
  resolveDailyScreeningFields,
} from './dailyScreeningPage.mjs'

const schema = {
  models: [
    {
      id: 'clxs',
      fields: [
        { name: 'days', default: 1 },
        { name: 'code', default: '' },
        { name: 'wave_opt', default: 1560 },
        { name: 'stretch_opt', default: 0 },
        { name: 'trend_opt', default: 1 },
        { name: 'model_opt', default: 10001, options: [{ value: 10001, label: '默认 CLXS' }] },
        { name: 'save_pre_pools', default: true },
        { name: 'output_category', default: 'CLXS_10001' },
        { name: 'remark', default: 'daily-screening:clxs', readonly: true },
      ],
    },
    {
      id: 'chanlun',
      fields: [
        { name: 'days', default: 1 },
        {
          name: 'input_mode',
          default: 'all_pre_pools',
          options: [{ value: 'single_code', label: '单票扫描' }],
        },
        { name: 'code', default: '' },
        {
          name: 'period_mode',
          default: 'all',
          options: [{ value: 'all', label: '30m / 60m / 1d' }],
        },
        { name: 'pre_pool_category', default: '' },
        { name: 'pre_pool_remark', default: '' },
        { name: 'max_concurrent', default: 50 },
        { name: 'save_signal', default: false },
        { name: 'save_pools', default: false },
        { name: 'save_pre_pools', default: true },
        { name: 'pool_expire_days', default: 10 },
        { name: 'output_category', default: 'chanlun_service' },
        { name: 'remark', default: 'daily-screening:chanlun', readonly: true },
      ],
    },
  ],
  options: {
    pre_pool_categories: ['CLXS_10001', 'chanlun_service'],
    pre_pool_remarks: ['daily-screening:chanlun', 'daily-screening:clxs'],
  },
}

test('buildDailyScreeningForms seeds defaults from schema', () => {
  const forms = buildDailyScreeningForms(schema)

  assert.deepEqual(forms.clxs, {
    days: 1,
    code: '',
    wave_opt: 1560,
    stretch_opt: 0,
    trend_opt: 1,
    model_opt: 10001,
    save_pre_pools: true,
    output_category: 'CLXS_10001',
    remark: 'daily-screening:clxs',
  })
  assert.equal(forms.chanlun.input_mode, 'all_pre_pools')
  assert.equal(forms.chanlun.period_mode, 'all')
})

test('resolveDailyScreeningFields hides and expands chanlun fields by mode', () => {
  const fields = resolveDailyScreeningFields(
    schema,
    'chanlun',
    {
      input_mode: 'remark_filtered_pre_pools',
      save_pools: true,
    },
  )

  const fieldNames = fields.map((field) => field.name)
  assert.ok(fieldNames.includes('pre_pool_remark'))
  assert.ok(!fieldNames.includes('code'))
  assert.ok(fieldNames.includes('pool_expire_days'))
  const remarkField = fields.find((field) => field.name === 'pre_pool_remark')
  assert.deepEqual(
    remarkField.options.map((item) => item.value),
    ['daily-screening:chanlun', 'daily-screening:clxs'],
  )
})

test('buildDailyScreeningCliPreview renders clxs command and page-only extensions', () => {
  const preview = buildDailyScreeningCliPreview('clxs', {
    days: 2,
    code: '000001',
    wave_opt: 1560,
    stretch_opt: 0,
    trend_opt: 1,
    model_opt: 10001,
    remark: 'daily-screening:clxs',
  })

  assert.equal(
    preview.command,
    'stock screen clxs --days 2 --code 000001 --wave-opt 1560 --stretch-opt 0 --trend-opt 1 --model-opt 10001',
  )
  assert.deepEqual(preview.extensions, ['remark=daily-screening:clxs'])
})

test('buildDailyScreeningCliPreview renders chanlun command for filtered pre-pools', () => {
  const preview = buildDailyScreeningCliPreview('chanlun', {
    days: 1,
    input_mode: 'remark_filtered_pre_pools',
    pre_pool_remark: 'daily-screening:clxs',
    period_mode: '60m',
    max_concurrent: 50,
    save_signal: true,
    save_pools: true,
    pool_expire_days: 15,
    remark: 'daily-screening:chanlun',
  })

  assert.equal(
    preview.command,
    'stock screen chanlun --days 1 --period 60m',
  )
  assert.deepEqual(preview.extensions, [
    'input_mode=remark_filtered_pre_pools',
    'pre_pool_remark=daily-screening:clxs',
    'max_concurrent=50',
    'save_signal=true',
    'save_pools=true',
    'pool_expire_days=15',
    'remark=daily-screening:chanlun',
  ])
})

test('getDailyScreeningGuide exposes the real rule summary for each model', () => {
  const clxsGuide = getDailyScreeningGuide('clxs')
  const chanlunGuide = getDailyScreeningGuide('chanlun')

  assert.ok(clxsGuide.some((line) => line.includes('sigs[-1] > 0')))
  assert.ok(chanlunGuide.some((line) => line.includes('BUY_LONG')))
})
