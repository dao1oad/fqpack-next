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
    if (sanitized.xtdata && typeof sanitized.xtdata === 'object') {
      const legacyMode = sanitized.xtdata.mode
      if (legacyMode !== undefined) {
        const migrated = migrateMonitorXtdataMode(legacyMode)
        sanitized.xtdata.trading_mode = migrated.trading_mode
        sanitized.xtdata.screening_mode = migrated.screening_mode
        delete sanitized.xtdata.mode
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

export const migrateMonitorXtdataMode = (mode) => {
  const normalized = String(mode ?? '').trim().toLowerCase()
  if (normalized === 'clx_15_30_only') {
    return { trading_mode: false, screening_mode: true }
  }
  if (normalized === 'guardian_and_clx_15_30' || normalized === 'clx_15_30') {
    return { trading_mode: true, screening_mode: true }
  }
  return { trading_mode: true, screening_mode: false }
}
