import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('CLX market evaluation renders master-detail workbench layout', async () => {
  const source = await readFile(new URL('./ClxMarketEvaluation.vue', import.meta.url), 'utf8')

  assert.match(source, /class="clx-eval-workbench"/)
  assert.match(source, /class="clx-eval-groups" aria-label="CLX 分组导航"/)
  assert.match(source, /class="clx-eval-members" aria-label="CLX 组内成员"/)
  assert.match(source, /class="clx-eval-group-card"/)
  assert.match(source, /class="clx-eval-members-toolbar"/)
  assert.match(source, /grid-template-columns: minmax\(320px, 420px\) minmax\(0, 1fr\)/)
  assert.match(source, /@media \(max-width: 1280px\)[\s\S]*\.clx-eval-workbench[\s\S]*grid-template-columns: minmax\(0, 1fr\)/)
})

test('CLX market evaluation group click filters the member table', async () => {
  const source = await readFile(new URL('./ClxMarketEvaluation.vue', import.meta.url), 'utf8')

  assert.match(source, /v-for="group in visibleGroups"/)
  assert.match(source, /@click="selectGroup\(group\)"/)
  assert.match(source, /const selectGroup = \(group\) => \{[\s\S]*selectedGroupName\.value = group\?\.groupName \|\| ''[\s\S]*filters\.primaryGroup = ''/)
  assert.match(source, /selectedGroupName\.value && member\.primaryGroup !== selectedGroupName\.value/)
  assert.match(source, /<tr v-for="member in filteredMembers"/)
  assert.match(source, /@click="clearSelectedGroup"/)
})

test('CLX market evaluation keeps run, statistics and mapping audit in details', async () => {
  const source = await readFile(new URL('./ClxMarketEvaluation.vue', import.meta.url), 'utf8')

  assert.match(source, /class="clx-eval-audit-stack"/)
  assert.match(source, /<details class="clx-eval-details">[\s\S]*<summary>运行合同<\/summary>/)
  assert.match(source, /<details class="clx-eval-details">[\s\S]*<summary>统计分布<\/summary>/)
  assert.match(source, /<details class="clx-eval-details">[\s\S]*<summary>映射审计<\/summary>/)
  assert.match(source, /v-for="row in data\.mappingAudit"/)
})

test('CLX market evaluation exposes fundamental, ETF, sell and signal reconciliation evidence', async () => {
  const source = await readFile(new URL('./ClxMarketEvaluation.vue', import.meta.url), 'utf8')

  assert.match(source, /member\.fundamentalQualityGrade/)
  assert.match(source, /member\.growthGrade/)
  assert.match(source, /member\.cashflowBalanceGrade/)
  assert.match(source, /member\.financialReportDate/)
  assert.match(source, /<summary>[\s\S]*ETF 暴露确认/)
  assert.match(source, /data\.diagnostics\?\.etfConfirmations/)
  assert.match(source, /sell \/ mixed 诊断/)
  assert.match(source, /data\.diagnostics\?\.sellDiagnostics/)
  assert.match(source, /official_unique_signal_event_count/)
  assert.match(source, /direction_expanded_membership_count_previous/)
})

test('CLX market evaluation keeps static JSON and TDX import contracts', async () => {
  const source = await readFile(new URL('./ClxMarketEvaluation.vue', import.meta.url), 'utf8')

  assert.match(source, /fetch\('\/data\/clx-evaluator\/latest\.json'\)/)
  assert.match(source, /fetch\(latest\.href\)/)
  assert.match(source, /const importGroupToTdx = async \(group\) =>/)
  assert.match(source, /@click\.stop="importGroupToTdx\(group\)"/)
  assert.match(source, /@click="importGroupToTdx\(selectedGroup\)"/)
  assert.match(source, /clxDailySelectionApi\.syncSelectedBatchResultsToTdx/)
  assert.match(source, /syncGroupToTdxViaLocalAdapter/)
})
