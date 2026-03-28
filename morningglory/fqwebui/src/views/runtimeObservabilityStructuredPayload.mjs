const MACHINE_VALUE_MIN_LENGTH = 20
const MULTILINE_VALUE_MIN_LENGTH = 80

const toText = (value) => String(value ?? '').trim()

const formatStructuredValue = (value) => {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value, null, 2)
}

const flattenStructuredEntries = (value, prefix = '') => {
  if (value === null || value === undefined) return []
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return prefix ? [{ label: prefix, value: '[]' }] : []
    }
    return value.flatMap((item, index) =>
      flattenStructuredEntries(item, prefix ? `${prefix}[${index}]` : `[${index}]`),
    )
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value)
    if (entries.length === 0) {
      return prefix ? [{ label: prefix, value: '{}' }] : []
    }
    return entries.flatMap(([key, nestedValue]) =>
      flattenStructuredEntries(nestedValue, prefix ? `${prefix}.${key}` : key),
    )
  }
  return [
    {
      label: prefix || 'value',
      value: formatStructuredValue(value),
    },
  ]
}

export const detectStructuredValueKind = (value) => {
  const normalized = toText(value)
  if (!normalized || normalized === '-') return 'empty'
  if (normalized.includes('\n')) return 'multiline'
  if (!/\s/.test(normalized) && normalized.length >= MACHINE_VALUE_MIN_LENGTH) return 'machine'
  if (normalized.length >= MULTILINE_VALUE_MIN_LENGTH) return 'multiline'
  return 'short'
}

export const buildStructuredPayloadEntries = (text, fallbackLabel) => {
  const normalized = toText(text)
  if (!normalized) return []
  try {
    const parsed = JSON.parse(normalized)
    return flattenStructuredEntries(parsed)
      .slice(0, 32)
      .map((entry, index) => ({
        key: `${fallbackLabel}-${index}`,
        label: entry.label || fallbackLabel,
        value: entry.value,
        kind: detectStructuredValueKind(entry.value),
      }))
  } catch {
    return [
      {
        key: `${fallbackLabel}-raw`,
        label: fallbackLabel,
        value: normalized,
        kind: detectStructuredValueKind(normalized),
      },
    ]
  }
}
