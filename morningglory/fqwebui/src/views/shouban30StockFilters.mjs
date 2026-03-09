import { hydratePlateRowsWithPassedStocks } from './shouban30Aggregation.mjs'

export const EXTRA_FILTER_OPTIONS = Object.freeze([
  { key: 'credit', label: '融资标的' },
  { key: 'near_long_term_ma', label: '均线附近' },
  { key: 'quality', label: '优质标的' },
])

const EXTRA_FILTER_PREDICATES = Object.freeze({
  credit: (row) => row?.is_credit_subject === true,
  near_long_term_ma: (row) => row?.near_long_term_ma_passed === true,
  quality: (row) => row?.is_quality_subject === true,
})

const EXTRA_FILTER_KEY_SET = new Set(EXTRA_FILTER_OPTIONS.map((item) => item.key))

const isChanlunPassed = (row) => row?.chanlun_passed !== false

export const normalizeExtraFilters = (values = []) => {
  const selected = new Set((values || []).filter((value) => EXTRA_FILTER_KEY_SET.has(value)))
  return EXTRA_FILTER_OPTIONS
    .map((item) => item.key)
    .filter((key) => selected.has(key))
}

export const toggleExtraFilter = (selectedKeys = [], key) => {
  const selected = new Set(normalizeExtraFilters(selectedKeys))
  if (!EXTRA_FILTER_KEY_SET.has(key)) {
    return normalizeExtraFilters(selectedKeys)
  }
  if (selected.has(key)) {
    selected.delete(key)
  } else {
    selected.add(key)
  }
  return EXTRA_FILTER_OPTIONS
    .map((item) => item.key)
    .filter((optionKey) => selected.has(optionKey))
}

export const filterStocksByExtraFlags = (rows = [], selectedKeys = []) => {
  const activeFilters = normalizeExtraFilters(selectedKeys)
  return (rows || []).filter((row) => {
    if (!isChanlunPassed(row)) return false
    return activeFilters.every((key) => EXTRA_FILTER_PREDICATES[key]?.(row) === true)
  })
}

export const filterStockRowsByPlate = (stockRowsByPlate = {}, selectedKeys = []) => {
  return Object.fromEntries(
    Object.entries(stockRowsByPlate || {}).map(([plateKey, rows]) => [
      plateKey,
      filterStocksByExtraFlags(rows, selectedKeys),
    ]),
  )
}

export const rebuildPlatesFromFilteredStocks = ({
  plates = [],
  stockRowsByPlate = {},
} = {}) => {
  return hydratePlateRowsWithPassedStocks({
    plates,
    stockRowsByPlate,
  })
}
