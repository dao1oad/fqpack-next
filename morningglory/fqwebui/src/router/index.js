import { createRouter, createWebHistory } from 'vue-router'
import {
  resolveDocumentTitle,
  resolveRouteMetaTitle,
} from './pageMeta.mjs'
import { buildClxDailyScreeningRedirect } from './clxDailyScreeningRedirect.mjs'

const StockControl = () => import('../views/StockControl.vue')
const MultiPeriod = () => import('../views/MultiPeriod.vue')
const KlineBig = () => import('../views/KlineBig.vue')
const KlineSlim = () => import('../views/KlineSlim.vue')
const StockPools = () => import('../components/StockPools.vue')
const GanttUnified = () => import('../views/GanttUnified.vue')
const GanttUnifiedStocks = () => import('../views/GanttUnifiedStocks.vue')
const DailyScreening = () => import('../views/DailyScreening.vue')
const PositionManagement = () => import('../views/PositionManagement.vue')
const PositionReview = () => import('../views/PositionReview.vue')
const RuntimeObservability = () => import('../views/RuntimeObservability.vue')
const OpsConsole = () => import('../views/OpsConsole.vue')
const SystemSettings = () => import('../views/SystemSettings.vue')
const TradingGuide = () => import('../views/TradingGuide.vue')

const withRouteTitle = (route) => ({
  ...route,
  meta: {
    ...(route.meta || {}),
    title: resolveRouteMetaTitle(route.name),
  },
})

const routes = [
  {
    path: '/',
    redirect: '/stock-control'
  },
  withRouteTitle({
    path: '/stock-control',
    name: 'stock-control',
    component: StockControl
  }),
  withRouteTitle({
    path: '/stock-pools',
    name: 'stock-pools',
    component: StockPools
  }),
  withRouteTitle({
    path: '/multi-period',
    name: 'multi-period',
    component: MultiPeriod
  }),
  withRouteTitle({
    path: '/kline-big',
    name: 'kline-big',
    component: KlineBig
  }),
  withRouteTitle({
    path: '/kline-slim',
    name: 'kline-slim',
    component: KlineSlim
  }),
  withRouteTitle({
    path: '/gantt',
    name: 'gantt',
    component: GanttUnified
  }),
  withRouteTitle({
    path: '/daily-screening',
    name: 'daily-screening',
    component: DailyScreening
  }),
  withRouteTitle({
    path: '/clx-daily-screening',
    name: 'clx-daily-screening',
    redirect: buildClxDailyScreeningRedirect
  }),
  withRouteTitle({
    path: '/clx-evaluation',
    name: 'clx-evaluation',
    redirect: () => ({ path: '/daily-screening' })
  }),
  withRouteTitle({
    path: '/gantt/stocks/:plateKey',
    name: 'gantt-stocks',
    component: GanttUnifiedStocks
  }),
  {
    path: '/reconciliation',
    redirect: (to) => ({
      path: '/position-management',
      query: to.query,
      hash: to.hash,
    }),
  },
  withRouteTitle({
    path: '/position-management',
    name: 'position-management',
    component: PositionManagement
  }),
  withRouteTitle({
    path: '/position-review',
    name: 'position-review',
    component: PositionReview
  }),
  withRouteTitle({
    path: '/runtime-observability',
    name: 'runtime-observability',
    component: RuntimeObservability
  }),
  withRouteTitle({
    path: '/ops-console',
    name: 'ops-console',
    component: OpsConsole
  }),
  withRouteTitle({
    path: '/system-settings',
    name: 'system-settings',
    component: SystemSettings
  }),
  withRouteTitle({
    path: '/trading-guide',
    name: 'trading-guide',
    component: TradingGuide
  }),
]

const router = createRouter({
  history: createWebHistory('/'),
  routes
})

router.afterEach((to) => {
  if (typeof document === 'undefined') return
  document.title = resolveDocumentTitle(to)
})

export default router
