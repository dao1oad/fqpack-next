import {
  buildKlineClxScreeningQuery,
  parseKlineClxQuery,
  parseKlineClxScreeningQuery,
  stripLegacyClxQueryAliases,
} from '../views/js/kline-slim-clx.mjs'

const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value || {}, key)

const firstPresent = (value, keys = []) => {
  const source = value && typeof value === 'object' ? value : {}
  const key = keys.find((item) => hasOwn(source, item))
  return key ? source[key] : undefined
}

const withLegacyScreeningAliases = (query = {}) => ({
  ...(query || {}),
  clxFilterModels: firstPresent(query, ['clxFilterModels', 'model_keys', 'clxModels']),
  clxFilterConditions: firstPresent(query, ['clxFilterConditions', 'condition_keys', 'clxConditions']),
})

export const buildClxDailyScreeningRedirect = (to = {}) => {
  const incoming = { ...(to?.query || {}) }
  const screeningState = parseKlineClxScreeningQuery(withLegacyScreeningAliases(incoming))
  const selectedAssetType = parseKlineClxQuery(incoming).assetType
  const baseQuery = stripLegacyClxQueryAliases(incoming)

  // On the legacy screening route these names represented result filters, not
  // right-hand marker visibility. They are migrated to clxFilter* above.
  delete baseQuery.clxModels
  delete baseQuery.clxConditions

  const query = buildKlineClxScreeningQuery(baseQuery, {
    ...screeningState,
    screeningOpen: true,
  })
  if (selectedAssetType) query.clxAssetType = selectedAssetType
  query.clxWorkbench = '1'
  if (!String(query.period || '').trim()) query.period = '1d'

  return {
    path: '/kline-slim',
    query,
    hash: to?.hash,
  }
}
