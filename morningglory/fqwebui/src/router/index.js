import { createRouter, createWebHistory } from 'vue-router'
import FuturesControl from '../views/FuturesControl.vue'
import StockControl from '../views/StockControl.vue'
import MultiPeriod from '../views/MultiPeriod.vue'
import KlineBig from '../views/KlineBig.vue'
import KlineSlim from '../views/KlineSlim.vue'
import StockPools from '../components/StockPools.vue'
import StockCjsd from '../components/StockCjsd.vue'
import {
  resolveDocumentTitle,
  resolveRouteMetaTitle,
} from './pageMeta.mjs'

const GanttUnified = () => import('../views/GanttUnified.vue')
const GanttUnifiedStocks = () => import('../views/GanttUnifiedStocks.vue')
const GanttShouban30Phase1 = () => import('../views/GanttShouban30Phase1.vue')
const OrderManagement = () => import('../views/OrderManagement.vue')
const PositionManagement = () => import('../views/PositionManagement.vue')
const RuntimeObservability = () => import('../views/RuntimeObservability.vue')
const TpslManagement = () => import('../views/TpslManagement.vue')
const SystemSettings = () => import('../views/SystemSettings.vue')

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
    path: '/futures-control',
    name: 'futures-control',
    component: FuturesControl
  }),
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
    path: '/stock-cjsd',
    name: 'stock-cjsd',
    component: StockCjsd
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
    path: '/gantt/shouban30',
    name: 'gantt-shouban30',
    component: GanttShouban30Phase1
  }),
  withRouteTitle({
    path: '/gantt/stocks/:plateKey',
    name: 'gantt-stocks',
    component: GanttUnifiedStocks
  }),
  withRouteTitle({
    path: '/order-management',
    name: 'order-management',
    component: OrderManagement
  }),
  withRouteTitle({
    path: '/position-management',
    name: 'position-management',
    component: PositionManagement
  }),
  withRouteTitle({
    path: '/runtime-observability',
    name: 'runtime-observability',
    component: RuntimeObservability
  }),
  withRouteTitle({
    path: '/system-settings',
    name: 'system-settings',
    component: SystemSettings
  }),
  withRouteTitle({
    path: '/tpsl',
    name: 'tpsl-management',
    component: TpslManagement
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
