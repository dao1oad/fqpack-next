import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const ganttHistorySource = readFileSync(
  new URL('./components/GanttHistory.vue', import.meta.url),
  'utf8',
)
const shouban30PageSource = readFileSync(
  new URL('./GanttShouban30Phase1.vue', import.meta.url),
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

test('shouban30 page keeps stock_window_days query wired into data fetches', () => {
  const stockWindowDaysBlock = readBlock(
    shouban30PageSource,
    'const stockWindowDays = computed(() => {',
    'const requestedAsOfDate = computed(() => toText(route.query.as_of_date))',
  )
  const fetchProviderPlatesBlock = readBlock(
    shouban30PageSource,
    'const fetchProviderPlates = async (provider) => {',
    'const fetchProviderStocksByPlate = async (provider, plates, asOfDate) => {',
  )
  const fetchProviderStocksByPlateBlock = readBlock(
    shouban30PageSource,
    'const fetchProviderStocksByPlate = async (provider, plates, asOfDate) => {',
    'const loadViewData = async () => {',
  )

  assert.match(
    stockWindowDaysBlock,
    /route\.query\.stock_window_days/,
  )
  assert.match(
    fetchProviderPlatesBlock,
    /stockWindowDays: stockWindowDays\.value/,
  )
  assert.match(
    fetchProviderStocksByPlateBlock,
    /stockWindowDays: stockWindowDays\.value/,
  )
})
