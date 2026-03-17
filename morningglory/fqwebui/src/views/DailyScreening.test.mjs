import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

const componentPath = path.resolve(import.meta.dirname, 'DailyScreening.vue')

test('DailyScreening radio buttons use value instead of deprecated label-as-value API', () => {
  const source = fs.readFileSync(componentPath, 'utf8')
  const radioButtonTags = source.match(/<el-radio-button\b[\s\S]*?>/g) || []

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
