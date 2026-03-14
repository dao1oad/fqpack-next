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

test('shouban30 page canonicalizes to days/end_date while keeping legacy link fallback', () => {
  const stockWindowDaysBlock = readBlock(
    shouban30PageSource,
    'const stockWindowDays = computed(() => {',
    'const requestedEndDate = computed(() => {',
  )
  const requestedEndDateBlock = readBlock(
    shouban30PageSource,
    'const requestedEndDate = computed(() => {',
    'const updateQuery = (patch = {}) => {',
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
    /route\.query\.days/,
  )
  assert.match(
    stockWindowDaysBlock,
    /route\.query\.stock_window_days/,
  )
  assert.match(
    requestedEndDateBlock,
    /route\.query\.end_date/,
  )
  assert.match(
    requestedEndDateBlock,
    /route\.query\.as_of_date/,
  )
  assert.match(
    fetchProviderPlatesBlock,
    /days: stockWindowDays\.value/,
  )
  assert.match(
    fetchProviderPlatesBlock,
    /endDate: requestedEndDate\.value \|\| undefined/,
  )
  assert.match(
    fetchProviderStocksByPlateBlock,
    /days: stockWindowDays\.value/,
  )
  assert.match(
    fetchProviderStocksByPlateBlock,
    /endDate: asOfDate \|\| requestedEndDate\.value \|\| undefined/,
  )
})
