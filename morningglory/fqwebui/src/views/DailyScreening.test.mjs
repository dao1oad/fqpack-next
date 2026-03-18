import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

const componentPath = path.resolve(import.meta.dirname, 'DailyScreening.vue')

test('DailyScreening renders unified workbench sections and uses radio value bindings', () => {
  const source = fs.readFileSync(componentPath, 'utf8')
  const radioButtonTags = source.match(/<el-radio-button\b[\s\S]*?>/g) || []

  assert.ok(source.includes('交集筛选'))
  assert.ok(source.includes('CLXS 命中模型'))
  assert.ok(source.includes('chanlun 命中信号'))
  assert.ok(source.includes('历史热门理由'))
  assert.ok(source.includes('90天聚合来源'))
  assert.ok(source.includes('执行全链路'))
  assert.ok(radioButtonTags.length > 0)
  assert.equal(
    radioButtonTags.some((tag) => /\s:label=|\slabel=/.test(tag)),
    false,
  )
  assert.equal(
    radioButtonTags.every((tag) => /\s:value=|\svalue=/.test(tag)),
    true,
  )
})
