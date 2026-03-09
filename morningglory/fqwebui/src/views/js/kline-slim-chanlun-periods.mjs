export const SUPPORTED_CHANLUN_PERIODS = ['1m', '5m', '15m', '30m']

export const DEFAULT_MAIN_PERIOD = '5m'

export const DEFAULT_VISIBLE_CHANLUN_PERIODS = ['5m']

export const ZHONGSHU_LEGEND_NAME = '中枢'
export const DUAN_ZHONGSHU_LEGEND_NAME = '段中枢'

export const PERIOD_STYLE_MAP = {
  '1m': {
    bi: '#ffffff',
    duan: '#facc15',
    higherDuan: '#3b82f6',
    zhongshu: '#ffffff',
    duanZhongshu: '#facc15',
    higherDuanZhongshu: '#3b82f6'
  },
  '5m': {
    bi: '#facc15',
    duan: '#3b82f6',
    higherDuan: '#ef4444',
    zhongshu: '#facc15',
    duanZhongshu: '#3b82f6',
    higherDuanZhongshu: '#ef4444'
  },
  '15m': {
    bi: '#facc15',
    duan: '#3b82f6',
    higherDuan: '#ef4444',
    zhongshu: '#facc15',
    duanZhongshu: '#3b82f6',
    higherDuanZhongshu: '#ef4444'
  },
  '30m': {
    bi: '#3b82f6',
    duan: '#ef4444',
    higherDuan: '#22c55e',
    zhongshu: '#3b82f6',
    duanZhongshu: '#ef4444',
    higherDuanZhongshu: '#22c55e'
  }
}

export const PERIOD_WIDTH_FACTOR = {
  '1m': 1,
  '5m': 3,
  '15m': 4,
  '30m': 5
}

function getDefaultLegendSelection() {
  return {
    '1m': false,
    '5m': true,
    '15m': false,
    '30m': false,
    [ZHONGSHU_LEGEND_NAME]: true,
    [DUAN_ZHONGSHU_LEGEND_NAME]: true
  }
}

export function normalizeChanlunPeriod(period) {
  return SUPPORTED_CHANLUN_PERIODS.includes(period) ? period : DEFAULT_MAIN_PERIOD
}

export function buildLegendSelectionState(previousSelected = null) {
  const defaults = getDefaultLegendSelection()
  if (!previousSelected || typeof previousSelected !== 'object') {
    return defaults
  }

  return Object.fromEntries(
    Object.keys(defaults).map((name) => [
      name,
      Object.prototype.hasOwnProperty.call(previousSelected, name)
        ? !!previousSelected[name]
        : defaults[name]
    ])
  )
}

export function getVisibleChanlunPeriods(selected = null) {
  const resolvedSelected = buildLegendSelectionState(selected)
  return SUPPORTED_CHANLUN_PERIODS.filter((period) => resolvedSelected[period])
}

export function getRealtimeRefreshPeriods({ currentPeriod, visiblePeriods = [] } = {}) {
  const normalizedCurrent = normalizeChanlunPeriod(currentPeriod)
  const deduped = [normalizedCurrent]

  SUPPORTED_CHANLUN_PERIODS.forEach((period) => {
    if (period === normalizedCurrent) {
      return
    }
    if (!visiblePeriods.includes(period)) {
      return
    }
    const normalized = normalizeChanlunPeriod(period)
    if (!deduped.includes(normalized)) {
      deduped.push(normalized)
    }
  })

  return deduped
}
