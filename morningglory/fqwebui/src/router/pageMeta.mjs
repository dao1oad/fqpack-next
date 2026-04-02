const DEFAULT_PAGE_TITLE = 'FreshQuant'

const toText = (value) => String(value ?? '').trim()

export const HEADER_NAV_TARGETS = {
  systemSettings: {
    label: '设置',
    path: '/system-settings',
    buttonType: 'primary',
    size: 'default',
  },
  futures: {
    label: '期货',
    path: '/futures-control',
    buttonType: 'primary',
    size: 'small',
  },
  klineSlim: {
    label: '行情图表',
    path: '/kline-slim',
    buttonType: 'warning',
    size: 'small',
  },
  orders: {
    label: '订单管理',
    path: '/order-management',
    buttonType: 'success',
    size: 'small',
  },
  positionManagement: {
    label: '仓位管理',
    path: '/position-management',
    buttonType: 'success',
    size: 'small',
  },
  tpsl: {
    label: 'TPSL',
    path: '/tpsl',
    buttonType: 'warning',
    plain: true,
    size: 'small',
  },
  runtime: {
    label: '运行观测',
    path: '/runtime-observability',
    buttonType: 'danger',
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
  shouban30: {
    label: '首板选股',
    path: '/gantt/shouban30',
    query: {
      p: 'xgb',
      days: '30',
    },
    buttonType: 'warning',
    size: 'small',
  },
  dailyScreening: {
    label: '每日选股',
    path: '/daily-screening',
    buttonType: 'danger',
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
  cjsd: {
    label: '超级赛道',
    path: '/stock-cjsd',
    buttonType: 'primary',
    size: 'small',
  },
}

export const HEADER_NAV_GROUPS = [
  ['systemSettings'],
  ['futures'],
  ['klineSlim', 'orders', 'positionManagement', 'tpsl', 'runtime'],
  ['gantt', 'shouban30', 'dailyScreening'],
  ['stock', 'pool', 'cjsd'],
]

export const ROUTE_TITLES_BY_NAME = {
  'futures-control': '期货',
  'stock-control': '股票',
  'stock-pools': '股票池',
  'stock-cjsd': '超级赛道',
  'multi-period': '多周期',
  'kline-big': '行情图表',
  'kline-slim': '行情图表',
  gantt: '板块趋势',
  'gantt-shouban30': '首板选股',
  'daily-screening': '每日选股',
  'gantt-stocks': '板块趋势',
  'order-management': '订单管理',
  'position-management': '仓位管理',
  'runtime-observability': '运行观测',
  'system-settings': '系统设置',
  'tpsl-management': 'TPSL',
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
