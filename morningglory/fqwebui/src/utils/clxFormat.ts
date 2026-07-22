import type { RunStatus } from '@/types/clxBacktest'

export function formatPercent(value?: number | null, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '--'
  return `${(Number(value) * 100).toFixed(digits)}%`
}

export function formatNumber(value?: number | null, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '--'
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

export function formatInteger(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '--'
  return Math.round(Number(value)).toLocaleString('zh-CN')
}

export function formatMoney(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '--'
  return `¥${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
}

export function formatDateTime(value?: string | null): string {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(date)
}

export const runStatusMeta: Record<RunStatus, { label: string; type: 'default' | 'info' | 'success' | 'warning' | 'error' }> = {
  DRAFT: { label: '草稿', type: 'default' },
  QUEUED: { label: '排队中', type: 'info' },
  RUNNING: { label: '运行中', type: 'info' },
  CANCEL_REQUESTED: { label: '取消中', type: 'warning' },
  CANCELLED: { label: '已取消', type: 'default' },
  FAILED: { label: '失败', type: 'error' },
  COMPLETE: { label: '已完成', type: 'success' },
}

export function hashShort(value?: string | null, length = 12): string {
  if (!value) return '--'
  return value.length <= length ? value : `${value.slice(0, length)}…`
}
