import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const readSource = async (relativePath) => {
  const source = await readFile(new URL(relativePath, import.meta.url), 'utf8')
  return source.replace(/\r/g, '')
}

test('DailyScreening workbench renders three fundamental regions with shared times', async () => {
  const source = await readSource('./DailyScreening.vue')

  assert.match(source, /import ClxFundamentalRankingPanel from '\.\.\/components\/clx-workbench\/ClxFundamentalRankingPanel\.vue'/)
  assert.match(source, /import ClxFundamentalDetailPanel from '\.\.\/components\/clx-workbench\/ClxFundamentalDetailPanel\.vue'/)
  assert.match(source, /import ClxFundamentalStatsPanel from '\.\.\/components\/clx-workbench\/ClxFundamentalStatsPanel\.vue'/)
  assert.match(source, /排序结果时间 <strong>\{\{\s*selection\.resultTime \|\| '—'\s*\}\}<\/strong>/)
  assert.match(source, /交易日 <strong>\{\{\s*selection\.tradeDate \|\| evaluation\.tradeDate \|\| '—'\s*\}\}<\/strong>/)
})

test('DailyScreening workbench uses fixed three-region layout without page-level scroll', async () => {
  const source = await readSource('./DailyScreening.vue')

  assert.match(source, /\.clx-workbench-page \{[\s\S]*height:\s*100dvh;[\s\S]*overflow:\s*hidden;/)
  assert.match(source, /grid-template-columns:[\s\S]*minmax\(460px,\s*40fr\)[\s\S]*minmax\(500px,\s*38fr\)[\s\S]*minmax\(300px,\s*22fr\)/)
  assert.match(source, /\.clx-workbench-grid \{[\s\S]*min-height:\s*0;[\s\S]*overflow:\s*hidden;/)
})

test('DailyScreening wires single-direction drill-down from list to detail and stats filters', async () => {
  const source = await readSource('./DailyScreening.vue')

  assert.match(source, /@select="onSelect"/)
  assert.match(source, /@close="onCloseDetail"/)
  assert.match(source, /@industry-filter="onIndustryFilter"/)
  assert.match(source, /@symbol-search="onSymbolSearch"/)
  assert.match(source, /@stats-ready="onStatsReady"/)
  assert.match(source, /:industry-filter="industryFilter"/)
})

test('DailyScreening restores ranking list focus when detail closes', async () => {
  const source = await readSource('./DailyScreening.vue')

  assert.match(source, /const onCloseDetail = \(\) => \{[\s\S]*selectedRow\.value = null[\s\S]*rankingPanel\.value\?\.focusList\?\.\(\)/)
  assert.match(source, /@close="onCloseDetail"/)
})

test('DailyScreening retires market-replay UI and the three-pool workspace', async () => {
  const source = await readSource('./DailyScreening.vue')

  assert.doesNotMatch(source, /PoolWorkspacePanel|poolWorkspaceLogic|clx-pools-panel/)
  assert.doesNotMatch(source, /ClxResultPanel|ClxEvaluationPanel/)
  assert.doesNotMatch(source, /market_lane|marketLane|market_theme_id|marketThemeId|marketFitGrade/)
  assert.doesNotMatch(source, /三池工作区/)
})

test('DailyScreening shows amber banner when batch quality gate fails', async () => {
  const source = await readSource('./DailyScreening.vue')

  assert.match(source, /amberBannerVisible/)
  assert.match(source, /clx-workbench-amber/)
  assert.match(source, /质量门：\{\{\s*gateStatus === 'passed' \? '通过' : '琥珀'\s*\}\}/)
})

test('DailyScreening degrades at narrow breakpoints (stats to bottom, detail drawer)', async () => {
  const source = await readSource('./DailyScreening.vue')

  assert.match(source, /@media \(max-width:\s*1280px\)/)
  assert.match(source, /\.clx-workbench-grid__stats \{[\s\S]*grid-row:\s*2;/)
  assert.match(source, /@media \(max-width:\s*960px\)/)
  assert.match(source, /\.clx-workbench-grid__detail \{[\s\S]*position:\s*fixed;/)
})
