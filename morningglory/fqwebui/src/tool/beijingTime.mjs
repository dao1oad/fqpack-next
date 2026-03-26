const BEIJING_TIMEZONE = 'Asia/Shanghai'
const BEIJING_OFFSET_SUFFIX = '+08:00'

const TIMESTAMP_LABEL_FORMATTER = new Intl.DateTimeFormat('sv-SE', {
  timeZone: BEIJING_TIMEZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
})

const DATE_LABEL_FORMATTER = new Intl.DateTimeFormat('sv-SE', {
  timeZone: BEIJING_TIMEZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

const CLOCK_LABEL_FORMATTER = new Intl.DateTimeFormat('sv-SE', {
  timeZone: BEIJING_TIMEZONE,
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
})

const toText = (value) => String(value ?? '').trim()

const DATE_ONLY_RE = /^\d{4}-\d{2}-\d{2}$/
const COMPACT_DATE_RE = /^\d{8}$/
const TIME_ONLY_RE = /^\d{2}:\d{2}(?::\d{2})?$/
const NAIVE_DATE_TIME_RE = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?$/

const trimFractionalSeconds = (text) => (
  text.replace(/(\.\d{3})\d+(?=(?:[+-]\d{2}:\d{2}|Z)?$)/, '$1')
)

const buildFormatterParts = (formatter, parsedMs) => Object.fromEntries(
  formatter
    .formatToParts(new Date(parsedMs))
    .filter((item) => item.type !== 'literal')
    .map((item) => [item.type, item.value]),
)

const normalizeIsoLikeText = (value) => {
  let text = trimFractionalSeconds(toText(value))
  if (!text) return ''
  if (COMPACT_DATE_RE.test(text)) {
    return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}T00:00:00${BEIJING_OFFSET_SUFFIX}`
  }
  if (DATE_ONLY_RE.test(text)) {
    return `${text}T00:00:00${BEIJING_OFFSET_SUFFIX}`
  }
  if (NAIVE_DATE_TIME_RE.test(text)) {
    text = text.replace(' ', 'T')
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(text)) {
      text = `${text}:00`
    }
    return `${text}${BEIJING_OFFSET_SUFFIX}`
  }
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?(?:\.\d+)?[+-]\d{2}:\d{2}$/.test(text)) {
    return text.replace(' ', 'T')
  }
  return text
}

export const parseTimestampMs = (value) => {
  if (value instanceof Date) {
    const parsedMs = value.getTime()
    return Number.isFinite(parsedMs) ? parsedMs : null
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Math.abs(value) < 1e12 ? Math.round(value * 1000) : Math.round(value)
  }

  const text = toText(value)
  if (!text) return null

  if (/^-?\d+(?:\.\d+)?$/.test(text)) {
    const numeric = Number(text)
    if (!Number.isFinite(numeric)) return null
    return Math.abs(numeric) < 1e12 ? Math.round(numeric * 1000) : Math.round(numeric)
  }

  const parsed = Date.parse(normalizeIsoLikeText(text))
  return Number.isFinite(parsed) ? parsed : null
}

export const formatBeijingTimestamp = (value, fallback = '-') => {
  const text = toText(value)
  if (!text && !(value instanceof Date) && !(typeof value === 'number' && Number.isFinite(value))) {
    return fallback
  }
  const parsedMs = parseTimestampMs(value)
  if (parsedMs === null) return text || fallback
  const parts = buildFormatterParts(TIMESTAMP_LABEL_FORMATTER, parsedMs)
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`
}

export const formatBeijingDate = (value, fallback = '') => {
  const text = toText(value)
  if (!text && !(value instanceof Date) && !(typeof value === 'number' && Number.isFinite(value))) {
    return fallback
  }
  if (COMPACT_DATE_RE.test(text)) {
    return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`
  }
  if (DATE_ONLY_RE.test(text)) {
    return text
  }
  const parsedMs = parseTimestampMs(value)
  if (parsedMs === null) return text || fallback
  const parts = buildFormatterParts(DATE_LABEL_FORMATTER, parsedMs)
  return `${parts.year}-${parts.month}-${parts.day}`
}

export const formatBeijingClockTime = (value, fallback = '') => {
  const text = toText(value)
  if (!text && !(value instanceof Date) && !(typeof value === 'number' && Number.isFinite(value))) {
    return fallback
  }
  if (/^\d{2}:\d{2}$/.test(text)) {
    return `${text}:00`
  }
  if (TIME_ONLY_RE.test(text)) {
    return text
  }
  const parsedMs = parseTimestampMs(value)
  if (parsedMs === null) return text || fallback
  const parts = buildFormatterParts(CLOCK_LABEL_FORMATTER, parsedMs)
  return `${parts.hour}:${parts.minute}:${parts.second}`
}

export const formatBeijingDateTimeParts = (dateValue, timeValue, fallback = '-') => {
  const dateLabel = formatBeijingDate(dateValue, '')
  const timeLabel = formatBeijingClockTime(timeValue, '')
  if (dateLabel && timeLabel) return `${dateLabel} ${timeLabel}`
  if (dateLabel) return dateLabel
  if (timeLabel) return timeLabel
  return fallback
}
