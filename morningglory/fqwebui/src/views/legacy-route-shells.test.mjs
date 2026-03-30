import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'

test('retired route shells are removed from the source tree', () => {
  const retiredShellFiles = [
    new URL('./FuturesControl.vue', import.meta.url),
    new URL('../components/StockPools.vue', import.meta.url),
    new URL('../components/StockCjsd.vue', import.meta.url),
    new URL('../style/futures-control.styl', import.meta.url),
  ]

  for (const fileUrl of retiredShellFiles) {
    assert.equal(existsSync(fileUrl), false, `${fileUrl} should be removed`)
  }
})

test('stock pool subviews expose dedicated table scroll containers', async () => {
  const [prePools, mustPools] = await Promise.all([
    readFile(new URL('../components/StockPrePools.vue', import.meta.url), 'utf8'),
    readFile(new URL('../components/StockMustPools.vue', import.meta.url), 'utf8'),
  ])

  assert.match(prePools, /stock-pool-subview__table/)
  assert.match(mustPools, /stock-pool-subview__table/)
})

test('kline-big uses a vertical shell and gives the chart viewport the remaining page height', async () => {
  const styleSource = (await readFile(new URL('../style/kline-big.styl', import.meta.url), 'utf8')).replace(/\r/g, '')

  assert.match(styleSource, /\.kline-big-main[\s\S]*display:\s*flex|\.kline-big-main[\s\S]*display flex/)
  assert.match(styleSource, /\.kline-big-main[\s\S]*flex-direction\s*column/)
  assert.match(styleSource, /\.echarts-item-big[\s\S]*flex\s*1/)
  assert.match(styleSource, /\.echarts-item-big[\s\S]*min-height\s*0/)
})

test('StatisticsChat pie-chart containers reserve a concrete height before ECharts initialization', async () => {
  const statisticsSource = (await readFile(new URL('./StatisticsChat.vue', import.meta.url), 'utf8')).replace(/\r/g, '')

  assert.match(statisticsSource, /\.pie-chart-list[\s\S]*height:\s*auto|\.pie-chart-list[\s\S]*height auto/)
  assert.match(statisticsSource, /\.pie-chart[\s\S]*flex:\s*0 0 auto|\.pie-chart[\s\S]*flex 0 0 auto/)
  assert.match(statisticsSource, /\.pie-chart[\s\S]*min-height:\s*300px|\.pie-chart[\s\S]*min-height 300px/)
  assert.match(
    statisticsSource,
    /#profit-chart,\s*#win-lose-count-rate-chart,\s*#margin-chart,\s*#win-pie-chart,\s*#lose-pie-chart[\s\S]*width:\s*100%[\s\S]*height:\s*100%|#profit-chart,\s*#win-lose-count-rate-chart,\s*#margin-chart,\s*#win-pie-chart,\s*#lose-pie-chart[\s\S]*width 100%[\s\S]*height 100%/
  )
})
