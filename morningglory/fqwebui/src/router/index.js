import { createRouter, createWebHistory } from 'vue-router'
import FuturesControl from '../views/FuturesControl.vue'
import StockControl from '../views/StockControl.vue'
import MultiPeriod from '../views/MultiPeriod.vue'
import KlineBig from '../views/KlineBig.vue'
import KlineSlim from '../views/KlineSlim.vue'
import StockPools from '../components/StockPools.vue'
import StockCjsd from '../components/StockCjsd.vue'

const GanttUnified = () => import('../views/GanttUnified.vue')
const GanttUnifiedStocks = () => import('../views/GanttUnifiedStocks.vue')
const GanttShouban30Phase1 = () => import('../views/GanttShouban30Phase1.vue')
const OrderManagement = () => import('../views/OrderManagement.vue')
const RuntimeObservability = () => import('../views/RuntimeObservability.vue')
const TpslManagement = () => import('../views/TpslManagement.vue')

const routes = [
  {
    path: '/',
    redirect: '/stock-control'
  },
  {
    path: '/futures-control',
    name: 'futures-control',
    component: FuturesControl
  },
  {
    path: '/stock-control',
    name: 'stock-control',
    component: StockControl
  },
  {
    path: '/stock-pools',
    name: 'stock-pools',
    component: StockPools
  },
  {
    path: '/stock-cjsd',
    name: 'stock-cjsd',
    component: StockCjsd
  },
  {
    path: '/multi-period',
    name: 'multi-period',
    component: MultiPeriod
  },
  {
    path: '/kline-big',
    name: 'kline-big',
    component: KlineBig
  },
  {
    path: '/kline-slim',
    name: 'kline-slim',
    component: KlineSlim
  },
  {
    path: '/gantt',
    name: 'gantt',
    component: GanttUnified
  },
  {
    path: '/gantt/shouban30',
    name: 'gantt-shouban30',
    component: GanttShouban30Phase1
  },
  {
    path: '/gantt/stocks/:plateKey',
    name: 'gantt-stocks',
    component: GanttUnifiedStocks
  },
  {
    path: '/order-management',
    name: 'order-management',
    component: OrderManagement
  },
  {
    path: '/runtime-observability',
    name: 'runtime-observability',
    component: RuntimeObservability
  },
  {
    path: '/tpsl',
    name: 'tpsl-management',
    component: TpslManagement
  }
]

const router = createRouter({
  history: createWebHistory('/'),
  routes
})

export default router
