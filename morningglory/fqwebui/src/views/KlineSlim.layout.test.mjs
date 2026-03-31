import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./KlineSlim.vue', import.meta.url), 'utf8').replace(/\r/g, '')
const mediumLayoutStart = source.indexOf('@media (max-width: 1200px)')
const mediumLayoutEnd = source.indexOf('@media (max-width: 900px)')
const mediumLayoutBlock = source.slice(mediumLayoutStart, mediumLayoutEnd)

test('KlineSlim keeps overlay panels anchored to the chart content without side-panel offsets', () => {
  assert.equal(
    source.includes('.kline-slim-content\n  position relative\n  flex 1'),
    true
  )
  assert.equal(
    source.includes('.kline-slim-overlay-panel\n  position absolute\n  top 12px\n  left 12px'),
    true
  )
  assert.equal(
    source.includes('.kline-slim-chanlun-panel\n  right 12px'),
    true
  )
  assert.equal(
    source.includes('.kline-slim-subject-panel\n  left 12px'),
    true
  )
  assert.equal(source.includes('has-side-panel'), false)
})

test('KlineSlim toolbar stays close to the original single-row shell instead of a workbench title block', () => {
  assert.equal(
    source.includes('.kline-slim-toolbar\n  position relative\n  min-height 52px\n  padding 8px 12px\n  z-index 10\n  display flex'),
    true
  )
  assert.equal(source.includes('.kline-slim-toolbar\n  position relative'), true)
  assert.equal(source.includes('  align-items center'), true)
  assert.equal(source.includes('  justify-content space-between'), true)
  assert.equal(source.includes('.kline-slim-toolbar__header'), false)
  assert.equal(source.includes('<MyHeader />'), false)
  assert.equal(source.includes('<WorkbenchToolbar class="kline-slim-toolbar">'), false)
  assert.equal(source.includes('class="workbench-page-title"'), false)
})

test('KlineSlim medium breakpoint keeps the flow layout and only narrows the price panel', () => {
  assert.equal(
    mediumLayoutBlock.includes('.kline-slim-toolbar\n    align-items flex-start\n    flex-direction column'),
    true
  )
  assert.equal(
    mediumLayoutBlock.includes('.toolbar-right\n    justify-content flex-start'),
    true
  )
  assert.equal(
    mediumLayoutBlock.includes('.kline-slim-price-panel\n    width 348px'),
    true
  )
  assert.equal(
    mediumLayoutBlock.includes('.kline-slim-subject-panel\n    width 392px'),
    true
  )
  assert.equal(mediumLayoutBlock.includes('has-side-panel'), false)
  assert.equal(mediumLayoutBlock.includes('.kline-slim-body\n    top 120px'), false)
  assert.equal(
    mediumLayoutBlock.includes('.subject-panel-base-row\n    grid-template-columns 1fr'),
    true
  )
  assert.equal(
    mediumLayoutBlock.includes('.price-panel-row-editor\n    grid-column 1 / -1'),
    true
  )
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

test('KlineSlim local section titles and empty state stay out of the shared workbench title wrappers', () => {
  assert.equal(source.includes('workbench-panel__title'), false)
  assert.equal(source.includes('class="workbench-empty kline-slim-empty"'), false)
  assert.equal(source.includes('class="kline-slim-empty"'), true)
})
