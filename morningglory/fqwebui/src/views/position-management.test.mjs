import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildConfigSections,
  readDashboardPayload,
  buildRuleMatrix,
  buildStatePanel,
} from './positionManagement.mjs'

const createDashboard = () => ({
  config: {
    updated_at: '2026-03-07T11:59:00+08:00',
    updated_by: 'pytest',
    thresholds: {
      allow_open_min_bail: 800000,
      holding_only_min_bail: 100000,
    },
    inventory: [
      {
        key: 'allow_open_min_bail',
        label: '允许开新仓最低保证金',
        value: 800000,
        editable: true,
        group: 'editable_thresholds',
        description: '超过该阈值时进入 ALLOW_OPEN。',
      },
      {
        key: 'holding_only_min_bail',
        label: '仅允许持仓内买入最低保证金',
        value: 100000,
        editable: true,
        group: 'editable_thresholds',
        description: '超过该阈值但未达到开仓阈值时进入 HOLDING_ONLY。',
      },
      {
        key: 'state_stale_after_seconds',
        label: '状态过期秒数',
        value: 15,
        editable: false,
        group: 'policy_defaults',
        description: '当前仅为代码默认值，本页只读展示。',
      },
      {
        key: 'default_state',
        label: 'stale 默认状态',
        value: 'HOLDING_ONLY',
        editable: false,
        group: 'policy_defaults',
        description: '当前仅为代码默认值，本页只读展示。',
      },
      {
        key: 'xtquant.account_type',
        label: 'XT 账户类型',
        value: 'CREDIT',
        editable: false,
        group: 'system_connection',
        description: '仓位管理查询信用详情时必须为 CREDIT。',
      },
    ],
  },
  state: {
    raw_state: 'ALLOW_OPEN',
    effective_state: 'HOLDING_ONLY',
    stale: true,
    available_bail_balance: 865432.12,
    available_amount: 102345.67,
    fetch_balance: 92345.67,
    total_asset: 1432100,
    market_value: 1210000,
    total_debt: 530000,
    evaluated_at: '2026-03-07T12:00:00+08:00',
    last_query_ok: '2026-03-07T12:00:00+08:00',
    data_source: 'xtquant',
    matched_rule: {
      code: 'stale_default_state',
      title: '状态已过期，按默认 HOLDING_ONLY 处理',
      detail: 'evaluated_at 超过 15 秒未刷新，raw_state=ALLOW_OPEN，effective_state=HOLDING_ONLY。',
    },
  },
  rule_matrix: [
    {
      key: 'buy_new',
      label: '新标的买入',
      allowed: false,
      reason_code: 'new_position_blocked',
      reason_text: '当前状态不允许开新仓',
    },
    {
      key: 'buy_holding',
      label: '已持仓标的买入',
      allowed: true,
      reason_code: 'holding_buy_allowed',
      reason_text: '当前状态允许买入已持仓标的',
    },
    {
      key: 'sell',
      label: '卖出',
      allowed: true,
      reason_code: 'sell_allowed',
      reason_text: '当前状态允许卖出持仓',
    },
  ],
})

test('buildConfigSections groups editable thresholds and readonly inventories', () => {
  const sections = buildConfigSections(createDashboard())

  assert.deepEqual(
    sections.map((section) => ({
      key: section.key,
      count: section.items.length,
    })),
    [
      { key: 'editable_thresholds', count: 2 },
      { key: 'policy_defaults', count: 2 },
      { key: 'system_connection', count: 1 },
    ],
  )
  assert.equal(sections[0].items[0].value_label, '800,000.00')
  assert.equal(sections[1].items[0].value_label, '15 秒')
  assert.equal(sections[2].items[0].value_label, 'CREDIT')
})

test('buildStatePanel exposes state labels, stale badge and asset metrics', () => {
  const panel = buildStatePanel(createDashboard())
  const stats = Object.fromEntries(panel.stats.map((item) => [item.key, item.value_label]))

  assert.equal(panel.hero.effective_state_label, '仅允许持仓内买入')
  assert.equal(panel.hero.raw_state_label, '允许开新仓')
  assert.equal(panel.hero.stale_label, '已过期')
  assert.equal(panel.hero.matched_rule_title, '状态已过期，按默认 HOLDING_ONLY 处理')
  assert.equal(stats.available_bail_balance, '865,432.12')
  assert.equal(stats.total_asset, '1,432,100.00')
})

test('buildRuleMatrix keeps decision order and readable allow status', () => {
  const rows = buildRuleMatrix(createDashboard())

  assert.deepEqual(
    rows.map((row) => ({
      key: row.key,
      allowed_label: row.allowed_label,
      reason_text: row.reason_text,
    })),
    [
      {
        key: 'buy_new',
        allowed_label: '拒绝',
        reason_text: '当前状态不允许开新仓',
      },
      {
        key: 'buy_holding',
        allowed_label: '允许',
        reason_text: '当前状态允许买入已持仓标的',
      },
      {
        key: 'sell',
        allowed_label: '允许',
        reason_text: '当前状态允许卖出持仓',
      },
    ],
  )
})

test('readDashboardPayload unwraps axios responses instead of treating request config as dashboard config', () => {
  const payload = createDashboard()
  const response = {
    data: payload,
    status: 200,
    config: {
      url: '/api/position-management/dashboard',
      method: 'get',
    },
  }

  assert.deepEqual(readDashboardPayload(response), payload)
})
