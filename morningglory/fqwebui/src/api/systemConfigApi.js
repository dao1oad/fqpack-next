import axios from 'axios'

export const systemConfigApi = {
  getDashboard () {
    return axios({
      url: '/api/system-config/dashboard',
      method: 'get',
    })
  },
  updateBootstrap (data) {
    return axios({
      url: '/api/system-config/bootstrap',
      method: 'post',
      data,
    })
  },
  updateSettings (data) {
    return axios({
      url: '/api/system-config/settings',
      method: 'post',
      data,
    })
  },
}
