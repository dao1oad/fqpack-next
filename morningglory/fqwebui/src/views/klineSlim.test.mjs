import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

test('KlineSlim view exposes price guide toolbar entry and side panel layout', () => {
  const source = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')

  assert.match(source, /价格层级/)
  assert.match(source, /kline-slim-price-panel/)
  assert.match(source, /Guardian 倍量价格/)
  assert.match(source, /止盈价格/)
  assert.match(source, /price-guide-badge--guardian/)
  assert.match(source, /price-guide-badge--takeprofit/)
  assert.match(source, /guardianGuideRows\.filter\(\(row\) => row\.manual_enabled\)\.length/)
  assert.match(source, /v-model="guardianDraft\.buy_enabled\[row\.index\]"/)
  assert.doesNotMatch(source, /v-model="guardianDraft\.enabled"/)
})

test('KlineSlim keeps price guide and chanlun panels on the chart overlay instead of shrinking the chart area', () => {
  const source = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')

  assert.doesNotMatch(source, /has-side-panel/)
  assert.match(source, /class="kline-slim-price-panel kline-slim-overlay-panel"/)
  assert.match(source, /class="kline-slim-chanlun-panel kline-slim-overlay-panel"/)
})

test('KlineSlim toolbar toggles both price guide and chanlun panels from the same buttons', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')
  const scriptSource = fs.readFileSync(new URL('./js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(viewSource, /@click="togglePriceGuidePanel"/)
  assert.match(viewSource, /@click="toggleSubjectPanel"/)
  assert.match(viewSource, /@click="toggleChanlunStructurePanel"/)
  assert.match(viewSource, /:type="showChanlunStructurePanel \? 'primary' : 'default'"/)

  assert.match(scriptSource, /togglePriceGuidePanel\(\)/)
  assert.match(scriptSource, /toggleSubjectPanel\(\)/)
  assert.match(scriptSource, /toggleChanlunStructurePanel\(\)/)
  assert.match(scriptSource, /this\.showPriceGuidePanel = false/)
  assert.match(scriptSource, /this\.showSubjectPanel = false/)
  assert.match(scriptSource, /this\.showChanlunStructurePanel = false/)
})

test('KlineSlim sidebar renders source and category tags for shared pre_pool rows', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')
  const sidebarSource = fs.readFileSync(new URL('./js/kline-slim-sidebar.mjs', import.meta.url), 'utf8')

  assert.match(viewSource, /sidebar-item-tags/)
  assert.match(viewSource, /item\.sourceLabels/)
  assert.match(viewSource, /item\.categoryLabels/)
  assert.match(sidebarSource, /sourceLabels/)
  assert.match(sidebarSource, /categoryLabels/)
})

test('KlineSlim exposes a dedicated price-guide edit mode with drag-save handlers', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')
  const scriptSource = fs.readFileSync(new URL('./js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(viewSource, /画线编辑/)
  assert.match(viewSource, /@click="togglePriceGuideEditMode"/)
  assert.match(scriptSource, /priceGuideEditMode:/)
  assert.match(scriptSource, /togglePriceGuideEditMode\(\)/)
  assert.match(scriptSource, /handlePriceGuideDrag\(/)
  assert.match(scriptSource, /handlePriceGuideDragEnd\(/)
})

test('KlineSlim price guide panel exposes a save-and-activate action for all six price levels', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')
  const scriptSource = fs.readFileSync(new URL('./js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(viewSource, /保存并激活/)
  assert.match(viewSource, /@click="handleSaveAndActivatePriceGuides"/)
  assert.match(scriptSource, /handleSaveAndActivatePriceGuides\(\)/)
})

test('KlineSlim lets the body flow below a wrapping toolbar instead of relying on a fixed top offset', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8').replace(/\r/g, '')

  assert.equal(
    viewSource.includes('.kline-slim-main\n  display flex\n  flex-direction column'),
    true
  )
  assert.equal(
    viewSource.includes('.kline-slim-toolbar\n  position relative'),
    true
  )
  assert.equal(
    viewSource.includes('.kline-slim-body\n  position relative\n  display flex\n  flex 1'),
    true
  )
  assert.equal(viewSource.includes('.kline-slim-body\n  top 60px'), false)
  assert.equal(
    viewSource.includes('@media (max-width: 1200px)\n  .kline-slim-body\n    top 120px'),
    false
  )
})

test('KlineSlim exposes a subject settings overlay next to price guides', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')
  const scriptSource = fs.readFileSync(new URL('./js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(viewSource, /标的设置/)
  assert.match(viewSource, /kline-slim-subject-panel/)
  assert.match(viewSource, /基础配置/)
  assert.match(viewSource, /单标的仓位上限/)
  assert.match(viewSource, /按 buy lot 止损/)
  assert.equal(
    viewSource.indexOf('class="kline-slim-subject-panel kline-slim-overlay-panel"') <
      viewSource.indexOf('Guardian 倍量价格'),
    true
  )
  assert.match(scriptSource, /showSubjectPanel:/)
  assert.match(scriptSource, /subjectPanelState/)
})
