// CLS 模型展示辅助（从旧 dailyScreeningPage.mjs 抽取，供 ModelSignalList 等复用）
const toText = (value) => String(value ?? '').trim()

export const CLS_MODEL_LABELS = Object.freeze({
  S0001: '类2买',
  S0002: '类2买分型',
  S0003: '复杂类2买',
  S0004: '3买或中枢3买',
  S0005: '2买及类2买',
  S0006: '低点反弹',
  S0007: '顶底互换',
  S0008: '盘整或趋势背驰',
  S0009: '下盘下',
  S0010: '突破回调',
  S0011: '突破回踩',
  S0012: 'V反',
  S0013: '一买后的二买',
  S0014: '一买后的三买',
  S0015: '站上年线',
  S0016: '线段盘整分型区间',
  S0017: '笔盘分型区间',
})

export const CLS_GROUP_DEFINITIONS = Object.freeze([
  { key: 'cls_group:erbai', label: '二买', modelKeys: ['S0001', 'S0002', 'S0003', 'S0005'] },
  { key: 'cls_group:sanmai', label: '三买', modelKeys: ['S0004'] },
  { key: 'cls_group:yali_support', label: '压力支撑', modelKeys: ['S0006', 'S0007'] },
  { key: 'cls_group:beichi', label: '背驰', modelKeys: ['S0008', 'S0009'] },
  { key: 'cls_group:break_pullback', label: '突破回调', modelKeys: ['S0010', 'S0011', 'S0012'] },
])

export const normalizeDailyScreeningClsModelKey = (value) => {
  const text = toText(value).toUpperCase()
  if (!text) return ''

  const directMatch = text.match(/^S(\d{1,4})$/)
  if (directMatch) {
    return `S${directMatch[1].padStart(4, '0')}`
  }

  const numericMatch = text.match(/^(?:CLXS?_?|CLX_?|)(\d{4,5})$/)
  if (numericMatch) {
    return `S${numericMatch[1].slice(-4).padStart(4, '0')}`
  }

  return text
}

export const resolveDailyScreeningClsModelPresentation = (value) => {
  const rawModel = toText(value)
  const modelKey = normalizeDailyScreeningClsModelKey(rawModel)
  const group = CLS_GROUP_DEFINITIONS.find((item) => item.modelKeys.includes(modelKey))

  return {
    rawModel,
    modelKey,
    modelLabel: CLS_MODEL_LABELS[modelKey] || rawModel || '--',
    groupKey: group?.key || '',
    groupLabel: group?.label || '--',
  }
}
