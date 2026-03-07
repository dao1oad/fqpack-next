import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  buildSidebarSections,
  getSidebarDeleteBehavior,
  normalizeSidebarItem,
  getSidebarCode6,
  normalizeReasonItems,
  getReasonPanelMessage,
  toggleSidebarExpandedKey
} from '../src/views/js/kline-slim-sidebar.mjs'

test('buildSidebarSections keeps fixed order and sidebar metadata', () => {
  const sections = buildSidebarSections({
    holdings: [{ symbol: 'sh600000', code: '600000', name: 'alpha' }],
    mustPools: [{ symbol: 'sz000001', code: '000001', name: 'beta' }],
    stockPools: [{ symbol: 'sz000002', code: '000002', name: 'gamma' }],
    prePools: [{ symbol: 'sz000003', code: '000003', name: 'delta' }]
  })

  assert.deepEqual(
    sections.map(section => section.key),
    ['holding', 'must_pool', 'stock_pools', 'stock_pre_pools']
  )
  assert.deepEqual(
    sections.map(section => section.label),
    ['持仓股', 'must_pool', 'stock_pools', 'stock_pre_pools']
  )
  assert.equal(sections[0].expanded, true)
  assert.equal(sections[1].expanded, false)
  assert.equal(sections[0].deletable, false)
  assert.equal(sections[1].deletable, true)
})

test('toggleSidebarExpandedKey keeps at most one section expanded', () => {
  assert.equal(toggleSidebarExpandedKey('holding', 'must_pool'), 'must_pool')
  assert.equal(toggleSidebarExpandedKey('must_pool', 'must_pool'), '')
  assert.equal(toggleSidebarExpandedKey('', 'stock_pools'), 'stock_pools')
})

test('getSidebarDeleteBehavior describes delete api and refresh scope', () => {
  assert.equal(getSidebarDeleteBehavior('holding'), null)
  assert.deepEqual(getSidebarDeleteBehavior('must_pool'), {
    method: 'deleteFromStockMustPoolsByCode',
    refreshKeys: ['must_pool'],
    confirmText: '确定从 must_pool 删除该标的吗？'
  })
  assert.deepEqual(getSidebarDeleteBehavior('stock_pools'), {
    method: 'deleteFromStockPoolsByCode',
    refreshKeys: ['stock_pools', 'must_pool'],
    confirmText: '确定从 stock_pools 删除该标的吗？'
  })
  assert.deepEqual(getSidebarDeleteBehavior('stock_pre_pools'), {
    method: 'deleteFromStockPrePoolsByCode',
    refreshKeys: ['stock_pre_pools'],
    confirmText: '确定从 stock_pre_pools 删除该标的吗？'
  })
})

test('normalizeSidebarItem fills symbol and code6 from code', () => {
  const item = normalizeSidebarItem({ code: '000001', name: 'pingan' })

  assert.deepEqual(item, {
    code: '000001',
    code6: '000001',
    symbol: 'sz000001',
    name: 'pingan',
    raw: { code: '000001', name: 'pingan' }
  })
  assert.equal(getSidebarCode6({ symbol: 'sh600000' }), '600000')
})

test('normalizeReasonItems unwraps api payload and keeps required fields', () => {
  const items = normalizeReasonItems({
    data: {
      items: [
        {
          date: '2026-03-05',
          time: '09:31',
          provider: 'xgb',
          plate_name: 'robotics',
          plate_reason: 'plate reason',
          stock_reason: 'stock reason'
        },
        { foo: 'bar' }
      ]
    }
  })

  assert.deepEqual(items, [
    {
      date: '2026-03-05',
      time: '09:31',
      provider: 'xgb',
      plate_name: 'robotics',
      plate_reason: 'plate reason',
      stock_reason: 'stock reason'
    }
  ])
})

test('getReasonPanelMessage returns loading error and empty states', () => {
  assert.equal(getReasonPanelMessage({ loading: true, error: '', items: [] }), '加载中...')
  assert.equal(
    getReasonPanelMessage({ loading: false, error: '加载失败', items: [] }),
    '加载失败'
  )
  assert.equal(getReasonPanelMessage({ loading: false, error: '', items: [] }), '暂无热门记录')
  assert.equal(getReasonPanelMessage({ loading: false, error: '', items: [{ date: '2026-03-05' }] }), '')
})

test('KlineSlim uses a wider popover and stock reason column', async () => {
  const content = await readFile(new URL('../src/views/KlineSlim.vue', import.meta.url), 'utf8')

  assert.match(content, /:width="860"/)
  assert.match(
    content,
    /grid-template-columns 110px 72px 120px minmax\(140px, 1fr\) minmax\(0, 2fr\)/
  )
})

test('KlineSlim constrains long reason text inside the popover grid cell', async () => {
  const content = await readFile(new URL('../src/views/KlineSlim.vue', import.meta.url), 'utf8')

  assert.match(content, /\.reason-table-row > span/)
  assert.match(content, /min-width 0/)
  assert.match(content, /overflow-wrap anywhere/)
})

test('KlineSlim renders accordion toggle, stacked name/code, and delete affordance', async () => {
  const content = await readFile(new URL('../src/views/KlineSlim.vue', import.meta.url), 'utf8')

  assert.match(content, /@click="toggleSidebarSection\(section.key\)"/)
  assert.match(content, /v-show="section.expanded"/)
  assert.match(content, /class="sidebar-item-meta"/)
  assert.match(content, /class="sidebar-item-title"/)
  assert.match(content, /class="sidebar-item-subtitle"/)
  assert.match(content, /v-if="section.deletable"/)
  assert.match(content, /@confirm="deleteSidebarItem\(section.key, item\)"/)
})
