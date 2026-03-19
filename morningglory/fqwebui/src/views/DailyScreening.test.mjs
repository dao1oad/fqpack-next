import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

const componentPath = path.resolve(import.meta.dirname, 'DailyScreening.vue')

test('DailyScreening renders dense workbench layout for grouped filters and workspace detail reuse', () => {
  const source = fs.readFileSync(componentPath, 'utf8')

  assert.ok(source.includes('conditionSectionGroups'))
  assert.ok(source.includes("group.key === 'base_pool'"))
  assert.ok(source.includes('加入 pre_pools'))
  assert.ok(source.includes('历史热门理由'))
  assert.ok(source.includes('handleWorkspaceRowClick'))
  assert.ok(source.includes('daily-detail-card-grid'))
  assert.ok(source.includes('daily-detail-history-panel'))
  assert.ok(!source.includes('执行全链路'))
})
