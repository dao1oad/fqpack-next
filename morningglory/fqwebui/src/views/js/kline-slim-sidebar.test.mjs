import test from 'node:test'
import assert from 'node:assert/strict'

import { buildSidebarSections, normalizeSidebarItem } from './kline-slim-sidebar.mjs'

test('normalizeSidebarItem formats holding runtime summary like subject-management runtime column', () => {
  const item = normalizeSidebarItem({
    symbol: 'sh600000',
    name: '浦发银行',
    quantity: 500,
    amount: 123456.7,
  })

  assert.equal(item.runtimePrimaryLabel, '仓位 12.35 万')
  assert.equal(item.runtimeSecondaryLabel, '持仓 500 股')
})

test('buildSidebarSections only adds runtime summaries to holding rows', () => {
  const sections = buildSidebarSections({
    holdings: [{ symbol: 'sh600000', name: '浦发银行', quantity: 500, amount: 123456.7 }],
    mustPools: [{ symbol: 'sh601398', name: '工商银行', category: '银行' }],
    expandedKey: 'holding',
  })

  const holdingSection = sections.find((section) => section.key === 'holding')
  const mustPoolSection = sections.find((section) => section.key === 'must_pool')

  assert.equal(holdingSection.items[0].runtimePrimaryLabel, '仓位 12.35 万')
  assert.equal(holdingSection.items[0].runtimeSecondaryLabel, '持仓 500 股')
  assert.equal(mustPoolSection.items[0].runtimePrimaryLabel, '')
  assert.equal(mustPoolSection.items[0].runtimeSecondaryLabel, '')
})
