const toText = (value) => String(value || '').trim()
const PROVIDER_ORDER = {
  xgb: 0,
  jygs: 1,
  agg: 2,
}

const sortByDateDesc = (left, right) => {
  return toText(right) === toText(left)
    ? 0
    : toText(right) > toText(left)
      ? 1
      : -1
}

const sortByNameAsc = (left, right) => toText(left).localeCompare(toText(right), 'zh-CN')

const uniqueSortedTexts = (values) => {
  return Array.from(
    new Set((values || []).map((item) => toText(item)).filter(Boolean)),
  ).sort()
}

const uniqueSortedProviders = (values) => {
  return Array.from(
    new Set((values || []).map((item) => toText(item)).filter(Boolean)),
  ).sort((left, right) => {
    return (PROVIDER_ORDER[left] ?? 99) - (PROVIDER_ORDER[right] ?? 99)
  })
}

const uniqueCodeCount = (rows) => {
  return new Set((rows || []).map((item) => toText(item?.code6)).filter(Boolean)).size
}

const normalizePlateRow = (row) => {
  const segTo = toText(row?.seg_to)
  return {
    ...row,
    last_up_date: segTo || null,
    view_key: toText(row?.view_key) || `${toText(row?.provider)}|${toText(row?.plate_key)}`,
  }
}

export const sortPlateRows = (rows) => {
  return (rows || [])
    .map((item) => normalizePlateRow(item))
    .sort((left, right) => {
      const dateCompare = sortByDateDesc(left.last_up_date, right.last_up_date)
      if (dateCompare !== 0) return dateCompare
      const appearCompare = Number(right?.appear_days_30 || 0) - Number(left?.appear_days_30 || 0)
      if (appearCompare !== 0) return appearCompare
      return sortByNameAsc(left?.plate_name, right?.plate_name)
    })
}

export const aggregatePlateRows = ({
  xgbPlates = [],
  jygsPlates = [],
  stockRowsByProvider = {},
} = {}) => {
  const grouped = new Map()
  for (const row of [...xgbPlates, ...jygsPlates]) {
    const plateName = toText(row?.plate_name)
    if (!plateName) continue
    if (!grouped.has(plateName)) grouped.set(plateName, [])
    grouped.get(plateName).push(row)
  }

  const aggregated = []
  for (const [plateName, rows] of grouped.entries()) {
    const providers = uniqueSortedProviders(rows.map((item) => item?.provider))
    const latestRow = [...rows].sort((left, right) => sortByDateDesc(left?.seg_to, right?.seg_to))[0]
    const tradeDates = uniqueSortedTexts(rows.flatMap((item) => item?.hit_trade_dates_30 || []))
    const sourcePlateKeys = Object.fromEntries(
      rows
        .map((item) => [toText(item?.provider), toText(item?.plate_key)])
        .filter(([provider, plateKey]) => provider && plateKey),
    )
    const stockRows = rows.flatMap((item) => {
      const provider = toText(item?.provider)
      const plateKey = toText(item?.plate_key)
      return stockRowsByProvider?.[provider]?.[plateKey] || []
    })

    aggregated.push({
      view_key: `agg|${plateName}`,
      provider: 'agg',
      plate_key: `agg|${plateName}`,
      plate_name: plateName,
      appear_days_30: tradeDates.length || Math.max(...rows.map((item) => Number(item?.appear_days_30 || 0)), 0),
      last_up_date: toText(latestRow?.seg_to) || null,
      seg_to: toText(latestRow?.seg_to) || null,
      stocks_count: uniqueCodeCount(stockRows),
      reason_text: toText(latestRow?.reason_text) || null,
      providers,
      source_plate_keys: sourcePlateKeys,
      hit_trade_dates_30: tradeDates,
    })
  }

  return sortPlateRows(aggregated)
}

export const aggregateStockRows = (rows = []) => {
  const grouped = new Map()
  for (const row of rows) {
    const code6 = toText(row?.code6)
    if (!code6) continue
    if (!grouped.has(code6)) grouped.set(code6, [])
    grouped.get(code6).push(row)
  }

  const aggregated = []
  for (const [code6, items] of grouped.entries()) {
    const latest = [...items].sort((left, right) => {
      const dateCompare = sortByDateDesc(left?.latest_trade_date, right?.latest_trade_date)
      if (dateCompare !== 0) return dateCompare
      return sortByNameAsc(left?.provider, right?.provider)
    })[0]
    const hitDates = uniqueSortedTexts(items.flatMap((item) => item?.hit_trade_dates_window || []))
    aggregated.push({
      code6,
      name: toText(latest?.name) || code6,
      hit_count_window: hitDates.length || Math.max(...items.map((item) => Number(item?.hit_count_window || 0)), 0),
      latest_trade_date: toText(latest?.latest_trade_date) || null,
      latest_reason: toText(latest?.latest_reason) || null,
      providers: uniqueSortedProviders(items.map((item) => item?.provider)),
      hit_trade_dates_window: hitDates,
    })
  }

  return aggregated.sort((left, right) => {
    const dateCompare = sortByDateDesc(left?.latest_trade_date, right?.latest_trade_date)
    if (dateCompare !== 0) return dateCompare
    const hitCompare = Number(right?.hit_count_window || 0) - Number(left?.hit_count_window || 0)
    if (hitCompare !== 0) return hitCompare
    return sortByNameAsc(left?.code6, right?.code6)
  })
}

export const buildViewStats = ({ plates = [], stockRowsByPlate = {} } = {}) => {
  const stockRows = Object.values(stockRowsByPlate || {}).flat()
  return {
    plate_count: Array.isArray(plates) ? plates.length : 0,
    stock_count: uniqueCodeCount(stockRows),
  }
}
