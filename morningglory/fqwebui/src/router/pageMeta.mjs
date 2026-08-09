const DEFAULT_PAGE_TITLE = 'FreshQuant'

const toText = (value) => String(value ?? '').trim()

export const HEADER_NAV_TARGETS = {
  systemSettings: {
    label: '设置',
    path: '/system-settings',
    buttonType: 'primary',
    size: 'default',
  },
  klineSlim: {
    label: '行情图表',
    path: '/kline-slim',
    buttonType: 'warning',
    size: 'small',
  },
  positionManagement: {
    label: '仓位管理',
    path: '/position-management',
    buttonType: 'success',
    size: 'small',
  },
  positionReview: {
    label: '持仓复盘',
    path: '/position-review',
    buttonType: 'primary',
    size: 'small',
  },
  runtime: {
    label: '运行观测',
    path: '/runtime-observability',
    buttonType: 'danger',
    size: 'small',
  },
  opsConsole: {
    label: '运维',
    path: '/ops-console',
    buttonType: 'warning',
    size: 'small',
  },
  gantt: {
    label: '板块趋势',
    path: '/gantt',
    query: {
      p: 'xgb',
    },
    buttonType: 'success',
    size: 'small',
  },
  dailyScreening: {
    label: '每日选股',
    path: '/daily-screening',
    buttonType: 'danger',
    plain: true,
    size: 'small',
  },
  clxEvaluation: {
    label: 'CLX评价',
    path: '/daily-screening',
    buttonType: 'primary',
    plain: true,
    size: 'small',
  },
  clxDailyScreening: {
    label: '每日选股',
    path: '/kline-slim',
    query: {
      clxScreening: '1',
      clxWorkbench: '1',
      period: '1d',
    },
    buttonType: 'primary',
    plain: true,
    size: 'small',
  },
  stock: {
    label: '股票',
    path: '/stock-control',
    buttonType: 'primary',
    size: 'small',
  },
  pool: {
    label: '股票池',
    path: '/stock-pools',
    buttonType: 'primary',
    size: 'small',
  },
  tradingGuide: {
    label: '交易课堂',
    path: '/trading-guide',
    buttonType: 'primary',
    plain: true,
    size: 'small',
  },
}

export const HEADER_NAV_GROUPS = [
  ['systemSettings'],
  ['klineSlim', 'positionManagement', 'positionReview', 'runtime', 'opsConsole'],
  ['gantt', 'dailyScreening', 'clxEvaluation'],
  ['stock', 'pool'],
  ['tradingGuide'],
]

export const ROUTE_TITLES_BY_NAME = {
  'stock-control': '股票',
  'stock-pools': '股票池',
  'multi-period': '多周期',
  'kline-big': '行情图表',
  'kline-slim': '行情图表',
  gantt: '板块趋势',
  'daily-screening': '每日选股',
  'clx-daily-screening': '每日选股',
  'clx-evaluation': 'CLX日线评价',
  'gantt-stocks': '板块趋势',
  'position-management': '仓位管理',
  'position-review': '持仓复盘',
  'runtime-observability': '运行观测',
  'ops-console': '运维',
  'system-settings': '系统设置',
  'trading-guide': '交易课堂',
}

export const getHeaderNavTarget = (key) => {
  const target = HEADER_NAV_TARGETS[toText(key)]
  if (!target) return null
  return {
    label: target.label,
    path: target.path,
    query: {
      ...(target.query || {}),
      tabTitle: target.label,
    },
  }
}

export const resolveHeaderNavGroups = () => {
  return HEADER_NAV_GROUPS.map((group) => group
    .map((key) => getHeaderNavTarget(key))
    .filter(Boolean))
}

export const resolveRouteMetaTitle = (routeName) => {
  return ROUTE_TITLES_BY_NAME[toText(routeName)] || ''
}

export const resolveDocumentTitle = (route = {}) => {
  const queryTitle = toText(route?.query?.tabTitle)
  if (queryTitle) return queryTitle

  const metaTitle = toText(route?.meta?.title)
  if (metaTitle) return metaTitle

  return DEFAULT_PAGE_TITLE
}
