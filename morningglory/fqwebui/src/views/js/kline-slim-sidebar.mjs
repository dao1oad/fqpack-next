const SECTION_DEFS = Object.freeze([
  { key: 'holding', label: '持仓股', source: 'holdings', deletable: false },
  { key: 'must_pool', label: 'must_pool', source: 'mustPools', deletable: true },
  { key: 'stock_pools', label: 'stock_pools', source: 'stockPools', deletable: true },
  { key: 'stock_pre_pools', label: 'stock_pre_pools', source: 'prePools', deletable: true }
])

const DELETE_BEHAVIOR_MAP = Object.freeze({
  must_pool: {
    method: 'deleteFromStockMustPoolsByCode',
    refreshKeys: ['must_pool'],
    confirmText: '确定从 must_pool 删除该标的吗？'
  },
  stock_pools: {
    method: 'deleteFromStockPoolsByCode',
    refreshKeys: ['stock_pools', 'must_pool'],
    confirmText: '确定从 stock_pools 删除该标的吗？'
  },
  stock_pre_pools: {
    method: 'deleteFromStockPrePoolsByCode',
    refreshKeys: ['stock_pre_pools'],
    confirmText: '确定从 stock_pre_pools 删除该标的吗？'
  }
})

const toText = (value) => {
  if (value === null || value === undefined) return ''
  return String(value).trim()
}

const toNullableNumber = (value) => {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

const formatWanAmount = (value) => {
  const parsed = toNullableNumber(value)
  if (parsed === null) return '-'
  return `${(Math.abs(parsed) / 10000).toFixed(2)} 万`
}

const joinLabels = (values = []) => {
  const labels = []
  for (const value of Array.isArray(values) ? values : []) {
    const text = toText(value)
    if (!text || labels.includes(text)) continue
    labels.push(text)
  }
  return labels.join(' / ')
}

export const getSidebarCode6 = (item = {}) => {
  const rawCode = toText(item.code || item.code6)
  const symbol = toText(item.symbol)
  if (/^\d{6}$/.test(rawCode)) return rawCode
  const digits = symbol.replace(/\D/g, '')
  return /^\d{6}$/.test(digits) ? digits : ''
}

const buildSymbolFromCode6 = (code6) => {
  if (!/^\d{6}$/.test(code6)) return ''
  return code6.startsWith('6') ? `sh${code6}` : `sz${code6}`
}

const buildSidebarTitle = ({ name = '', code6 = '' } = {}) => {
  if (name && code6) return `${name}(${code6})`
  return name || code6
}

const buildSidebarSecondaryLabel = ({
  sectionKey = '',
  amount = null,
  sourceLabels = '',
  categoryLabels = '',
} = {}) => {
  if (sectionKey === 'holding') {
    return amount !== null && amount !== undefined ? `仓位 ${formatWanAmount(amount)}` : ''
  }

  if (sourceLabels && categoryLabels) return `${sourceLabels} · ${categoryLabels}`
  return sourceLabels || categoryLabels || ''
}

export const normalizeSidebarItem = (item = {}, { sectionKey = '' } = {}) => {
  const code6 = getSidebarCode6(item)
  const amount = item?.position_amount ?? item?.market_value ?? item?.amount
  const name = toText(item.name || item.stock_name || code6)
  const sourceLabels = joinLabels(item.sources) || toText(item.provider)
  const categoryLabels = joinLabels(item.categories) || toText(item.category)
  return {
    code: toText(item.code || code6),
    code6,
    symbol: toText(item.symbol) || buildSymbolFromCode6(code6),
    name,
    sourceLabels,
    categoryLabels,
    titleLabel: buildSidebarTitle({ name, code6 }),
    secondaryLabel: buildSidebarSecondaryLabel({ sectionKey, amount, sourceLabels, categoryLabels }),
    raw: item
  }
}

export const buildSidebarSections = ({
  holdings = [],
  mustPools = [],
  stockPools = [],
  prePools = [],
  expandedKey = 'holding'
} = {}) => {
  const sourceMap = { holdings, mustPools, stockPools, prePools }
  return SECTION_DEFS.map((section) => ({
    key: section.key,
    label: section.label,
    items: (sourceMap[section.source] || []).map((item) => normalizeSidebarItem(item, { sectionKey: section.key })),
    deletable: !!section.deletable,
    expanded: section.key === expandedKey,
    deleteConfirmText: DELETE_BEHAVIOR_MAP[section.key]?.confirmText || ''
  }))
}

export const toggleSidebarExpandedKey = (currentKey = '', targetKey = '') => {
  if (!targetKey) return ''
  return currentKey === targetKey ? '' : targetKey
}

export const getSidebarDeleteBehavior = (sectionKey = '') => {
  return DELETE_BEHAVIOR_MAP[sectionKey] || null
}

export const normalizeReasonItems = (payload = {}) => {
  const rawItems = Array.isArray(payload?.data?.items)
    ? payload.data.items
    : Array.isArray(payload?.items)
      ? payload.items
      : []

  return rawItems
    .map((item) => ({
      date: toText(item?.date) || '',
      time: toText(item?.time) || null,
      provider: toText(item?.provider) || '',
      plate_name: toText(item?.plate_name) || '',
      plate_reason: toText(item?.plate_reason) || '',
      stock_reason: toText(item?.stock_reason) || ''
    }))
    .filter((item) => item.date || item.provider || item.plate_name || item.stock_reason)
}

export const getReasonPanelMessage = ({ loading = false, error = '', items = [] } = {}) => {
  if (loading) return '加载中...'
  if (error) return error
  if (!Array.isArray(items) || !items.length) return '暂无热门记录'
  return ''
}
