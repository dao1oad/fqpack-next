import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildDailyScreeningForms,
  buildDailyScreeningQueryPayload,
  buildDailyScreeningSetOptions,
  buildDailyScreeningWorkbenchState,
  normalizeDailyScreeningScopeItems,
  readDailyScreeningPayload,
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
          default: [10001, 10002, 10003],
          options: [
            { value: 10001, label: 'S0001' },
            { value: 10002, label: 'S0002' },
            { value: 10003, label: 'S0003' },
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
          options: [{ value: 10001, label: 'S0001' }],
        },
        { name: 'save_pre_pools', default: true },
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
        { name: 'save_pools', default: false },
        { name: 'pool_expire_days', default: 10 },
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
    clxs_model_opts: [10001, 10002, 10003],
    chanlun_signal_types: ['buy_zs_huila', 'macd_bullish_divergence'],
    chanlun_period_mode: 'all',
  })
  assert.equal(forms.clxs.remark, 'daily-screening:clxs')
  assert.equal(forms.chanlun.remark, 'daily-screening:chanlun')
})

test('readDailyScreeningPayload supports both axios envelopes and interceptor-unwrapped payloads', () => {
  assert.deepEqual(
    readDailyScreeningPayload({
      data: {
        run: { id: 'run-1' },
      },
    }),
    {
      run: { id: 'run-1' },
    },
  )

  assert.deepEqual(
    readDailyScreeningPayload({
      run: { id: 'run-2' },
    }),
    {
      run: { id: 'run-2' },
    },
  )

  assert.deepEqual(
    readDailyScreeningPayload({
      run_id: 'run-9',
      scope: 'run:run-9',
      label: 'run-9',
    }),
    {
      run_id: 'run-9',
      scope: 'run:run-9',
      label: 'run-9',
    },
  )

  assert.deepEqual(readDailyScreeningPayload(null), {})
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
})

test('buildDailyScreeningWorkbenchState exposes intersection defaults for the unified workbench', () => {
  const state = buildDailyScreeningWorkbenchState(schema, {
    run_id: 'run-9',
    scope: 'run:run-9',
    label: 'run-9',
  })

  assert.equal(state.selectedModel, 'all')
  assert.equal(state.selectedRunId, 'run-9')
  assert.deepEqual(state.selectedSets, ['clxs', 'chanlun'])
  assert.deepEqual(state.clxsModels, [])
  assert.deepEqual(state.chanlunSignalTypes, [])
  assert.deepEqual(state.chanlunPeriods, [])
  assert.deepEqual(state.shouban30Providers, [])
})

test('normalizeDailyScreeningScopeItems keeps latest flag and stable labels', () => {
  const items = normalizeDailyScreeningScopeItems({
    items: [
      { run_id: 'run-2', scope: 'run:run-2', label: 'run-2', is_latest: true },
      { run_id: 'run-1', scope: 'run:run-1', label: 'run-1', is_latest: false },
    ],
  })

  assert.deepEqual(items, [
    { runId: 'run-2', scope: 'run:run-2', label: 'run-2', isLatest: true },
    { runId: 'run-1', scope: 'run:run-1', label: 'run-1', isLatest: false },
  ])
})

test('buildDailyScreeningSetOptions maps summary counts to the six intersection sources', () => {
  const options = buildDailyScreeningSetOptions({
    stage_counts: {
      clxs: 12,
      chanlun: 5,
      shouban30_agg90: 8,
      market_flags: 11,
    },
  })

  assert.deepEqual(
    options.map((item) => item.key),
    ['clxs', 'chanlun', 'shouban30_agg90', 'credit_subject', 'near_long_term_ma', 'quality_subject'],
  )
  assert.equal(options[0].count, 12)
  assert.equal(options[1].count, 5)
  assert.equal(options[2].count, 8)
})

test('buildDailyScreeningQueryPayload keeps source intersection and source-internal union filters separate', () => {
  const payload = buildDailyScreeningQueryPayload({
    runId: 'run-1',
    selectedSets: ['clxs', 'chanlun', 'quality_subject'],
    clxsModels: ['CLXS_10001', 'CLXS_10008'],
    chanlunSignalTypes: ['buy_zs_huila'],
    chanlunPeriods: ['30m', '60m'],
    shouban30Providers: ['xgb'],
  })

  assert.deepEqual(payload, {
    run_id: 'run-1',
    selected_sets: ['clxs', 'chanlun', 'quality_subject'],
    clxs_models: ['CLXS_10001', 'CLXS_10008'],
    chanlun_signal_types: ['buy_zs_huila'],
    chanlun_periods: ['30m', '60m'],
    shouban30_providers: ['xgb'],
  })
})

test('buildDailyScreeningQueryPayload normalizes numeric clxs model selections to membership model keys', () => {
  const payload = buildDailyScreeningQueryPayload({
    runId: 'run-1',
    clxsModels: [10001, '10008'],
  })

  assert.deepEqual(payload, {
    run_id: 'run-1',
    clxs_models: ['CLXS_10001', 'CLXS_10008'],
  })
})
