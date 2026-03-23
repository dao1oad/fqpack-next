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

test('KlineSlim price panel titles stay horizontal with ellipsis', () => {
  assert.equal(
    source.includes('.price-panel-row-title\n  font-size 13px\n  color #f8fafc\n  font-weight 600\n  overflow hidden\n  text-overflow ellipsis\n  white-space nowrap'),
    true
  )
  assert.equal(
    source.includes('.price-panel-row-subtitle\n  font-size 12px\n  color #94a3b8\n  overflow hidden\n  text-overflow ellipsis\n  white-space nowrap'),
    true
  )
})

test('KlineSlim price rows reserve a dedicated grid column for the color badge', () => {
  assert.equal(
    source.includes('.price-panel-row\n  display grid\n  grid-template-columns max-content minmax(0, 1fr) auto'),
    true
  )
})
