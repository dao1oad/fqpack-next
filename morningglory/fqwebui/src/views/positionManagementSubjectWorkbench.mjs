const toText = (value) => String(value ?? '').trim()

const errorMessage = (error) => (
  error?.response?.data?.error || error?.message || String(error || 'unknown error')
)

const emitNotify = (notify, level, message) => {
  const handler = notify?.[level]
  if (typeof handler === 'function') {
    handler(message)
  }
}

const cloneMustPoolDraft = (draft = {}) => ({
  category: String(draft?.category || '').trim(),
  initial_lot_amount: draft?.initial_lot_amount ?? null,
  lot_amount: draft?.lot_amount ?? null,
})

const clonePositionLimitDraft = (draft = {}) => ({
  limit: draft?.limit ?? draft?.effective_limit ?? draft?.override_limit ?? draft?.default_limit ?? null,
})

const hasMustPoolDraftChanges = (detail, draft) => {
  const baseline = cloneMustPoolDraft(detail?.mustPool || {})
  return JSON.stringify(cloneMustPoolDraft(draft)) !== JSON.stringify(baseline)
}

const hasPositionLimitDraftChanges = (detail, draft) => {
  const baseline = clonePositionLimitDraft(detail?.positionLimitSummary || {})
  return JSON.stringify(clonePositionLimitDraft(draft)) !== JSON.stringify(baseline)
}

const buildPositionLimitPayload = (draft = {}) => ({
  limit: draft?.limit ?? null,
})

const uniqueSymbols = (symbols = []) => Array.from(new Set(
  (Array.isArray(symbols) ? symbols : [])
    .map((symbol) => String(symbol || '').trim())
    .filter(Boolean),
))

const normalizeEntryId = (value) => String(value || '').trim()

const listDetailEntries = (detail = null) => (
  Array.isArray(detail?.entries) ? detail.entries : []
)

const resolveSelectedEntryId = (detail, previousEntryId = '') => {
  const entries = listDetailEntries(detail)
  const candidateIds = entries.map((entry) => normalizeEntryId(entry?.entry_id)).filter(Boolean)
  if (!candidateIds.length) return ''
  const normalizedPreviousEntryId = normalizeEntryId(previousEntryId)
  return candidateIds.includes(normalizedPreviousEntryId)
    ? normalizedPreviousEntryId
    : candidateIds[0]
}

export const createPositionManagementSubjectWorkbenchController = ({
  actions,
  notify,
  reactiveImpl = (value) => value,
}) => {
  const inflightDetailLoads = {}
  const state = reactiveImpl({
    loadingOverview: false,
    pageError: '',
    overviewRows: [],
    detailMap: {},
    detailErrors: {},
    loadingDetail: {},
    mustPoolDrafts: {},
    positionLimitDrafts: {},
    selectedEntryIds: {},
    savingConfigBundle: {},
  })

  const pruneMapsForOverview = (rows = []) => {
    const allowedSymbols = new Set((rows || []).map((row) => String(row?.symbol || '').trim()).filter(Boolean))
    for (const bucket of [
      state.detailMap,
      state.detailErrors,
      state.loadingDetail,
      state.mustPoolDrafts,
      state.positionLimitDrafts,
      state.selectedEntryIds,
      state.savingConfigBundle,
    ]) {
      Object.keys(bucket).forEach((symbol) => {
        if (!allowedSymbols.has(symbol)) {
          delete bucket[symbol]
        }
      })
    }
  }

  const applyDetail = (
    detail,
    {
      preserveMustPoolDraft = false,
      preservePositionLimitDraft = false,
    } = {},
  ) => {
    const symbol = String(detail?.symbol || '').trim()
    if (!symbol) return

    const previousMustPoolDraft = cloneMustPoolDraft(state.mustPoolDrafts[symbol] || {})
    const previousPositionLimitDraft = clonePositionLimitDraft(state.positionLimitDrafts[symbol] || {})
    const previousSelectedEntryId = normalizeEntryId(state.selectedEntryIds[symbol])

    state.detailMap[symbol] = detail
    state.detailErrors[symbol] = ''
    state.mustPoolDrafts[symbol] = cloneMustPoolDraft(detail?.mustPool || {})
    state.positionLimitDrafts[symbol] = clonePositionLimitDraft(detail?.positionLimitSummary || {})
    state.selectedEntryIds[symbol] = resolveSelectedEntryId(detail, previousSelectedEntryId)

    if (preserveMustPoolDraft) {
      state.mustPoolDrafts[symbol] = previousMustPoolDraft
    }
    if (preservePositionLimitDraft) {
      state.positionLimitDrafts[symbol] = previousPositionLimitDraft
    }
  }

  const hydrateSymbol = async (
    symbol,
    {
      preserveMustPoolDraft = false,
      preservePositionLimitDraft = false,
    } = {},
  ) => {
    const normalizedSymbol = String(symbol || '').trim()
    if (!normalizedSymbol) return null
    if (inflightDetailLoads[normalizedSymbol]) {
      return inflightDetailLoads[normalizedSymbol]
    }

    state.loadingDetail[normalizedSymbol] = true
    const request = (async () => {
      try {
        const detail = await actions.loadSubjectDetail(normalizedSymbol)
        applyDetail(detail, {
          preserveMustPoolDraft,
          preservePositionLimitDraft,
        })
        state.pageError = ''
        return detail
      } catch (error) {
        state.detailErrors[normalizedSymbol] = errorMessage(error)
        state.pageError = state.detailErrors[normalizedSymbol]
        return null
      } finally {
        state.loadingDetail[normalizedSymbol] = false
        if (inflightDetailLoads[normalizedSymbol] === request) {
          delete inflightDetailLoads[normalizedSymbol]
        }
      }
    })()
    inflightDetailLoads[normalizedSymbol] = request
    return request
  }

  const ensureSymbolsHydrated = async (symbols = []) => {
    const pendingSymbols = uniqueSymbols(symbols).filter((symbol) => !state.detailMap[symbol])
    await Promise.all(pendingSymbols.map((symbol) => hydrateSymbol(symbol)))
  }

  const refreshOverview = async ({ preloadSymbols = [] } = {}) => {
    state.loadingOverview = true
    try {
      state.overviewRows = await actions.loadOverview()
      pruneMapsForOverview(state.overviewRows)
      const availableSymbols = new Set(state.overviewRows.map((row) => String(row?.symbol || '').trim()).filter(Boolean))
      const validPreloadSymbols = uniqueSymbols(preloadSymbols).filter((symbol) => availableSymbols.has(symbol))
      await ensureSymbolsHydrated(validPreloadSymbols)
      state.pageError = ''
    } catch (error) {
      state.pageError = errorMessage(error)
    } finally {
      state.loadingOverview = false
    }
  }

  const reloadSymbol = async (
    symbol,
    {
      preserveMustPoolDraft = false,
      preservePositionLimitDraft = false,
    } = {},
  ) => hydrateSymbol(symbol, {
    preserveMustPoolDraft,
    preservePositionLimitDraft,
  })

  const getSelectedEntryId = (symbol) => {
    const normalizedSymbol = String(symbol || '').trim()
    if (!normalizedSymbol) return ''
    const detail = state.detailMap[normalizedSymbol]
    const resolvedEntryId = resolveSelectedEntryId(detail, state.selectedEntryIds[normalizedSymbol])
    if (resolvedEntryId !== state.selectedEntryIds[normalizedSymbol]) {
      state.selectedEntryIds[normalizedSymbol] = resolvedEntryId
    }
    return resolvedEntryId
  }

  const getSelectedEntry = (symbol) => {
    const normalizedSymbol = String(symbol || '').trim()
    const selectedEntryId = getSelectedEntryId(normalizedSymbol)
    if (!normalizedSymbol || !selectedEntryId) return null
    const entries = listDetailEntries(state.detailMap[normalizedSymbol])
    return entries.find((entry) => normalizeEntryId(entry?.entry_id) === selectedEntryId) || null
  }

  const getSelectedEntrySlices = (symbol) => {
    const entry = getSelectedEntry(symbol)
    if (!entry) return []
    return (Array.isArray(entry.entry_slices) ? entry.entry_slices : []).map((slice) => ({
      ...slice,
      // #549 双账本：显式透传 position_type（切片缺失按 base 展示）。
      position_type: toText(slice?.position_type),
      entry_id: entry.entry_id,
      entryIdLabel: entry.entryIdLabel,
      entryCompactLabel: entry.entryCompactLabel,
      entryDisplayLabel: entry.entryDisplayLabel,
    }))
  }

  const selectEntry = (symbol, entryId) => {
    const normalizedSymbol = String(symbol || '').trim()
    const normalizedEntryId = normalizeEntryId(entryId)
    if (!normalizedSymbol || !normalizedEntryId) return null
    const entries = listDetailEntries(state.detailMap[normalizedSymbol])
    const selectedEntry = entries.find((entry) => normalizeEntryId(entry?.entry_id) === normalizedEntryId) || null
    if (!selectedEntry) return null
    state.selectedEntryIds[normalizedSymbol] = normalizedEntryId
    return selectedEntry
  }

  const saveConfigBundle = async (symbol) => {
    const normalizedSymbol = String(symbol || '').trim()
    const detail = state.detailMap[normalizedSymbol]
    if (!normalizedSymbol || !detail) return

    const mustPoolDraft = state.mustPoolDrafts[normalizedSymbol] || {}
    const positionLimitDraft = state.positionLimitDrafts[normalizedSymbol] || {}
    const mustPoolChanged = hasMustPoolDraftChanges(detail, mustPoolDraft)
    const positionLimitChanged = hasPositionLimitDraftChanges(detail, positionLimitDraft)

    if (!mustPoolChanged && !positionLimitChanged) return

    state.savingConfigBundle[normalizedSymbol] = true
    let mustPoolSaved = false
    try {
      if (mustPoolChanged) {
        await actions.saveMustPool(normalizedSymbol, cloneMustPoolDraft(mustPoolDraft))
        mustPoolSaved = true
      }
      if (positionLimitChanged) {
        await actions.savePositionLimit(
          normalizedSymbol,
          buildPositionLimitPayload(positionLimitDraft),
        )
      }
      await reloadSymbol(normalizedSymbol)
      await refreshOverview()
      emitNotify(
        notify,
        'success',
        mustPoolChanged && positionLimitChanged
          ? `${normalizedSymbol} 基础设置与仓位上限已保存`
          : mustPoolChanged
            ? `${normalizedSymbol} 基础设置已保存`
            : `${normalizedSymbol} 仓位上限已保存`,
      )
    } catch (error) {
      if (mustPoolSaved) {
        emitNotify(notify, 'warning', `${normalizedSymbol} 基础设置已保存，仓位上限保存失败`)
        await reloadSymbol(normalizedSymbol, {
          preservePositionLimitDraft: true,
        })
        await refreshOverview()
      }
      state.pageError = errorMessage(error)
    } finally {
      state.savingConfigBundle[normalizedSymbol] = false
    }
  }

  return {
    state,
    ensureSymbolsHydrated,
    refreshOverview,
    reloadSymbol,
    getSelectedEntryId,
    getSelectedEntry,
    getSelectedEntrySlices,
    selectEntry,
    saveConfigBundle,
  }
}
