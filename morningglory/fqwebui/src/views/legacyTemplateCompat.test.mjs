import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const read = (relativePath) => readFile(new URL(relativePath, import.meta.url), 'utf8')

test('FuturePositionList.vue no longer relies on Vue 2 filter pipe syntax', async () => {
  const content = await read('./FuturePositionList.vue')

  assert.match(content, /parseTime\(row\.date_created,\s*'\{y\}-\{m\}-\{d\} \{h\}:\{i\}'\)/)
  assert.match(content, /:class="directionTagFilter\(row\.direction\)"/)
  assert.match(content, /\{\{\s*directionFilter\(row\.direction\)\s*\}\}/)
  assert.match(content, /\{\{\s*signalTypeFilter\(row\.signal\)\s*\}\}/)
  assert.match(content, /:class="percentTagFilter\(row\.current_profit_rate\)"/)
  assert.match(content, /:class="percentTagFilter\(row\.current_profit\)"/)
  assert.match(content, /:class="winLoseRateTagFilter\(calcWinLoseRate\(row\)\)"/)
  assert.match(content, /:class="percentTagFilter\(sumObj\.currentProfitSum\)"/)
  assert.doesNotMatch(content, /\|\s*parseTime/)
  assert.doesNotMatch(content, /\|\s*directionTagFilter/)
  assert.doesNotMatch(content, /\|\s*directionFilter/)
  assert.doesNotMatch(content, /\|\s*signalTypeFilter/)
  assert.doesNotMatch(content, /\|\s*percentTagFilter/)
  assert.doesNotMatch(content, /\|\s*winLoseRateTagFilter/)
})

test('Element Plus el-link underline props use string enums instead of deprecated booleans', async () => {
  const files = await Promise.all([
    read('../components/StockCjsd.vue'),
    read('../components/StockMustPools.vue'),
    read('../components/StockPools.vue'),
    read('../components/StockPrePools.vue'),
    read('./FuturePositionList.vue'),
    read('./StockPositionList.vue'),
  ])

  for (const content of files) {
    assert.doesNotMatch(content, /:underline="true"/)
    assert.doesNotMatch(content, /:underline="false"/)
  }

  assert.match(files[0], /underline="never"/)
  assert.match(files[1], /underline="hover"/)
  assert.match(files[4], /underline="never"/)
})

test('FuturePositionList.vue expansion rows bind nested table data from the current slot row', async () => {
  const content = await read('./FuturePositionList.vue')

  assert.match(content, /<template\s+#default="\{row\}">/)
  assert.match(content, /v-if="Object\.hasOwnProperty\(row,\s*'dynamicPositionList'\)"/)
  assert.match(content, /:data="row\.dynamicPositionList"/)
  assert.doesNotMatch(content, /:data="props\.row\.dynamicPositionList"/)
})

test('FuturePositionList keeps a refresh timer handle and clears it on unmount', async () => {
  const content = (await read('./FuturePositionList.vue')).replace(/\r/g, '')

  assert.match(content, /positionListRefreshTimer:\s*null/)
  assert.match(content, /this\.positionListRefreshTimer = window\.setInterval\(/)
  assert.match(
    content,
    /beforeUnmount \(\) \{[\s\S]*if \(this\.positionListRefreshTimer\) \{[\s\S]*window\.clearInterval\(this\.positionListRefreshTimer\)[\s\S]*this\.positionListRefreshTimer = null[\s\S]*\}/
  )
})

test('DailyScreening workbench no longer uses el-pagination (lists scroll inside panels)', async () => {
  const content = await read('./DailyScreening.vue')

  assert.doesNotMatch(content, /<el-pagination/)
})

test('kline-big defaults single-chart period to 1m when the route query omits period', async () => {
  const content = await read('./js/kline-big.js')

  assert.match(content, /const resolvedPeriod = .*?period.*?\|\| .*?query\.period.*?\|\| '1m'/)
  assert.match(content, /Object\.assign\(\{ symbol, period: resolvedPeriod, endDate \}/)
})

test('kline chart queries skip API requests until the route symbol exists', async () => {
  const [bigContent, multiContent] = await Promise.all([
    read('./js/kline-big.js'),
    read('./js/multi-period.js')
  ])

  assert.match(bigContent, /if \(!symbol\) \{\s*return null\s*\}/)
  assert.match(multiContent, /if \(!symbol\) \{\s*return null\s*\}/)
})

test('kline-mixin skips margin processing when the current route has no symbol', async () => {
  const content = await read('./js/kline-mixin.js')

  assert.match(content, /if \(!query\.symbol\) \{[\s\S]*?return\s*\}/)
})

test('multi-period draw watchers ignore empty period payloads before calling draw', async () => {
  const content = await read('./js/multi-period.js')

  assert.match(content, /klineData1Min: function \(newKlineData\) \{[\s\S]*if \(newKlineData\) \{[\s\S]*draw\(this, newKlineData, '1m'\)/)
  assert.match(content, /klineData5Min: function \(newKlineData\) \{[\s\S]*if \(newKlineData\) \{[\s\S]*draw\(this, newKlineData, '5m'\)/)
  assert.match(content, /klineData15Min: function \(newKlineData\) \{[\s\S]*if \(newKlineData\) \{[\s\S]*draw\(this, newKlineData, '15m'\)/)
  assert.match(content, /klineData30Min: function \(newKlineData\) \{[\s\S]*if \(newKlineData\) \{[\s\S]*draw\(this, newKlineData, '30m'\)/)
  assert.match(content, /klineData60Min: function \(newKlineData\) \{[\s\S]*if \(newKlineData\) \{[\s\S]*draw\(this, newKlineData, '60m'\)/)
  assert.match(content, /klineData1D: function \(newKlineData\) \{[\s\S]*if \(newKlineData\) \{[\s\S]*draw\(this, newKlineData, '1d'\)/)
})
