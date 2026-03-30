import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'

const read = (relativePath) => readFile(new URL(relativePath, import.meta.url), 'utf8')

test('retired route sources are removed from the legacy template compatibility surface', () => {
  const retiredCompatFiles = [
    new URL('../components/StockCjsd.vue', import.meta.url),
    new URL('../components/StockPools.vue', import.meta.url),
    new URL('./FuturePositionList.vue', import.meta.url),
    new URL('./FuturesControl.vue', import.meta.url),
    new URL('./js/future-control.js', import.meta.url),
  ]

  for (const fileUrl of retiredCompatFiles) {
    assert.equal(existsSync(fileUrl), false, `${fileUrl} should be removed`)
  }
})

test('Element Plus el-link underline props use string enums instead of deprecated booleans', async () => {
  const files = await Promise.all([
    read('../components/StockMustPools.vue'),
    read('../components/StockPrePools.vue'),
    read('./StockPositionList.vue'),
  ])

  for (const content of files) {
    assert.doesNotMatch(content, /:underline="true"/)
    assert.doesNotMatch(content, /:underline="false"/)
  }

  assert.match(files[0], /underline="hover"/)
  assert.match(files[1], /underline="hover"/)
  assert.match(files[2], /underline="never"/)
})

test('DailyScreening.vue no longer uses the deprecated el-pagination small prop', async () => {
  const content = await read('./DailyScreening.vue')

  assert.match(content, /<el-pagination[\s\S]*size="small"/)
  assert.doesNotMatch(content, /<el-pagination[\s\S]*\n\s*small(?=[\s>])/)
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

test('kline-mixin no longer routes control navigation to the retired futures page', async () => {
  const content = (await read('./js/kline-mixin.js')).replace(/\r/g, '')

  assert.match(content, /jumpToControl \(type\) \{/)
  assert.match(content, /this\.\$router\.replace\('\/stock-control'\)/)
  assert.doesNotMatch(content, /\/futures-control/)
  assert.doesNotMatch(content, /type === 'futures'/)
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

test('remaining chart sources avoid active debug console.log noise and deprecated barBorderRadius options', async () => {
  const [statisticsContent, drawContent] = await Promise.all([
    read('./StatisticsChat.vue'),
    read('./js/draw.js'),
  ])

  for (const content of [statisticsContent, drawContent]) {
    assert.doesNotMatch(content, /^\s*console\.log\(/m)
  }

  assert.doesNotMatch(statisticsContent, /barBorderRadius:/)
  assert.match(statisticsContent, /legend:\s*\{[\s\S]*data:\s*\['保证金占用'\]/)
  assert.match(statisticsContent, /name:\s*'保证金占用'/)
})

test('shared stock-pool settings and kline helpers avoid active console.log noise', async () => {
  const [prePoolsContent, mySettingContent, commonToolContent, klineMixinContent] = await Promise.all([
    read('../components/StockPrePools.vue'),
    read('../components/MySetting.vue'),
    read('../tool/CommonTool.js'),
    read('./js/kline-mixin.js')
  ])

  for (const content of [prePoolsContent, mySettingContent, commonToolContent, klineMixinContent]) {
    assert.doesNotMatch(content, /^\s*console\.log\(/m)
  }
})
