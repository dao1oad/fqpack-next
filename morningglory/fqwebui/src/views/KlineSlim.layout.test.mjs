import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8').replace(/\r/g, '')
const mediumLayoutStart = source.indexOf('@media (max-width: 1200px)')
const mediumLayoutEnd = source.indexOf('@media (max-width: 900px)')
const mediumLayoutBlock = source.slice(mediumLayoutStart, mediumLayoutEnd)

test('KlineSlim unifies CLX selection, chart and signal workbench without page-level overflow', () => {
  assert.equal(
    source.includes('.kline-slim-body\n  position relative\n  display grid\n  grid-template-columns 280px minmax(0, 1fr)'),
    true
  )
  assert.equal(
    source.includes('.kline-slim-body.has-clx-workbench\n  grid-template-columns 320px minmax(0, 1fr) clamp(320px, 25vw, 360px)'),
    true
  )
  assert.match(source, /'has-clx-screening': isClxScreeningMode/)
  assert.match(source, /'has-clx-workbench': showClxWorkbench/)
  assert.match(source, /<ClxSelectionPanel[\s\S]*v-if="isClxScreeningMode"/)
  assert.match(source, /overflow hidden/)
  assert.doesNotMatch(source, /minmax\(720px, 1fr\)/)
  assert.match(
    source,
    /<aside\s+v-if="showClxWorkbench"\s+class="kline-slim-clx-workbench"/
  )
  assert.doesNotMatch(source, /kline-slim-clx-workbench kline-slim-overlay-panel/)
  assert.match(source, /\.kline-slim-clx-workbench\n  position sticky\n  top 0\n  align-self stretch/)
  assert.match(source, /\.kline-slim-clx-workbench[\s\S]*height 100%[\s\S]*overflow hidden/)
  assert.doesNotMatch(source, /\.kline-slim-clx-workbench\n  right 12px/)
  assert.doesNotMatch(source, /\.kline-slim-clx-workbench[\s\S]*resize horizontal/)
  assert.match(source, /class="kline-slim-price-panel kline-slim-overlay-panel"/)
  assert.match(source, /class="kline-slim-chanlun-panel kline-slim-overlay-panel"/)
  assert.match(source, /\.kline-slim-overlay-panel\n  position absolute\n  top 12px\n  left 12px/)
  assert.equal(
    source.includes('.kline-slim-chanlun-panel\n  right 12px'),
    true
  )
  assert.equal(source.includes('.kline-slim-subject-panel\n  left 12px'), false)
  assert.equal(source.includes('has-side-panel'), false)
})

test('KlineSlim medium breakpoint keeps the CLX workbench in its own grid column', () => {
  assert.equal(
    mediumLayoutBlock.includes('.kline-slim-toolbar\n    align-items flex-start\n    flex-direction column'),
    true
  )
  assert.equal(
    mediumLayoutBlock.includes('.toolbar-right\n    justify-content flex-start'),
    true
  )
  assert.equal(
    mediumLayoutBlock.includes('.kline-slim-price-panel\n    width 680px'),
    true
  )
  assert.equal(mediumLayoutBlock.includes('.kline-slim-subject-panel\n    width 392px'), false)
  assert.equal(mediumLayoutBlock.includes('has-side-panel'), false)
  assert.equal(mediumLayoutBlock.includes('.kline-slim-body\n    top 120px'), false)
  assert.equal(mediumLayoutBlock.includes('.subject-panel-base-row\n    grid-template-columns 1fr'), false)
  assert.equal(
    mediumLayoutBlock.includes('.price-panel-row-editor\n    grid-column 1 / -1'),
    true
  )
  assert.equal(
    mediumLayoutBlock.includes('.kline-slim-body.has-clx-workbench\n    grid-template-columns 280px minmax(0, 1fr) 320px'),
    true
  )
  assert.doesNotMatch(mediumLayoutBlock, /\.kline-slim-clx-workbench[\s\S]*position (?:absolute|fixed)/)
})

test('KlineSlim price guide rows no longer reserve standalone title or subtitle columns', () => {
  assert.equal(source.includes('.price-panel-row-title'), false)
  assert.equal(source.includes('.price-panel-row-subtitle'), false)
  assert.equal(source.includes('class="price-panel-row-main"'), false)
})

test('KlineSlim price rows reserve a dedicated grid column for the color badge', () => {
  assert.equal(
    source.includes('.price-panel-row\n  display grid\n  grid-template-columns max-content auto'),
    true
  )
  assert.equal(
    source.includes('.price-panel-row-editor--multi\n  flex-wrap nowrap'),
    true
  )
})

test('KlineSlim sidebar keeps each item to a title line and one summary line', () => {
  assert.equal(
    source.includes('.sidebar-item-meta\n  display flex\n  flex-direction column\n  gap 4px'),
    true
  )
  assert.equal(
    source.includes('.sidebar-item-subtitle\n  font-size 12px\n  line-height 1.35\n  color #94a3b8'),
    true
  )
  assert.equal(source.includes('.sidebar-item-runtime'), false)
  assert.equal(source.includes('.sidebar-item-tags'), false)
})
