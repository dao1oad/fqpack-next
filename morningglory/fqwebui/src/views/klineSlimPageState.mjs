const OVERLAY_PANEL_KEYS = Object.freeze([
  'showPriceGuidePanel',
  'showChanlunStructurePanel',
  'showClxWorkbench',
])

export const buildInitialKlineSlimPageState = ({
  currentPeriod = '',
} = {}) => ({
  routeSymbol: '',
  currentPeriod,
  showPriceGuidePanel: false,
  showChanlunStructurePanel: false,
  showClxWorkbench: false,
})

export const buildKlineSlimRouteSymbol = (route = {}) => {
  return String(route?.query?.symbol || '').trim()
}

export const buildClxHistoryRequestKey = ({
  symbol = '',
  assetType = '',
  endDate = '',
  barCount = 250,
} = {}) => {
  const resolvedSymbol = String(symbol || '').trim()
  if (!resolvedSymbol) return ''
  return [
    resolvedSymbol,
    String(assetType || '').trim().toLowerCase(),
    String(endDate || '').trim() || 'latest',
    Number(barCount) || 250,
  ].join('__')
}

export const closeOtherPanels = (state = {}, keepKey = '') => {
  for (const panelKey of OVERLAY_PANEL_KEYS) {
    if (panelKey === keepKey) continue
    state[panelKey] = false
  }

  if (keepKey !== 'showPriceGuidePanel') {
    state.priceGuideEditMode = false
    state.priceGuideDragDirty = false
  }

  if (keepKey !== 'showChanlunStructurePanel') {
    state.chanlunStructureRefreshError = ''
  }

  return state
}
