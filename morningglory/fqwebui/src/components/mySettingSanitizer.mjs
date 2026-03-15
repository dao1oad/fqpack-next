const cloneValue = (value) => JSON.parse(JSON.stringify(value || {}))

export const sanitizeLegacySettingValue = (code, value) => {
  const sanitized = cloneValue(value)

  if (code === 'monitor') {
    if (sanitized.stock && typeof sanitized.stock === 'object') {
      delete sanitized.stock.periods
      delete sanitized.stock.auto_open
      if (Object.keys(sanitized.stock).length === 0) {
        delete sanitized.stock
      }
    }
  }

  if (code === 'guardian') {
    if (sanitized.stock && typeof sanitized.stock === 'object') {
      delete sanitized.stock.position_pct
      delete sanitized.stock.auto_open
      delete sanitized.stock.min_amount
    }
  }

  return sanitized
}
