import http from '@/http'

export const getChanlunStructure = (data) => {
  let url = `/api/stock_data_chanlun_structure?period=${data.period}&symbol=${data.symbol}`
  if (data.endDate) {
    url += `&endDate=${data.endDate}`
  }
  return http({
    url,
    method: 'get'
  })
}

export const futureApi = {
  /**
   * 获取K线数据
   */
  stockData (data, config = {}) {
    let url
    if (!data.endDate) {
      url = `/api/stock_data?period=${data.period}&symbol=${data.symbol}`
    } else {
      url = `/api/stock_data?period=${data.period}&symbol=${data.symbol}&endDate=${data.endDate}`
    }
    if (data.realtimeCache) {
      url += '&realtimeCache=1'
    }
    if (data.barCount) {
      url += `&barCount=${data.barCount}`
    }
    return http({
      ...config,
      url,
      method: 'get'
    })
  },
  stockChanlunStructure (data) {
    return getChanlunStructure(data)
  },

  // 获取期货统计列表
  getStatisticList (dateRange) {
    const url = `/api/get_statistic_list?dateRange=${dateRange}`
    return http({
      url,
      method: 'get'
    })
  },
  // 获取期货合约配置
  getFutureConfig () {
    const url = '/api/get_future_config'
    return http({
      url,
      method: 'get'
    })
  },
  // 获取主力合约
  dominant () {
    const url = '/api/dominant'
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
  getStockSignalList (page) {
    return http({
      url: `/api/get_stock_signal_list?page=${page}`,
      method: 'get'
    })
  },
  getSignalList () {
    return http({
      url: '/api/get_future_signal_list',
      method: 'get'
    })
  },
  getChangeiList () {
    return http({
      url: '/api/get_change_list',
      method: 'get'
    })
  },
  getDayMaList () {
    return http({
      url: '/api/get_day_ma_list',
      method: 'get'
    })
  },
  getGlobalFutureChangeList () {
    return http({
      url: '/api/get_global_future_change_list',
      method: 'get'
    })
  },
  getDominant () {
    return http({
      url: '/api/dominant',
      method: 'get'
    })
  },
  // 查询单个持仓
  getPosition (symbol, period, status, direction) {
    const url = `/api/get_position?symbol=${symbol}&period=${period}&status=${status}&direction=${direction}`
    return http({
      url,
      method: 'get'
    })
  },
  // 查询持仓列表
  getPositionList (status, page, size, endDate) {
    const url = `/api/get_position_list?status=${status}&page=${page}&size=${size}&endDate=${endDate}`
    return http({
      url,
      method: 'get'
    })
  },
  // 获取级别多空方向
  // getLevelDirectionList () {
  //     let url = `/api/get_future_level_direction_list`
  //     return axios({
  //         url: url,
  //         method: 'get'
  //     })
  // },
  // 创建预判
  createPrejudgeList (data) {
    const url = '/api/create_future_prejudge_list'
    return http({
      url,
      method: 'post',
      data
    })
  },
  // 获取预判
  getPrejudgeList (endDate) {
    const url = `/api/get_future_prejudge_list?endDate=${endDate}`
    return http({
      url,
      method: 'get'
    })
  },
  // 更新预判
  updatePrejudgeList (data) {
    const url = '/api/update_future_prejudge_list'
    return http({
      url,
      method: 'post',
      data
    })
  },
  // 获取okex btc ticker 这个接口单独获取不能阻塞掉商品期货
  getBTCTicker () {
    const url = '/api/get_btc_ticker'
    return http({
      url,
      method: 'get'
    })
  }
}
