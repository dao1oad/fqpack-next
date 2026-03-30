import axios from './http.js'

// 简单的内存缓存实现（浏览器兼容）
export class SimpleCache {
  constructor(ttl = 3600) {
    this.cache = new Map()
    this.ttl = ttl * 1000 // 转换为毫秒
  }

  set(key, value, ttlSeconds) {
    const ttlMs =
      typeof ttlSeconds === 'number' && Number.isFinite(ttlSeconds)
        ? ttlSeconds * 1000
        : this.ttl

    this.cache.set(key, {
      value,
      expiry: Date.now() + ttlMs
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

export default {
  install (app) {
    app.config.globalProperties.$axios = axios
    app.config.globalProperties.$cache = new SimpleCache(3600)
  }
}
