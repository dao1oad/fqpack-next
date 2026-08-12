import http from '@/http'

export const stockApi = {
  /**
   * 获取K线数据
   */
  stockData (data) {
    let url
    if (!data.endDate) {
      url = `/api/stock_data?period=${data.period}&symbol=${data.symbol}`
    } else {
      url = `/api/stock_data?period=${data.period}&symbol=${data.symbol}&endDate=${data.endDate}`
    }
    return http({
      url,
      method: 'get'
    })
  },
  saveStockData (data) {
    const url = `/api/save_stock_data?period=${data.period}&symbol=${data.symbol}`
    return http({
      url,
      method: 'get',
      data
    })
  },
  getStockSignalList ({ page, size, category }) {
    page = page || 1
    size = size || 10
    return http({
      url: '/api/get_stock_signal_list',
      method: 'get',
      params: { page, size, category }
    })
  },
  getStockModelSignalList ({ page, size }) {
    page = page || 1
    size = size || 10
    return http({
      url: '/api/get_stock_model_signal_list',
      method: 'get',
      params: { page, size }
    })
  },
  getStockPoolsList ({ page, size }) {
    return http({
      url: '/api/get_stock_pools_list',
      method: 'get',
      params: { page, size }
    })
  },
  syncStockPoolsFromTdx ({ days = 30 } = {}) {
    return http({
      url: '/api/pools/stock/sync-from-tdx',
      method: 'post',
      params: { days }
    })
  },
  syncMustPoolFromTdx ({ days = 30, allowEmpty = false } = {}) {
    return http({
      url: '/api/pools/must/sync-from-tdx',
      method: 'post',
      params: {
        days,
        ...(allowEmpty ? { allow_empty: 1 } : {})
      }
    })
  },
  getStockPrePoolsCategory () {
    return http({
      url: '/api/get_stock_pre_pools_category',
      method: 'get'
    })
  },
  getStockPrePoolsList ({ page, size , category}) {
    return http({
      url: '/api/get_stock_pre_pools_list',
      method: 'get',
      params: { page, size , category}
    })
  },
  getCjsdList ({ page, size }) {
    return http({
      url: '/api/get_cjsd_list',
      method: 'get',
      params: { page, size }
    })
  },
  // 持仓操作
  // 新增一个持仓
  createPosition (data) {
    const url = '/api/create_stock_position'
    return http({
      url,
      method: 'post',
      data
    })
  },
  // 查询单个持仓
  getPosition (symbol, period, status) {
    const url = `/api/get_stock_position?symbol=${symbol}&period=${period}&status=${status}`
    return http({
      url,
      method: 'get'
    })
  },
  // 查询持仓列表
  getPositionList ({ page = 1, size = 10 }) {
    const url = `/api/get_stock_position_list?page=${page}&size=${size}`
    return http({
      url,
      method: 'get'
    })
  },
  getHoldingPositionList () {
    return http({
      url: '/api/get_stock_position_list',
      method: 'get'
    })
  },
  // 更新持仓
  updatePosition (data) {
    const url = '/api/update_stock_position'
    return http({
      url,
      method: 'post',
      data
    })
  },
  // 更新持仓状态
  updatePositionStatus (id, status) {
    const url = `/api/update_stock_position_status?id=${id}&status=${status}`
    return http({
      url,
      method: 'get'
    })
  },
  // 从预监控池删除
  deleteFromStockPrePoolsByCode (code) {
    const url = `/api/delete_from_stock_pre_pools_by_code?code=${code}`
    return http({
      url,
      method: 'get'
    })
  },
  // v4.2 收敛后 stock/must 只以通达信 ZXG/DM 分组为来源，不再提供网页直接维护。
  // 保留兼容 helper：KlineSlim 等旧入口调用时返回明确提示，避免 missing method。
  addToStockPoolsByCode () {
    return Promise.resolve({
      code: '1',
      msg: '已迁移：stock_pools 请在通达信维护 ZXG 自选股后点击「同步自选股」'
    })
  },
  deleteFromStockPoolsByCode () {
    return Promise.resolve({
      code: '1',
      msg: '已迁移：stock_pools 请在通达信维护 ZXG 自选股后点击「同步自选股」'
    })
  },
  deleteFromStockMustPoolsByCode () {
    return Promise.resolve({
      code: '1',
      msg: '已迁移：must_pool 请在通达信维护 DM 待买组后点击「同步待买组」'
    })
  },
  // 从必选池获取
  getStockMustPoolsList ({ page = 1, size = 10 }) {
    return http({
      url: '/api/get_stock_must_pools_list',
      method: 'get',
      params: { page, size }
    })
  },
  // 获取所有设置
  getSettings () {
    return http({
      url: '/api/get_settings',
      method: 'get'
    })
  },
  // 更新设置
  updateSetting (name, value) {
    return http({
      url: '/api/update_settings',
      method: 'post',
      data: {
        name,
        value
      }
    })
  },
  planGridTrade (data) {
    return http({
      url: '/api/plan_grid_trade',
      method: 'get',
      params: data
    })
  },
  query_stock_fills (symbol) {
    return http({
      url: '/api/stock_fills',
      method: 'get',
      params: { symbol }
    })
  },
  resetStockFills (data) {
    return http({
      url: '/api/stock_fills/reset',
      method: 'post',
      data
    })
  },
  get_stock_hold_position(code) {
    return http({
      url: '/api/stock_hold_position',
      method: 'get',
      params: { code }
    })
  }

}
