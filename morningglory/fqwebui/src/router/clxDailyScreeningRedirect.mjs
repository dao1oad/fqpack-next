const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value || {}, key)

const firstPresent = (value, keys = []) => {
  const source = value && typeof value === 'object' ? value : {}
  const key = keys.find((item) => hasOwn(source, item))
  return key ? source[key] : undefined
}

const appendIfPresent = (target, key, value) => {
  if (value !== undefined && value !== null && String(value).trim()) target[key] = value
}

export const buildClxDailyScreeningRedirect = (to = {}) => {
  const incoming = { ...(to?.query || {}) }
  const query = { ...incoming, tab: 'clx' }

  appendIfPresent(query, 'scope_id', firstPresent(incoming, ['scope_id', 'scopeId', 'clxScope']))
  appendIfPresent(query, 'asset_types', firstPresent(incoming, ['asset_types', 'clxAssets', 'clxAssetType']))
  appendIfPresent(query, 'model_keys', firstPresent(incoming, ['model_keys', 'clxFilterModels', 'clxModels']))
  appendIfPresent(query, 'condition_keys', firstPresent(incoming, ['condition_keys', 'clxFilterConditions', 'clxConditions']))

  delete query.clxScreening
  delete query.clxWorkbench
  delete query.period
  delete query.clxScope
  delete query.scopeId
  delete query.clxAssetType
  delete query.clxAssets
  delete query.clxFilterModels
  delete query.clxFilterConditions
  delete query.clxModels
  delete query.clxConditions

  return {
    path: '/daily-screening',
    query,
    hash: to?.hash,
  }
}
