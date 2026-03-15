const numberFormatter = new Intl.NumberFormat('en-US')

const toText = (value) => String(value ?? '').trim()

const formatValue = (value) => {
  if (Array.isArray(value)) {
    return value.map((item) => toText(item)).filter(Boolean).join(', ') || '-'
  }
  if (typeof value === 'boolean') {
    return value ? '是' : '否'
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return numberFormatter.format(value)
  }
  return toText(value) || '-'
}

const buildSections = (payload, sectionKey) => {
  const sections = Array.isArray(payload?.[sectionKey]?.sections) ? payload[sectionKey].sections : []
  return sections.map((section) => ({
    ...section,
    restart_label: section?.restart_required
      ? '保存后需重启相关服务'
      : '保存后运行链按下次刷新生效',
    items: Array.isArray(section?.items)
      ? section.items.map((item) => ({
        ...item,
        value_label: formatValue(item?.value),
      }))
      : [],
  }))
}

export const readSystemConfigPayload = (response, fallback = {}) => {
  if (response && typeof response === 'object') {
    if (
      Object.prototype.hasOwnProperty.call(response, 'data') &&
      response.data &&
      typeof response.data === 'object'
    ) {
      return response.data
    }
    if (response.bootstrap || response.settings) return response
  }
  return fallback
}

export const buildBootstrapSections = (response) => buildSections(
  readSystemConfigPayload(response, {}),
  'bootstrap',
)

export const buildSettingsSections = (response) => buildSections(
  readSystemConfigPayload(response, {}),
  'settings',
)
