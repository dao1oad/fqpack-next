const DEFAULT_PAGE_TITLE = 'FreshQuant'

const toText = (value) => String(value ?? '').trim()

export const HEADER_NAV_TARGETS = {
  systemSettings: {
    label: '设置',
    path: '/system-settings',
  },
  futures: {
    label: '期货',
    path: '/futures-control',
  },
  klineSlim: {
    label: '行情图表',
    path: '/kline-slim',
  },
  orders: {
    label: '订单管理',
    path: '/order-management',
  },
  positionManagement: {
    label: '仓位管理',
    path: '/position-management',
  },
  tpsl: {
    label: 'TPSL',
    path: '/tpsl',
  },
  runtime: {
    label: '运行观测',
    path: '/runtime-observability',
  },
  gantt: {
    label: '板块趋势',
    path: '/gantt',
    query: {
      p: 'xgb',
    },
  },
  shouban30: {
    label: '首板选股',
    path: '/gantt/shouban30',
    query: {
      p: 'xgb',
      days: '30',
    },
  },
  stock: {
    label: '股票',
    path: '/stock-control',
  },
  pool: {
    label: '股票池',
    path: '/stock-pools',
  },
  cjsd: {
    label: '超级赛道',
    path: '/stock-cjsd',
  },
}

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
