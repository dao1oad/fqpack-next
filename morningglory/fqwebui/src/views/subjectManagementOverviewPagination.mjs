export const DEFAULT_OVERVIEW_PAGE_SIZE = 100
export const OVERVIEW_PAGE_SIZE_OPTIONS = [100, 200, 500]

const toPositiveInteger = (value, fallback) => {
  const parsed = Number(value)
  if (!Number.isInteger(parsed) || parsed <= 0) {
    return fallback
  }
  return parsed
}

export const paginateOverviewRows = (rows = [], pagination = {}) => {
  const normalizedRows = Array.isArray(rows) ? rows : []
  const pageSize = toPositiveInteger(pagination?.pageSize, DEFAULT_OVERVIEW_PAGE_SIZE)
  const total = normalizedRows.length
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const page = Math.min(
    toPositiveInteger(pagination?.page, 1),
    totalPages,
  )
  const start = (page - 1) * pageSize

  return {
    rows: normalizedRows.slice(start, start + pageSize),
    page,
    pageSize,
    total,
    totalPages,
  }
}
