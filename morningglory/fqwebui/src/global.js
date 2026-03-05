import axios from './http'

// 简单的内存缓存实现（浏览器兼容）
class SimpleCache {
  constructor(ttl = 3600) {
    this.cache = new Map()
    this.ttl = ttl * 1000 // 转换为毫秒
  }

  set(key, value) {
    this.cache.set(key, {
      value,
      expiry: Date.now() + this.ttl
    })
  }

  get(key) {
    const item = this.cache.get(key)
    if (!item) return undefined

    if (Date.now() > item.expiry) {
      this.cache.delete(key)
      return undefined
    }

    return item.value
  }

  del(key) {
    this.cache.delete(key)
  }

  flushAll() {
    this.cache.clear()
  }
}

// 期货账户
const futureAccount = 58
// 股票账户
const stockAccount = 3
// 数字货币账户
const digitCoinAccount = 60.3 / 10000
// 外盘账户
const globalFutureAccount = 6
// 数字货币 杠杆倍数
const digitCoinLevel = 20
// 'NID', 'CP', 'CT',
const globalFutureSymbol = ['CL', 'GC', 'SI', 'ZS', 'ZM', 'ZL', 'YM', 'ES', 'NQ', 'CN']

// 最大资金使用率
const maxAccountUseRate = 0.10

// 止损系数
const stopRate = 0.01

export default {
  install (app) {
    app.config.globalProperties.$axios = axios
    app.config.globalProperties.$futureAccount = futureAccount
    app.config.globalProperties.$globalFutureAccount = globalFutureAccount
    app.config.globalProperties.$stockAccount = stockAccount
    app.config.globalProperties.$digitCoinAccount = digitCoinAccount
    app.config.globalProperties.$digitCoinLevel = digitCoinLevel
    app.config.globalProperties.$globalFutureSymbol = globalFutureSymbol
    app.config.globalProperties.$maxAccountUseRate = maxAccountUseRate
    app.config.globalProperties.$stopRate = stopRate
    app.config.globalProperties.$cache = new SimpleCache(3600)
  }
}
