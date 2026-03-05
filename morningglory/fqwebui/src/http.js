import axios from 'axios'
// 请求拦截
axios.interceptors.request.use(
  config => {
    return config
  },
  error => {
    Promise.reject(error)
  }
)
// 响应拦截
axios.interceptors.response.use((res) => {
  // 对响应数据做些事
  if (res.status !== 200) {
    return Promise.reject(res)
  }
  return res.data
}, (error) => {
  return Promise.reject(error)
})
export default axios
