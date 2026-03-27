import http from '@/http'

export const systemConfigApi = {
  getDashboard () {
    return http({
      url: '/api/system-config/dashboard',
      method: 'get',
    })
  },
  updateBootstrap (data) {
    return http({
      url: '/api/system-config/bootstrap',
      method: 'post',
      data,
    })
  },
  updateSettings (data) {
    return http({
      url: '/api/system-config/settings',
      method: 'post',
      data,
    })
  },
}
