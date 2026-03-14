const LARGE_REPRO_STRUCTURE_ASOF = '2026-03-13 15:00'

function pad(value) {
  return String(value).padStart(2, '0')
}

function buildDates(period, count) {
  const stepMinutesMap = {
    '1m': 1,
    '5m': 5,
    '15m': 15,
    '30m': 30
  }
  const stepMs = (stepMinutesMap[period] || 5) * 60 * 1000
  const start = Date.parse('2025-06-01T09:30:00')
  const result = []

  for (let index = 0; index < count; index += 1) {
    const value = new Date(start + index * stepMs)
    result.push(
      `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())} ${pad(value.getHours())}:${pad(value.getMinutes())}`
    )
  }

  return result
}

function buildSeriesPairs(dates, values, stride) {
  const seriesDates = []
  const seriesValues = []

  for (let index = 0; index < dates.length; index += stride) {
    seriesDates.push(dates[index])
    seriesValues.push(Number(values[index].toFixed(4)))
  }

  if (seriesDates[seriesDates.length - 1] !== dates[dates.length - 1]) {
    seriesDates.push(dates[dates.length - 1])
    seriesValues.push(Number(values[values.length - 1].toFixed(4)))
  }

  return {
    date: seriesDates,
    data: seriesValues
  }
}

function buildBoxes(dates, count, every, width, topBase, bottomBase) {
  const result = []
  for (
    let index = Math.max(0, dates.length - count * every - width - 1);
    index < dates.length - width - 1;
    index += every
  ) {
    const phase = Math.floor((index % 37) / 3)
    result.push([
      [dates[index], Number((topBase + (phase % 5) * 0.11).toFixed(4))],
      [
        dates[Math.min(index + width, dates.length - 1)],
        Number((bottomBase - (phase % 3) * 0.08).toFixed(4))
      ]
    ])
  }
  return result
}

export function buildLargeReproStockDataPayload(period) {
  const countMap = {
    '1m': 24000,
    '5m': 20000,
    '15m': 8000,
    '30m': 4000
  }
  const count = countMap[period] || 20000
  const dates = buildDates(period, count)
  const open = []
  const close = []
  const low = []
  const high = []

  for (let index = 0; index < count; index += 1) {
    const base = 20 + index * 0.0008
    const closeValue = base + Math.sin(index / 17) * 0.92 + Math.cos(index / 47) * 0.35
    const openValue = closeValue - Math.cos(index / 13) * 0.26
    const highValue = Math.max(openValue, closeValue) + 0.33
    const lowValue = Math.min(openValue, closeValue) - 0.31

    open.push(Number(openValue.toFixed(4)))
    close.push(Number(closeValue.toFixed(4)))
    high.push(Number(highValue.toFixed(4)))
    low.push(Number(lowValue.toFixed(4)))
  }

  const recentHigh = Math.max(...high.slice(-400)) + 0.6
  const recentLow = Math.min(...low.slice(-400)) - 0.6

  return {
    symbol: 'sz002262',
    name: 'ENHUA',
    date: dates,
    open,
    close,
    low,
    high,
    bidata: buildSeriesPairs(dates, close, period === '1m' ? 8 : 6),
    duandata: buildSeriesPairs(
      dates,
      close.map((value, index) => value + Math.sin(index / 29) * 0.27),
      period === '1m' ? 24 : 18
    ),
    higherDuanData: buildSeriesPairs(
      dates,
      close.map((value, index) => value + Math.cos(index / 41) * 0.4),
      period === '1m' ? 64 : 36
    ),
    zsdata: buildBoxes(
      dates,
      period === '1m' ? 80 : 36,
      period === '1m' ? 13 : 21,
      period === '1m' ? 5 : 8,
      recentHigh,
      recentLow + 1.3
    ),
    zsflag: Array.from({ length: period === '1m' ? 80 : 36 }, () => 1),
    duan_zsdata: buildBoxes(
      dates,
      period === '1m' ? 40 : 18,
      period === '1m' ? 31 : 43,
      period === '1m' ? 9 : 13,
      recentHigh + 0.5,
      recentLow + 1.8
    ),
    duan_zsflag: Array.from({ length: period === '1m' ? 40 : 18 }, () => 1),
    higher_duan_zsdata: buildBoxes(
      dates,
      period === '1m' ? 20 : 8,
      period === '1m' ? 67 : 91,
      period === '1m' ? 13 : 21,
      recentHigh + 0.9,
      recentLow + 2.1
    ),
    higher_duan_zsflag: Array.from({ length: period === '1m' ? 20 : 8 }, () => 1),
    _bar_time: `${dates[dates.length - 1]}:${period}`,
    updated_at: `${dates[dates.length - 1]}:${period}`,
    dt: `${dates[dates.length - 1]}:${period}`
  }
}

export async function mockLargeReproKlineSlimApis(page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname

    if (!path.startsWith('/api/')) {
      await route.continue()
      return
    }

    if (path === '/api/stock_data') {
      const period = url.searchParams.get('period') || '5m'
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildLargeReproStockDataPayload(period))
      })
      return
    }

    if (path === '/api/get_stock_position_list') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            code: '002262',
            code6: '002262',
            symbol: 'sz002262',
            name: 'ENHUA'
          }
        ])
      })
      return
    }

    if (
      path === '/api/get_stock_must_pools_list' ||
      path === '/api/get_stock_pools_list' ||
      path === '/api/get_stock_pre_pools_list' ||
      path === '/api/gantt/stocks/reasons'
    ) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([])
      })
      return
    }

    if (path === '/api/stock_data_chanlun_structure') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          source: 'history_fullcalc',
          asof: LARGE_REPRO_STRUCTURE_ASOF,
          message: '',
          structure: {}
        })
      })
      return
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({})
    })
  })
}

export { LARGE_REPRO_STRUCTURE_ASOF }
