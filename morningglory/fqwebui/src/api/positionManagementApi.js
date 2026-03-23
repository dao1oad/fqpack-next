import axios from 'axios'

export const positionManagementApi = {
  getDashboard () {
    return axios({
      url: '/api/position-management/dashboard',
      method: 'get'
    })
  },
  getConfig () {
    return axios({
      url: '/api/position-management/config',
      method: 'get'
    })
  },
  updateConfig (data) {
    return axios({
      url: '/api/position-management/config',
      method: 'post',
      data
    })
  },
  updateSymbolLimit (symbol, data) {
    return axios({
      url: `/api/position-management/symbol-limits/${String(symbol || '').trim()}`,
      method: 'post',
      data
    })
  }
}
