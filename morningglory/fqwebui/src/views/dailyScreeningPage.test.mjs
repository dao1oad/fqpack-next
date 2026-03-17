import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildDailyScreeningModelFilters,
  buildDailyScreeningCliPreview,
  buildDailyScreeningForms,
  getDailyScreeningGuide,
  resolveDailyScreeningFields,
} from './dailyScreeningPage.mjs'

const schema = {
  models: [
    {
      id: 'all',
      fields: [
        { name: 'days', default: 1 },
        { name: 'code', default: '' },
        { name: 'wave_opt', default: 1560 },
        { name: 'stretch_opt', default: 0 },
        { name: 'trend_opt', default: 1 },
        {
          name: 'clxs_model_opts',
          default: [8, 9, 12, 10001],
          options: [
            { value: 8, label: 'MACD 背驰' },
            { value: 9, label: '中枢回拉' },
          ],
        },
        {
          name: 'chanlun_signal_types',
          default: ['buy_zs_huila', 'macd_bullish_divergence'],
          options: [
            { value: 'buy_zs_huila', label: '回拉中枢上涨' },
            { value: 'macd_bullish_divergence', label: 'MACD看涨背驰' },
          ],
        },
        {
          name: 'chanlun_period_mode',
          default: 'all',
          options: [{ value: 'all', label: '30m / 60m / 1d' }],
        },
      ],
    },
    {
      id: 'clxs',
      fields: [
        { name: 'days', default: 1 },
        { name: 'code', default: '' },
        { name: 'wave_opt', default: 1560 },
        { name: 'stretch_opt', default: 0 },
        { name: 'trend_opt', default: 1 },
        {
          name: 'model_opts',
          default: [10001],
          options: [{ value: 10001, label: '默认 CLXS' }],
        },
        { name: 'save_pre_pools', default: true },
        { name: 'output_category', default: '' },
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

  assert.deepEqual(forms.all, {
    days: 1,
    code: '',
    wave_opt: 1560,
    stretch_opt: 0,
    trend_opt: 1,
    clxs_model_opts: [8, 9, 12, 10001],
    chanlun_signal_types: ['buy_zs_huila', 'macd_bullish_divergence'],
    chanlun_period_mode: 'all',
  })
  assert.deepEqual(forms.clxs, {
    days: 1,
    code: '',
    wave_opt: 1560,
    stretch_opt: 0,
    trend_opt: 1,
    model_opts: [10001],
    save_pre_pools: true,
    output_category: '',
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

test('buildDailyScreeningCliPreview renders clxs command set and page-only extensions', () => {
  const preview = buildDailyScreeningCliPreview('clxs', {
    days: 2,
    code: '000001',
    wave_opt: 1560,
    stretch_opt: 0,
    trend_opt: 1,
    model_opts: [8, 10001],
    remark: 'daily-screening:clxs',
  })

  assert.equal(
    preview.command,
    [
      'stock screen clxs --days 2 --code 000001 --wave-opt 1560 --stretch-opt 0 --trend-opt 1 --model-opt 8',
      'stock screen clxs --days 2 --code 000001 --wave-opt 1560 --stretch-opt 0 --trend-opt 1 --model-opt 10001',
    ].join('\n'),
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

test('buildDailyScreeningCliPreview renders all-pipeline preview with CLXS and chanlun model sets', () => {
  const preview = buildDailyScreeningCliPreview('all', {
    days: 1,
    code: '',
    wave_opt: 1560,
    stretch_opt: 0,
    trend_opt: 1,
    clxs_model_opts: [8, 10001],
    chanlun_signal_types: ['buy_zs_huila', 'macd_bullish_divergence'],
    chanlun_period_mode: 'all',
  })

  assert.match(preview.command, /stock screen clxs/)
  assert.match(preview.command, /--model-opt 8/)
  assert.match(preview.command, /--model-opt 10001/)
  assert.match(preview.command, /stock screen chanlun/)
  assert.deepEqual(preview.extensions, [
    'chanlun_source=current_clxs_run',
    'chanlun_signal_types=buy_zs_huila,macd_bullish_divergence',
  ])
})

test('getDailyScreeningGuide exposes the real rule summary for each model', () => {
  const allGuide = getDailyScreeningGuide('all')
  const clxsGuide = getDailyScreeningGuide('clxs')
  const chanlunGuide = getDailyScreeningGuide('chanlun')

  assert.ok(allGuide.some((line) => line.includes('CLXS 全模型')))
  assert.ok(clxsGuide.some((line) => line.includes('sigs[-1] > 0')))
  assert.ok(chanlunGuide.some((line) => line.includes('BUY_LONG')))
})

test('buildDailyScreeningModelFilters keeps branch counts and narrows models by branch', () => {
  const rows = [
    { branch: 'clxs', model_key: 'CLXS_8', model_label: 'MACD 背驰' },
    { branch: 'clxs', model_key: 'CLXS_8', model_label: 'MACD 背驰' },
    { branch: 'clxs', model_key: 'CLXS_10001', model_label: '默认 CLXS' },
    { branch: 'chanlun', model_key: 'buy_zs_huila', model_label: '回拉中枢上涨' },
  ]

  const allFilters = buildDailyScreeningModelFilters(rows, 'all')
  const clxsFilters = buildDailyScreeningModelFilters(rows, 'clxs')

  assert.deepEqual(allFilters.branches, [
    { key: 'clxs', label: 'CLXS', count: 3 },
    { key: 'chanlun', label: 'chanlun', count: 1 },
  ])
  assert.deepEqual(allFilters.models, [
    { key: 'CLXS_8', label: 'MACD 背驰', branch: 'clxs', count: 2 },
    { key: 'CLXS_10001', label: '默认 CLXS', branch: 'clxs', count: 1 },
    { key: 'buy_zs_huila', label: '回拉中枢上涨', branch: 'chanlun', count: 1 },
  ])
  assert.deepEqual(clxsFilters.models, [
    { key: 'CLXS_8', label: 'MACD 背驰', branch: 'clxs', count: 2 },
    { key: 'CLXS_10001', label: '默认 CLXS', branch: 'clxs', count: 1 },
  ])
})
