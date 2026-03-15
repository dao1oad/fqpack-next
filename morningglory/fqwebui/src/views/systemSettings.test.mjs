import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildBootstrapSections,
  buildSettingsSections,
  readSystemConfigPayload,
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
    },
    sections: [
      {
        key: 'mongodb',
        title: 'MongoDB',
        description: '主业务库与只读模型依赖的 Mongo 启动配置。',
        source: 'bootstrap_file',
        restart_required: true,
        items: [
          {
            key: 'mongodb.host',
            label: '主机',
            value: '127.0.0.1',
            restart_required: true,
            source: 'bootstrap_file',
          },
          {
            key: 'mongodb.port',
            label: '端口',
            value: 27027,
            restart_required: true,
            source: 'bootstrap_file',
          },
        ],
      },
    ],
  },
  settings: {
    values: {
      monitor: {
        xtdata: { mode: 'guardian_1m' },
      },
      guardian: {
        stock: {
          lot_amount: 1500,
        },
      },
    },
    strategies: [
      { code: 'Guardian', name: '守护者策略', b62_uid: 'g8txDZY5cclM7zbo' },
    ],
    sections: [
      {
        key: 'monitor',
        title: '监控',
        description: 'XTData 订阅模式、预热和消费节流配置。',
        source: 'params.monitor',
        restart_required: false,
        items: [
          {
            key: 'monitor.xtdata.mode',
            label: 'XTData 模式',
            value: 'guardian_1m',
            restart_required: false,
            source: 'params.monitor',
          },
        ],
      },
      {
        key: 'guardian',
        title: 'Guardian',
        description: 'Guardian 股票阈值、网格间距和下单金额配置。',
        source: 'params.guardian',
        restart_required: false,
        items: [
          {
            key: 'guardian.stock.lot_amount',
            label: '单次买入金额',
            value: 1500,
            restart_required: false,
            source: 'params.guardian',
          },
        ],
      },
    ],
  },
})

test('readSystemConfigPayload unwraps axios responses', () => {
  const payload = createPayload()
  assert.deepEqual(readSystemConfigPayload({ data: payload }), payload)
})

test('buildBootstrapSections formats restart badges and scalar values', () => {
  const sections = buildBootstrapSections(createPayload())

  assert.equal(sections[0].key, 'mongodb')
  assert.equal(sections[0].restart_label, '保存后需重启相关服务')
  assert.equal(sections[0].items[0].value_label, '127.0.0.1')
  assert.equal(sections[0].items[1].value_label, '27,027')
})

test('buildSettingsSections formats arrays and booleans for display', () => {
  const sections = buildSettingsSections(createPayload())

  assert.equal(sections[0].items[0].value_label, 'guardian_1m')
  assert.equal(sections[1].items[0].value_label, '1,500')
  assert.equal(sections[1].restart_label, '保存后运行链按下次刷新生效')
})
