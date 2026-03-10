export const streakPalettes = {
  1: ['#ffd666', '#ffc53d', '#faad14', '#d48806', '#ad6800', '#874d00'],
  2: ['#91caff', '#69b1ff', '#409eff', '#1677ff', '#0958d9', '#003eb3'],
  3: ['#ffa39e', '#ff7875', '#ff4d4f', '#d9363e', '#b3242b', '#8c161c'],
  4: ['#b7eb8f', '#95de64', '#73d13d', '#52c41a', '#389e0d', '#237804']
}

const DEFAULT_COLOR = '#d9d9d9'

const getYKey = (item, level, fallbackKey) => {
  if (level === 'plate') return item?.id ?? item?.name ?? fallbackKey
  return item?.symbol ?? item?.name ?? fallbackKey
}

const getZoomSpan = (zoom, fallbackSpan) => {
  const start = Number(zoom?.start)
  const end = Number(zoom?.end)
  const span = end - start
  if (!Number.isFinite(span) || span <= 0) return fallbackSpan
  return Math.min(100, span)
}

export const getStreakColor = (order, day) => {
  const paletteKey = Math.min(Number(order) || 1, 4)
  const palette = streakPalettes[paletteKey] || []
  if (!palette.length) return DEFAULT_COLOR
  const idx = Math.min(Math.max((Number(day) || 1) - 1, 0), palette.length - 1)
  return palette[idx] || DEFAULT_COLOR
}

export const processSeriesWithStreaks = ({
  dates = [],
  yAxisRaw = [],
  seriesData = [],
  level = 'plate'
} = {}) => {
  const orderedYAxis = Array.isArray(yAxisRaw) ? [...yAxisRaw] : []
  const yIndexMap = new Map()
  orderedYAxis.forEach((item, idx) => {
    yIndexMap.set(getYKey(item, level, idx), idx)
  })

  const records = new Map()
  ;(seriesData || []).forEach((entry, rawIdx) => {
    if (!Array.isArray(entry)) return
    const rawYIndex = Number(entry[1])
    const rawYItem = orderedYAxis[rawYIndex]
    const yKey = getYKey(rawYItem, level, `fallback-${rawIdx}`)
    if (!records.has(yKey)) records.set(yKey, new Map())
    records.get(yKey).set(entry[0], entry)
  })

  const processed = []
  orderedYAxis.forEach((item, idx) => {
    const yKey = getYKey(item, level, idx)
    const dateMap = records.get(yKey) || new Map()
    let streakOrder = 0
    let streakDay = 0
    let hadPrev = false

    dates.forEach((_, dateIdx) => {
      const entry = dateMap.get(dateIdx)
      if (!entry) {
        hadPrev = false
        streakDay = 0
        return
      }

      if (hadPrev) {
        streakDay += 1
      } else {
        streakOrder += 1
        streakDay = 1
      }
      hadPrev = true

      const cloned = [...entry]
      cloned[1] = yIndexMap.get(yKey) ?? cloned[1]
      cloned.push(getStreakColor(streakOrder, streakDay), streakOrder, streakDay)
      processed.push(cloned)
    })
  })

  return {
    yAxisRaw: orderedYAxis,
    seriesData: processed
  }
}

export const getResetViewportWindow = (xZoom = {}, yZoom = {}) => {
  const xSpan = getZoomSpan(xZoom, 100)
  const ySpan = getZoomSpan(yZoom, 100)
  return {
    xStart: Math.max(0, 100 - xSpan),
    xEnd: 100,
    yStart: 0,
    yEnd: Math.min(100, ySpan)
  }
}
