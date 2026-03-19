export const CHANLUN_EXCLUDED_PLATE_NAMES = new Set([
  '其他',
  '公告',
  'ST股',
  'ST板块'
])

const toText = (value) => String(value || '').trim()

const toFiniteNumber = (value) => {
  if (value == null || value === '') {
    return null
  }
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

export const filterExcludedPlates = (rows = []) => {
  return (rows || []).filter((item) => {
    return !CHANLUN_EXCLUDED_PLATE_NAMES.has(toText(item?.plate_name))
  })
}

export const getSegmentGainMultiple = (segment) => {
  const startPrice = toFiniteNumber(segment?.start_price)
  const endPrice = toFiniteNumber(segment?.end_price)
  if (startPrice == null || endPrice == null || startPrice <= 0) {
    return null
  }
  return Number((endPrice / startPrice).toFixed(4))
}

export const passesDefaultChanlunFilter = (response) => {
  const higherMultiple = getSegmentGainMultiple(response?.structure?.higher_segment)
  const segmentMultiple = getSegmentGainMultiple(response?.structure?.segment)
  const biGainPercent = toFiniteNumber(response?.structure?.bi?.price_change_pct)

  const result = {
    passed: false,
    higher_multiple: higherMultiple,
    segment_multiple: segmentMultiple,
    bi_gain_percent: biGainPercent,
    reason: 'structure_unavailable'
  }

  if (!response?.ok) {
    return result
  }
  if (higherMultiple == null) {
    result.reason = 'higher_multiple_unavailable'
    return result
  }
  if (segmentMultiple == null) {
    result.reason = 'segment_multiple_unavailable'
    return result
  }
  if (biGainPercent == null) {
    result.reason = 'bi_gain_unavailable'
    return result
  }
  if (higherMultiple > 3.0) {
    result.reason = 'higher_multiple_exceed'
    return result
  }
  if (segmentMultiple > 2.0) {
    result.reason = 'segment_multiple_exceed'
    return result
  }
  if (biGainPercent > 20) {
    result.reason = 'bi_gain_exceed'
    return result
  }

  result.passed = true
  result.reason = 'passed'
  return result
}
