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

test('KlineSlim sidebar uses compact two-line summaries instead of stacked tags', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')
  const sidebarSource = fs.readFileSync(new URL('./js/kline-slim-sidebar.mjs', import.meta.url), 'utf8')

  assert.match(viewSource, /item\.titleLabel/)
  assert.match(viewSource, /item\.secondaryLabel/)
  assert.doesNotMatch(viewSource, /sidebar-item-tags/)
  assert.match(sidebarSource, /titleLabel/)
  assert.match(sidebarSource, /secondaryLabel/)
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

test('KlineSlim exposes a reset viewport control that returns the chart to auto mode', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')
  const scriptSource = fs.readFileSync(new URL('./js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(viewSource, /重置视图/)
  assert.match(viewSource, /@click="resetChartViewport"/)
  assert.match(scriptSource, /resetChartViewport\(\)/)
  assert.match(scriptSource, /this\.chartViewport = createKlineSlimViewportState\(\)/)
  assert.match(scriptSource, /this\.resetViewportOnNextRender = true/)
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

test('KlineSlim subject panel removes category editing, refresh noise and source toggle', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8').replace(/\r/g, '')
  const scriptSource = fs.readFileSync(new URL('./js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(viewSource, /保存基础配置与上限/)
  assert.equal(viewSource.includes('subject-panel-header-summary'), false)
  assert.equal(viewSource.includes('@click="loadSubjectPanelDetail({ force: true })"'), false)
  assert.equal(viewSource.includes('v-model.trim="subjectPanelState.mustPoolDraft.category"'), false)
  assert.equal(viewSource.includes('右侧直接改 must_pool.category'), false)
  assert.equal(viewSource.includes('当前分类'), false)
  assert.equal(viewSource.includes('subjectPanelState.positionLimitDraft.use_default'), false)
  assert.equal(viewSource.includes('关闭“默认”后生效'), false)
  assert.equal(viewSource.includes('覆盖值'), false)
  assert.equal(viewSource.includes('留空时沿用仓位管理默认值'), false)
  assert.match(viewSource, /单标的上限设置/)
  assert.match(viewSource, /当前来源/)
  assert.equal(scriptSource.includes('use_default'), false)
  assert.match(viewSource, /class="subject-panel-base-row"/)
  assert.match(viewSource, /class="subject-panel-limit-summary"/)
})

test('KlineSlim subject panel keeps readable buy-lot stoploss rows after header cleanup', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8').replace(/\r/g, '')

  assert.match(viewSource, /row\.buyLotDisplayLabel/)
  assert.match(viewSource, /row\.buyLotMetaLabel/)
  assert.match(viewSource, /row\.buyLotIdLabel/)
  assert.match(viewSource, /class="subject-panel-stoploss-head"/)
  assert.match(viewSource, /class="subject-panel-stoploss-title-wrap"/)
  assert.match(viewSource, /class="subject-panel-stoploss-id"/)
  assert.equal(viewSource.includes('.kline-slim-subject-panel\n  left 12px\n  width 436px'), true)
  assert.equal(viewSource.includes('.subject-panel-stoploss-row\n  display flex\n  flex-direction column'), true)
})

test('KlineSlim price guide panel removes refresh noise and keeps full color badges', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8').replace(/\r/g, '')

  assert.equal(viewSource.includes('@click="loadSubjectPriceDetail({ force: true })"'), false)
  assert.equal(viewSource.includes('图上默认展示 Guardian / 止盈横线，可在 legend 中关闭'), false)
  assert.equal(viewSource.includes('高到低展示，蓝 / 红 / 绿实线'), false)
  assert.equal(viewSource.includes('低到高展示，蓝 / 红 / 绿虚线'), false)
  assert.equal(viewSource.includes('<span class="price-panel-chip">{{ currentPeriod }}</span>'), false)
  assert.match(viewSource, /\.price-guide-badge/)
  assert.equal(viewSource.includes('min-width 68px'), true)
  assert.equal(viewSource.includes('white-space nowrap'), true)
})

test('KlineSlim price guide rows give the color badge its own layout column', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8').replace(/\r/g, '')

  assert.equal(viewSource.includes('class="price-panel-row-main"'), false)
  assert.match(viewSource, /class="price-guide-badge"/)
  assert.match(viewSource, /class="price-panel-row-meta"/)
  assert.match(viewSource, /\.price-panel-row\n  display grid\n  grid-template-columns max-content minmax\(0, 1fr\) auto/)
})

test('KlineSlim sidebar shows runtime position summary for holding rows', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')

  assert.match(viewSource, /item\.titleLabel/)
  assert.match(viewSource, /item\.secondaryLabel/)
  assert.doesNotMatch(viewSource, /item\.runtimePrimaryLabel/)
  assert.doesNotMatch(viewSource, /item\.runtimeSecondaryLabel/)
  assert.doesNotMatch(viewSource, /sidebar-item-tags/)
})
