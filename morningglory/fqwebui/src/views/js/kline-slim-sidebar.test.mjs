import test from 'node:test'
import assert from 'node:assert/strict'

import { buildSidebarSections, normalizeSidebarItem } from './kline-slim-sidebar.mjs'

test('normalizeSidebarItem formats holding runtime summary like subject-management runtime column', () => {
  const item = normalizeSidebarItem({
    symbol: 'sh600000',
    name: '浦发银行',
    quantity: 500,
    amount: 123456.7,
  }, { sectionKey: 'holding' })

  assert.equal(item.titleLabel, '浦发银行(600000)')
  assert.equal(item.secondaryLabel, '仓位 12.35 万')
})

test('buildSidebarSections keeps every section to a compact two-line summary', () => {
  const sections = buildSidebarSections({
    holdings: [{ symbol: 'sh600000', name: '浦发银行', quantity: 500, amount: 123456.7 }],
    mustPools: [{ symbol: 'sh601398', name: '工商银行', category: '银行' }],
    stockPools: [{ symbol: 'sz000001', name: '平安银行', provider: 'xgb' }],
    expandedKey: 'holding',
  })

  const holdingSection = sections.find((section) => section.key === 'holding')
  const mustPoolSection = sections.find((section) => section.key === 'must_pool')
  const stockPoolSection = sections.find((section) => section.key === 'stock_pools')

  assert.equal(holdingSection.items[0].titleLabel, '浦发银行(600000)')
  assert.equal(holdingSection.items[0].secondaryLabel, '仓位 12.35 万')
  assert.equal(mustPoolSection.items[0].titleLabel, '工商银行(601398)')
  assert.equal(mustPoolSection.items[0].secondaryLabel, '银行')
  assert.equal(stockPoolSection.items[0].titleLabel, '平安银行(000001)')
  assert.equal(stockPoolSection.items[0].secondaryLabel, 'xgb')
})

test('buildSidebarSections sorts holding items by position size descending and keeps equal amounts stable', () => {
  const sections = buildSidebarSections({
    holdings: [
      { symbol: 'sz000001', name: '平安银行', amount: 100000 },
      { symbol: 'sh600036', name: '招商银行', position_amount: 300000 },
      { symbol: 'sh601398', name: '工商银行', market_value: 300000 },
      { symbol: 'sz300750', name: '宁德时代', amount: 'not-a-number' }
    ],
    expandedKey: 'holding'
  })

  const holdingSection = sections.find((section) => section.key === 'holding')

  assert.deepEqual(
    holdingSection.items.map((item) => item.titleLabel),
    ['招商银行(600036)', '工商银行(601398)', '平安银行(000001)', '宁德时代(300750)']
  )
})
