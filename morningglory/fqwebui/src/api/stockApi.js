import axios from 'axios'

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
    return axios({
      url,
      method: 'get'
    })
  },
  saveStockData (data) {
    const url = `/api/save_stock_data?period=${data.period}&symbol=${data.symbol}`
    return axios({
      url,
      method: 'get',
      data
    })
  },
  getStockSignalList ({ page, size, category }) {
    page = page || 1
    size = size || 10
    return axios({
      url: '/api/get_stock_signal_list',
      method: 'get',
      params: { page, size, category }
    })
  },
  getStockModelSignalList ({ page, size }) {
    page = page || 1
    size = size || 10
    return axios({
      url: '/api/get_stock_model_signal_list',
      method: 'get',
      params: { page, size }
    })
  },
  getStockPoolsList ({ page, size }) {
    return axios({
      url: '/api/get_stock_pools_list',
      method: 'get',
      params: { page, size }
    })
  },
  getStockPrePoolsCategory () {
    return axios({
      url: '/api/get_stock_pre_pools_category',
      method: 'get'
    })
  },
  getStockPrePoolsList ({ page, size , category}) {
    return axios({
      url: '/api/get_stock_pre_pools_list',
      method: 'get',
      params: { page, size , category}
    })
  },
  getCjsdList ({ page, size }) {
    return axios({
      url: '/api/get_cjsd_list',
      method: 'get',
      params: { page, size }
    })
  },
  // 持仓操作
  // 新增一个持仓
  createPosition (data) {
    const url = '/api/create_stock_position'
    return axios({
      url,
      method: 'post',
      data
    })
  },
  // 查询单个持仓
  getPosition (symbol, period, status) {
    const url = `/api/get_stock_position?symbol=${symbol}&period=${period}&status=${status}`
    return axios({
      url,
      method: 'get'
    })
  },
  // 查询持仓列表
  getPositionList ({ page = 1, size = 10 }) {
    const url = `/api/get_stock_position_list?page=${page}&size=${size}`
    return axios({
      url,
      method: 'get'
    })
  },
  getHoldingPositionList () {
    return axios({
      url: '/api/get_stock_position_list',
      method: 'get'
    })
  },
  // 更新持仓
  updatePosition (data) {
    const url = '/api/update_stock_position'
    return axios({
      url,
      method: 'post',
      data
    })
  },
  // 更新持仓状态
  updatePositionStatus (id, status) {
    const url = `/api/update_stock_position_status?id=${id}&status=${status}`
    return axios({
      url,
      method: 'get'
    })
  },
  // 添加到监控池
  addToStockPoolsByCode (code, days) {
    const url = `/api/add_to_stock_pools_by_code?code=${code}&days=${days}`
    return axios({
      url,
      method: 'get'
    })
  },
  // 添加到监控池
  addToStockPoolsByStock (data) {
    const url = '/api/add_to_stock_pools_by_stock'
    return axios({
      url,
      method: 'post',
      data
    })
  },
  // 从预监控池删除
  deleteFromStockPrePoolsByCode (code) {
    const url = `/api/delete_from_stock_pre_pools_by_code?code=${code}`
    return axios({
      url,
      method: 'get'
    })
  },
  // 从监控池删除
  deleteFromStockPoolsByCode (code) {
    const url = `/api/delete_from_stock_pools_by_code?code=${code}`
    return axios({
      url,
      method: 'get'
    })
  },
  // 从必选池获取
  getStockMustPoolsList ({ page = 1, size = 10 }) {
    return axios({
      url: '/api/get_stock_must_pools_list',
      method: 'get',
      params: { page, size }
    })
  },
  // 从必选删除
  deleteFromStockMustPoolsByCode (code) {
    const url = `/api/delete_from_must_pool_by_code?code=${code}`
    return axios({
      url,
      method: 'get'
    })
  },
  // 从监控池添加到必选
  addToStockMustPoolsByCode (code, stop_loss_price, initial_lot_amount, lot_amount, forever) {
    const url = `/api/add_to_must_pool_by_code?code=${code}&stop_loss_price=${stop_loss_price}&initial_lot_amount=${initial_lot_amount}&lot_amount=${lot_amount}&forever=${forever}`
    return axios({
      url,
      method: 'get'
    })
  },
  // 获取所有设置
  getSettings () {
    return axios({
      url: '/api/get_settings',
      method: 'get'
    })
  },
  // 更新设置
  updateSetting (name, value) {
    return axios({
      url: '/api/update_settings',
      method: 'post',
      data: {
        name,
        value
      }
    })
  },
  planGridTrade (data) {
    return axios({
      url: '/api/plan_grid_trade',
      method: 'get',
      params: data
    })
  },
  query_stock_fills (symbol) {
    return axios({
      url: '/api/stock_fills',
      method: 'get',
      params: { symbol }
    })
  },
  resetStockFills (data) {
    return axios({
      url: '/api/stock_fills/reset',
      method: 'post',
      data
    })
  },
  get_stock_hold_position(code) {
    return axios({
      url: '/api/stock_hold_position',
      method: 'get',
      params: { code }
    })
  }

}
