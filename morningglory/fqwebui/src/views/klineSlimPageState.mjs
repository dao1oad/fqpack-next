const OVERLAY_PANEL_KEYS = Object.freeze([
  'showPriceGuidePanel',
  'showSubjectPanel',
  'showChanlunStructurePanel',
])

export const buildInitialKlineSlimPageState = ({
  currentPeriod = '',
} = {}) => ({
  routeSymbol: '',
  currentPeriod,
  showPriceGuidePanel: false,
  showSubjectPanel: false,
  showChanlunStructurePanel: false,
})

export const buildKlineSlimRouteSymbol = (route = {}) => {
  return String(route?.query?.symbol || '').trim()
}

export const closeOtherPanels = (state = {}, keepKey = '') => {
  for (const panelKey of OVERLAY_PANEL_KEYS) {
    if (panelKey === keepKey) continue
    state[panelKey] = false
  }

  if (keepKey !== 'showSubjectPanel' && state?.subjectPanelState) {
    state.subjectPanelState.showSubjectPanel = false
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
