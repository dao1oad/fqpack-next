import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

test('KlineSlim keeps the price editor side panel but removes the duplicate 价格层级 trigger copy', () => {
  const source = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')

  assert.doesNotMatch(source, />\s*价格层级\s*<\/el-button>/)
  assert.doesNotMatch(source, /price-panel-title">价格层级</)
  assert.doesNotMatch(source, /暂无价格层级配置/)
  assert.match(source, /画线编辑/)
  assert.match(source, /kline-slim-price-panel/)
  assert.match(source, /Guardian 倍量价格/)
  assert.match(source, /止盈价格/)
  assert.match(source, /price-guide-badge--guardian/)
  assert.match(source, /price-guide-badge--takeprofit/)
  assert.match(source, /guardianGuideRows\.filter\(\(row\) => row\.manual_enabled\)\.length/)
  assert.match(source, /:model-value="guardianDraft\.buy_enabled\[row\.index\]"/)
  assert.doesNotMatch(source, /v-model="guardianDraft\.enabled"/)
})

test('KlineSlim keeps price guide and chanlun panels on the chart overlay instead of shrinking the chart area', () => {
  const source = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')

  assert.doesNotMatch(source, /has-side-panel/)
  assert.match(source, /class="kline-slim-price-panel kline-slim-overlay-panel"/)
  assert.match(source, /class="kline-slim-chanlun-panel kline-slim-overlay-panel"/)
})

test('KlineSlim toolbar keeps only draw-edit, subject and chanlun toggles for overlay panels', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')
  const scriptSource = fs.readFileSync(new URL('./js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(viewSource, /@click="toggleSubjectPanel"/)
  assert.match(viewSource, /@click="toggleChanlunStructurePanel"/)
  assert.match(viewSource, /@click="togglePriceGuideEditMode"/)
  assert.match(viewSource, /:type="showChanlunStructurePanel \? 'primary' : 'default'"/)

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
  assert.match(
    scriptSource,
    /if \(this\.priceGuideEditMode\) \{[\s\S]*this\.closePriceGuidePanel\(\)/
  )
  assert.match(scriptSource, /handlePriceGuideDrag\(/)
  assert.match(scriptSource, /handlePriceGuideDragEnd\(/)
})

test('KlineSlim price guide panel separates price saving from switch control', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')
  const scriptSource = fs.readFileSync(new URL('./js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(viewSource, />\s*保存\s*<\/el-button>/)
  assert.match(viewSource, /@click="handleSavePriceGuides"/)
  assert.match(viewSource, /Guardian 倍量价格/)
  assert.match(viewSource, /止盈价格/)
  assert.match(viewSource, /@click="handleGuardianGuideEnabledAll\(true\)"/)
  assert.match(viewSource, /@click="handleGuardianGuideEnabledAll\(false\)"/)
  assert.match(viewSource, /@click="handleTakeprofitGuideEnabledAll\(true\)"/)
  assert.match(viewSource, /@click="handleTakeprofitGuideEnabledAll\(false\)"/)
  assert.match(viewSource, /@change="handleGuardianGuideEnabledChange\(row\.index, \$event\)"/)
  assert.match(viewSource, /@change="handleTakeprofitGuideEnabledChange\(row\.level, \$event\)"/)
  assert.doesNotMatch(viewSource, /保存并激活/)
  assert.doesNotMatch(viewSource, /保存 Guardian/)
  assert.doesNotMatch(viewSource, /保存止盈/)
  assert.match(scriptSource, /handleSavePriceGuides\(\)/)
  assert.match(scriptSource, /handleGuardianGuideEnabledChange\(index, enabled\)/)
  assert.match(scriptSource, /handleTakeprofitGuideEnabledChange\(level, enabled\)/)
  assert.match(scriptSource, /handleGuardianGuideEnabledAll\(enabled\)/)
  assert.match(scriptSource, /handleTakeprofitGuideEnabledAll\(enabled\)/)
})

test('KlineSlim bulk price guide toggles sync runtime state while row toggles stay config-only', () => {
  const scriptSource = fs.readFileSync(new URL('./js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(
    scriptSource,
    /handleGuardianGuideEnabledAll\(enabled\)[\s\S]*syncRuntimeState: true/
  )
  assert.match(
    scriptSource,
    /handleTakeprofitGuideEnabledAll\(enabled\)[\s\S]*syncRuntimeState: true/
  )
})

test('KlineSlim price guide panel shows read-only runtime states for Guardian and takeprofit', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')
  const scriptSource = fs.readFileSync(new URL('./js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(viewSource, /运行态 \{\{ guardianRuntimeActiveCount \}\}\/3/)
  assert.match(viewSource, /运行态 \{\{ takeprofitRuntimeActiveCount \}\}\/3/)
  assert.match(viewSource, /最近命中 \{\{ guardianLastHitLabel \}\}/)
  assert.match(viewSource, /最近命中价/)
  assert.match(viewSource, /运行态 \{\{ row\.runtimeStateLabel \}\}/)
  assert.match(scriptSource, /guardianLastHitLabel\(\)/)
  assert.match(scriptSource, /guardianRuntimeActiveCount\(\)/)
  assert.match(scriptSource, /takeprofitRuntimeActiveCount\(\)/)
  assert.match(scriptSource, /runtime_active:/)
  assert.doesNotMatch(viewSource, />\s*命中价\s*</)
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
  assert.match(viewSource, /单标的上限设置/)
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

  assert.match(viewSource, />\s*保存\s*</)
  assert.equal(viewSource.includes('保存基础配置与上限'), false)
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
  assert.match(viewSource, /当前生效/)
  assert.equal(viewSource.includes('单标的仓位上限'), false)
  assert.equal(viewSource.includes('subject-panel-limit-row'), false)
  assert.equal(scriptSource.includes('use_default'), false)
  assert.match(viewSource, /class="subject-panel-base-row"/)
  assert.match(viewSource, /v-model="subjectPanelState\.positionLimitDraft\.limit"/)
})

test('KlineSlim subject panel removes misleading must-pool note and redundant limit prose', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8').replace(/\r/g, '')

  assert.equal(viewSource.includes('price-panel-section-note">must_pool'), false)
  assert.match(viewSource, /当前生效/)
  assert.match(viewSource, /市值/)
  assert.match(viewSource, /已阻断买入|允许买入/)
  assert.equal(viewSource.includes('系统默认值'), false)
  assert.equal(viewSource.includes('当前来源'), false)
  assert.equal(viewSource.includes('输入当前希望生效的单标的上限'), false)
})

test('KlineSlim subject panel lifts base config summaries out of the position-limit card', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8').replace(/\r/g, '')

  assert.match(
    viewSource,
    /<span class="price-panel-section-title">基础配置<\/span>[\s\S]*<div class="price-panel-summary">[\s\S]*当前止损[\s\S]*当前上限[\s\S]*市值[\s\S]*(?:已阻断买入|允许买入)/
  )
  assert.equal(
    /<span class="subject-panel-field__label">单标的上限设置<\/span>[\s\S]*<div class="subject-panel-inline-chips">/.test(viewSource),
    false
  )
})

test('KlineSlim subject panel uses a two-column base grid inside the narrow overlay', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8').replace(/\r/g, '')

  assert.equal(
    viewSource.includes('.subject-panel-base-row\n  display grid\n  grid-template-columns repeat(2, minmax(0, 1fr))'),
    true
  )
  assert.equal(viewSource.includes('grid-template-columns repeat(4, minmax(0, 1fr))'), false)
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
  assert.equal(viewSource.includes('待机'), false)
  assert.equal(viewSource.includes('待命'), false)
  assert.equal(viewSource.includes('布防'), false)
  assert.equal(viewSource.includes('仅展示'), false)
  assert.equal(viewSource.includes('price-panel-footer'), false)
  assert.match(viewSource, /已开启 \{\{ takeprofitGuideRows\.filter\(\(row\) => row\.manual_enabled\)\.length \}\}\/3/)
  assert.match(
    viewSource,
    /<span class="price-panel-section-title">止盈价格<\/span>[\s\S]*<div class="price-panel-section-actions">[\s\S]*handleTakeprofitGuideEnabledAll\(true\)[\s\S]*handleTakeprofitGuideEnabledAll\(false\)/
  )
  assert.match(
    viewSource,
    /<span class="price-panel-section-title">止盈价格<\/span>[\s\S]*<div class="price-panel-summary">[\s\S]*takeprofitGuideRows\.filter\(\(row\) => row\.manual_enabled\)\.length[\s\S]*takeprofitRuntimeActiveCount/
  )
  assert.match(viewSource, /\.price-guide-badge/)
  assert.equal(viewSource.includes('min-width 68px'), true)
  assert.equal(viewSource.includes('white-space nowrap'), true)
})

test('KlineSlim price guide inputs use three-decimal precision for editing', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')
  const scriptSource = fs.readFileSync(new URL('./js/kline-slim.js', import.meta.url), 'utf8')
  const stepMatches = viewSource.match(/:step="0\.001"/g) || []
  const precisionMatches = viewSource.match(/:precision="3"/g) || []

  assert.equal(stepMatches.length, 2)
  assert.equal(precisionMatches.length, 2)
  assert.match(
    scriptSource,
    /function resolveLatestClosePrice\(mainData\)\s*\{[\s\S]*lastClose\.toFixed\(3\)/
  )
})

test('KlineSlim exposes 1d as a supported chanlun period', async () => {
  const periodsModule = await import('./js/kline-slim-chanlun-periods.mjs')

  assert.equal(periodsModule.SUPPORTED_CHANLUN_PERIODS.includes('1d'), true)
  assert.equal(periodsModule.normalizeChanlunPeriod('1d'), '1d')
  assert.equal(periodsModule.PERIOD_DURATION_MS['1d'], 24 * 60 * 60 * 1000)
})

test('KlineSlim price guide rows give the color badge its own layout column', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8').replace(/\r/g, '')

  assert.equal(viewSource.includes('class="price-panel-row-main"'), false)
  assert.equal(viewSource.includes('price-panel-row-title'), false)
  assert.equal(viewSource.includes('price-panel-row-subtitle'), false)
  assert.equal(viewSource.includes('图上 G-'), false)
  assert.equal(viewSource.includes('图上 TP-'), false)
  assert.match(viewSource, /class="price-guide-badge"/)
  assert.equal(viewSource.includes('class="price-panel-row-meta"'), false)
  assert.match(viewSource, /\.price-panel-row\n  display grid\n  grid-template-columns max-content auto/)
})

test('KlineSlim sidebar shows runtime position summary for holding rows', () => {
  const viewSource = fs.readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8')

  assert.match(viewSource, /item\.titleLabel/)
  assert.match(viewSource, /item\.secondaryLabel/)
  assert.doesNotMatch(viewSource, /item\.runtimePrimaryLabel/)
  assert.doesNotMatch(viewSource, /item\.runtimeSecondaryLabel/)
  assert.doesNotMatch(viewSource, /sidebar-item-tags/)
})
