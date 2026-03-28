import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  buildBootstrapLedgerSections,
  buildLedgerColumns,
  buildSettingsLedgerSections,
  flattenLedgerRows,
  readSystemConfigPayload,
  resolveEditorMeta,
} from './systemSettings.mjs'

const createPayload = () => ({
  bootstrap: {
    file_path: 'D:/fqpack/config/freshquant_bootstrap.yaml',
    values: {
      mongodb: {
        host: '127.0.0.1',
        port: 27027,
        db: 'freshquant',
        gantt_db: 'freshquant_gantt',
      },
      redis: {
        host: '127.0.0.1',
        port: 6380,
        db: 1,
        password: 'secret',
      },
      order_management: {
        mongo_database: 'freshquant_order_management',
        projection_database: 'freshquant',
      },
      position_management: {
        mongo_database: 'freshquant_position_management',
      },
      memory: {
        mongodb: {
          host: '127.0.0.1',
          port: 27027,
          db: 'fq_memory',
        },
        cold_root: 'D:/fqpack/runtime/memory',
        artifact_root: 'D:/fqpack/runtime/memory/artifacts',
      },
    },
    sections: [
      {
        key: 'mongodb',
        title: 'MongoDB',
        description: '主业务库与只读模型依赖的 Mongo 启动配置。',
        source: 'bootstrap_file',
        restart_required: true,
        items: [
          { key: 'mongodb.host', label: '主机', value: '127.0.0.1' },
          { key: 'mongodb.port', label: '端口', value: 27027 },
        ],
      },
      {
        key: 'redis',
        title: 'Redis',
        description: '运行队列与实时缓存依赖的 Redis 启动配置。',
        source: 'bootstrap_file',
        restart_required: true,
        items: [
          { key: 'redis.password', label: '密码', value: 'secret' },
          { key: 'redis.port', label: '端口', value: 6380 },
        ],
      },
      {
        key: 'order_management',
        title: '订单管理',
        description: '订单管理写库与 projection 库配置。',
        source: 'bootstrap_file',
        restart_required: true,
        items: [
          { key: 'order_management.mongo_database', label: 'Mongo 库', value: 'freshquant_order_management' },
        ],
      },
      {
        key: 'position_management',
        title: '仓位管理库',
        description: '仓位管理单独 Mongo 库配置。',
        source: 'bootstrap_file',
        restart_required: true,
        items: [
          { key: 'position_management.mongo_database', label: 'Mongo 库', value: 'freshquant_position_management' },
        ],
      },
      {
        key: 'memory',
        title: 'Memory',
        description: 'Memory 服务冷数据和 artifact 根路径。',
        source: 'bootstrap_file',
        restart_required: true,
        items: [
          { key: 'memory.mongodb.host', label: 'Mongo 主机', value: '127.0.0.1' },
        ],
      },
    ],
  },
  settings: {
    values: {
      monitor: {
        xtdata: {
          mode: 'guardian_1m',
          max_symbols: 60,
          queue_backlog_threshold: 500,
          prewarm: { max_bars: 240 },
        },
      },
      xtquant: {
        path: 'D:/xtquant/userdata_mini',
        account: '068000076370',
        account_type: 'CREDIT',
        broker_submit_mode: 'observe_only',
      },
      guardian: {
        stock: {
          lot_amount: 1500,
          threshold: {
            mode: 'percent',
            percent: 1,
            atr: { period: 14, multiplier: 1.2 },
          },
          grid_interval: {
            mode: 'atr',
            percent: 3,
            atr: { period: 21, multiplier: 2 },
          },
        },
      },
      position_management: {
        allow_open_min_bail: 800000,
        holding_only_min_bail: 100000,
        single_symbol_position_limit: 600000,
      },
    },
    strategies: [
      {
        code: 'Guardian',
        name: '守护者策略',
        desc: '这是一个高抛低吸的超级网格策略',
        b62_uid: 'g8txDZY5cclM7zbo',
      },
    ],
    sections: [
      {
        key: 'monitor',
        title: '监控',
        description: 'XTData 订阅模式、预热和消费节流配置。',
        source: 'params.monitor',
        restart_required: false,
        items: [
          { key: 'monitor.xtdata.mode', label: 'XTData 模式', value: 'guardian_1m' },
          { key: 'monitor.xtdata.max_symbols', label: '最大订阅数', value: 60 },
        ],
      },
      {
        key: 'xtquant',
        title: 'XTQuant',
        description: '交易连接、账户和 broker submit mode。',
        source: 'params.xtquant',
        restart_required: false,
        items: [
          { key: 'xtquant.account_type', label: '账户类型', value: 'CREDIT' },
          { key: 'xtquant.broker_submit_mode', label: 'Broker Submit Mode', value: 'observe_only' },
        ],
      },
      {
        key: 'guardian',
        title: 'Guardian',
        description: 'Guardian 股票阈值、网格间距和下单金额配置。',
        source: 'params.guardian',
        restart_required: false,
        items: [
          { key: 'guardian.stock.threshold.mode', label: '阈值模式', value: 'percent' },
          { key: 'guardian.stock.threshold.percent', label: '阈值百分比', value: 1 },
          { key: 'guardian.stock.threshold.atr.period', label: '阈值 ATR 周期', value: 14 },
          { key: 'guardian.stock.threshold.atr.multiplier', label: '阈值 ATR 倍数', value: 1.2 },
          { key: 'guardian.stock.grid_interval.mode', label: '网格模式', value: 'atr' },
          { key: 'guardian.stock.grid_interval.percent', label: '网格百分比', value: 3 },
          { key: 'guardian.stock.grid_interval.atr.period', label: '网格 ATR 周期', value: 21 },
          { key: 'guardian.stock.grid_interval.atr.multiplier', label: '网格 ATR 倍数', value: 2 },
        ],
      },
      {
        key: 'position_management',
        title: '仓位门禁',
        description: '仓位管理阈值真值，保存在 pm_configs。',
        source: 'pm_configs.thresholds',
        restart_required: false,
        items: [
          { key: 'position_management.allow_open_min_bail', label: '允许开新仓最低保证金', value: 800000 },
          { key: 'position_management.holding_only_min_bail', label: '仅允许持仓内买入最低保证金', value: 100000 },
          { key: 'position_management.single_symbol_position_limit', label: '单标的实时仓位上限', value: 600000 },
        ],
      },
    ],
  },
})

test('readSystemConfigPayload unwraps axios responses', () => {
  const payload = createPayload()
  assert.deepEqual(readSystemConfigPayload({ data: payload }), payload)
})

test('bootstrap sections flatten into dense ledger rows with column and editor metadata', () => {
  const payload = createPayload()
  const sections = buildBootstrapLedgerSections(payload, {
    currentValues: payload.bootstrap.values,
    baselineValues: payload.bootstrap.values,
  })
  const rows = flattenLedgerRows(sections)

  const mongodbHost = rows.find((row) => row.key === 'mongodb.host')
  const redisPort = rows.find((row) => row.key === 'redis.port')

  assert.equal(mongodbHost.column, 'left')
  assert.equal(mongodbHost.editor.type, 'text')
  assert.equal(redisPort.column, 'left')
  assert.equal(redisPort.editor.type, 'number')
})

test('module grouping keeps storage sections together and puts PM thresholds in the trading column', () => {
  const payload = createPayload()
  const bootstrapSections = buildBootstrapLedgerSections(payload, {
    currentValues: payload.bootstrap.values,
    baselineValues: payload.bootstrap.values,
  })
  const settingsSections = buildSettingsLedgerSections(payload, {
    currentValues: payload.settings.values,
    baselineValues: payload.settings.values,
  })
  const columns = buildLedgerColumns([...bootstrapSections, ...settingsSections])

  const leftKeys = columns.find((column) => column.key === 'left').sections.map((section) => section.key)
  const middleKeys = columns.find((column) => column.key === 'middle').sections.map((section) => section.key)
  const rightKeys = columns.find((column) => column.key === 'right').sections.map((section) => section.key)

  assert.deepEqual(leftKeys, ['mongodb', 'redis', 'order_management', 'position_management', 'memory'])
  assert.deepEqual(middleKeys, ['xtquant', 'monitor'])
  assert.deepEqual(rightKeys, ['guardian', 'position_management'])
})

test('settings rows keep guardian percent and atr rows visible while marking inactive mode rows', () => {
  const payload = createPayload()
  const currentValues = JSON.parse(JSON.stringify(payload.settings.values))
  currentValues.guardian.stock.threshold.mode = 'percent'
  currentValues.guardian.stock.grid_interval.mode = 'atr'

  const sections = buildSettingsLedgerSections(payload, {
    currentValues,
    baselineValues: payload.settings.values,
  })
  const rows = flattenLedgerRows(sections)

  const thresholdPercent = rows.find((row) => row.key === 'guardian.stock.threshold.percent')
  const thresholdAtrPeriod = rows.find((row) => row.key === 'guardian.stock.threshold.atr.period')
  const gridPercent = rows.find((row) => row.key === 'guardian.stock.grid_interval.percent')
  const gridAtrPeriod = rows.find((row) => row.key === 'guardian.stock.grid_interval.atr.period')

  assert.ok(thresholdPercent)
  assert.ok(thresholdAtrPeriod)
  assert.ok(gridPercent)
  assert.ok(gridAtrPeriod)
  assert.equal(thresholdPercent.inactive, false)
  assert.equal(thresholdAtrPeriod.inactive, true)
  assert.equal(gridPercent.inactive, true)
  assert.equal(gridAtrPeriod.inactive, false)
})

test('resolveEditorMeta returns official select options for enum settings', () => {
  assert.deepEqual(resolveEditorMeta('monitor.xtdata.mode').options.map((item) => item.value), [
    'guardian_1m',
    'guardian_and_clx_15_30',
  ])
  assert.deepEqual(resolveEditorMeta('xtquant.account_type').options.map((item) => item.value), [
    'STOCK',
    'CREDIT',
  ])
  assert.deepEqual(resolveEditorMeta('guardian.stock.threshold.mode').options.map((item) => item.value), [
    'percent',
    'atr',
  ])
  assert.deepEqual(resolveEditorMeta('position_management.single_symbol_position_limit'), {
    type: 'number',
    min: 0,
    step: 10000,
  })
})

test('monitor mode editor only exposes official guardian and combined modes', () => {
  const options = resolveEditorMeta('monitor.xtdata.mode').options.map((item) => item.value)
  const content = readFileSync(new URL('./SystemSettings.vue', import.meta.url), 'utf8')

  assert.deepEqual(options, ['guardian_1m', 'guardian_and_clx_15_30'])
  assert.equal(options.includes('clx_15_30'), false)
  assert.match(content, /buildSettingsLedgerSections/)
})
