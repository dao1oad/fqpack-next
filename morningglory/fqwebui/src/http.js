import axios from 'axios'

export const HTTP_CONFIG = Object.freeze({
  baseURL: '',
  timeout: 15000
})

const http = axios.create({
  ...HTTP_CONFIG
})

http.interceptors.response.use(
  (response) => response.data,
  (error) => Promise.reject(error),
)

export default http
