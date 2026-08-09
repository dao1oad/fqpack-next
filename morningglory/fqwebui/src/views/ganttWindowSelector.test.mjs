import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const ganttHistorySource = readFileSync(
  new URL('./components/GanttHistory.vue', import.meta.url),
  'utf8',
)

const readBlock = (source, startMarker, endMarker) => {
  const start = source.indexOf(startMarker)
  assert.notEqual(start, -1, `missing start marker: ${startMarker}`)

  const end = source.indexOf(endMarker, start)
  assert.notEqual(end, -1, `missing end marker: ${endMarker}`)

  return source.slice(start, end)
}

test('gantt history window switch reloads data after local button changes window days', () => {
  const changeWindowDaysBlock = readBlock(
    ganttHistorySource,
    'const changeWindowDays = (value) => {',
    'const emitBack = () => {',
  )

  assert.match(changeWindowDaysBlock, /emit\('update:windowDays', next\)/)
  assert.match(changeWindowDaysBlock, /loadData\(\)/)
})
