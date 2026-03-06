import { createRouter, createWebHistory } from 'vue-router'
import FuturesControl from '../views/FuturesControl.vue'
import StockControl from '../views/StockControl.vue'
import MultiPeriod from '../views/MultiPeriod.vue'
import KlineBig from '../views/KlineBig.vue'
import KlineSlim from '../views/KlineSlim.vue'
import StockPools from '../components/StockPools.vue'
import StockCjsd from '../components/StockCjsd.vue'

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
  }
]

const router = createRouter({
  history: createWebHistory('/'),
  routes
})

export default router
