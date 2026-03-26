import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolveDailyScreeningClsModelPresentation } from './dailyScreeningPage.mjs'

const modelSignalListSource = readFileSync(new URL('./ModelSignalList.vue', import.meta.url), 'utf8')

test('ModelSignalList restores stock model context columns and keeps single-line price summary', () => {
  assert.match(modelSignalListSource, /stock-control-ledger stock-control-ledger--model/)
  assert.match(modelSignalListSource, /stock-control-ledger__header stock-control-model-ledger__grid/)
  assert.match(modelSignalListSource, /stock-control-ledger__row stock-control-model-ledger__grid/)
  assert.match(modelSignalListSource, />\s*信号时间\s*</)
  assert.match(modelSignalListSource, />\s*入库时间\s*</)
  assert.match(modelSignalListSource, />\s*标的代码\s*</)
  assert.match(modelSignalListSource, />\s*标的名称\s*</)
  assert.match(modelSignalListSource, />\s*周期\s*</)
  assert.match(modelSignalListSource, />\s*分组\s*</)
  assert.match(modelSignalListSource, />\s*模型\s*</)
  assert.match(modelSignalListSource, />\s*来源\s*</)
  assert.match(modelSignalListSource, />\s*触发价\/止损价\/止损%\s*</)
  assert.match(modelSignalListSource, /formatPriceSummary\(row\.close, row\.stop_loss_price\)/)
  assert.match(modelSignalListSource, /formatDateTime\(row\.datetime\)/)
  assert.match(modelSignalListSource, /formatDateTime\(row\.created_at\)/)
  assert.match(modelSignalListSource, /resolveDailyScreeningClsModelPresentation/)
  assert.match(modelSignalListSource, /return parsed\.toFixed\(3\)/)
  assert.match(modelSignalListSource, /@import '\.\.\/style\/stock-control-ledger\.styl'/)
  assert.match(modelSignalListSource, /stock-control-ledger__cell--time/)
  assert.match(modelSignalListSource, /grid-template-columns 148px 148px 56px minmax\(0, 1fr\) 80px 100px 120px 60px 160px/)
  assert.doesNotMatch(modelSignalListSource, /<el-table/)
  assert.doesNotMatch(modelSignalListSource, /label="标的"/)
})

test('daily-screening CLX mappings normalize stock-control raw model ids', () => {
  const erbai = resolveDailyScreeningClsModelPresentation('CLX10001')
  assert.equal(erbai.modelKey, 'S0001')
  assert.equal(erbai.groupLabel, '二买')
  assert.equal(erbai.modelLabel, '类2买')

  const breakPullback = resolveDailyScreeningClsModelPresentation('CLX10012')
  assert.equal(breakPullback.modelKey, 'S0012')
  assert.equal(breakPullback.groupLabel, '突破回调')
  assert.equal(breakPullback.modelLabel, 'V反')
})
