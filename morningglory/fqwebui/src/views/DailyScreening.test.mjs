import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const readSource = async (relativePath) => {
  const source = await readFile(new URL(relativePath, import.meta.url), 'utf8')
  return source.replace(/\r/g, '')
}

test('DailyScreening workbench renders three compact panels with independent result times', async () => {
  const source = await readSource('./DailyScreening.vue')

  assert.match(source, /import ClxResultPanel from '\.\.\/components\/clx-workbench\/ClxResultPanel\.vue'/)
  assert.match(source, /import ClxEvaluationPanel from '\.\.\/components\/clx-workbench\/ClxEvaluationPanel\.vue'/)
  assert.match(source, /import PoolWorkspacePanel from '\.\.\/components\/clx-workbench\/PoolWorkspacePanel\.vue'/)
  assert.match(source, /选股结果时间 <strong>\{\{\s*selection\.resultTime \|\| '—'\s*\}\}<\/strong>/)
  assert.match(source, /评价结果时间 <strong>\{\{\s*evaluation\.generatedAt \|\| '—'\s*\}\}<\/strong>/)
  assert.match(source, /评价对象时间 <strong>\{\{\s*evaluation\.tradeDate \|\| '—'\s*\}\}<\/strong>/)
})

test('DailyScreening workbench uses fixed three-column layout without page-level scroll', async () => {
  const source = await readSource('./DailyScreening.vue')

  assert.match(source, /\.clx-workbench-page \{[\s\S]*height:\s*100dvh;[\s\S]*overflow:\s*hidden;/)
  assert.match(source, /grid-template-columns:[\s\S]*minmax\(760px,\s*30fr\)[\s\S]*minmax\(1100px,\s*46fr\)[\s\S]*minmax\(560px,\s*24fr\)/)
  assert.match(source, /\.clx-workbench-grid \{[\s\S]*min-height:\s*0;[\s\S]*overflow:\s*hidden;/)
})

test('DailyScreening workbench wires shared times from result and evaluation panels', async () => {
  const source = await readSource('./DailyScreening.vue')

  assert.match(source, /@selection-time="Object\.assign\(selection, \$event\)"/)
  assert.match(source, /@evaluation-time="Object\.assign\(evaluation, \$event\)"/)
  assert.match(source, /@pre-status="preStatus = \$event"/)
})

test('DailyScreening workbench does not embed the retired intersection or CLX legacy pages', async () => {
  const source = await readSource('./DailyScreening.vue')

  assert.doesNotMatch(source, /ClxDailyScreening/)
  assert.doesNotMatch(source, /dailyScreeningPage\.mjs/)
  assert.doesNotMatch(source, /dailyScreeningFilters\.mjs/)
  assert.doesNotMatch(source, /Shouban30ReasonPopover/)
})
