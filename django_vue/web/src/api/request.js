import axios from 'axios'
import { ElMessage } from 'element-plus'

const service = axios.create({
  baseURL: '/',
  timeout: 30000,
})

// 请求拦截：自动附带 JWT
service.interceptors.request.use((config) => {
  const token = localStorage.getItem('tsai_token')
  if (token) {
    config.headers.Authorization = 'Bearer ' + token
  }
  return config
})

// 响应拦截：解包 CustomRenderer 五字段结构
service.interceptors.response.use(
  (resp) => {
    const body = resp.data
    // 业务负载在 body.data（CustomRenderer 统一包装）
    const biz = body && body.data !== undefined ? body.data : body
    if (body && body.status === 'error') {
      ElMessage.error(body.message || '请求失败')
      return Promise.reject(body)
    }
    return biz
  },
  (error) => {
    const resp = error.response
    const body = resp && resp.data
    if (resp && resp.status === 401) {
      localStorage.removeItem('tsai_token')
      ElMessage.error('登录已失效，请重新登录')
      setTimeout(() => {
        location.hash = '#/login'
      }, 800)
    } else {
      ElMessage.error((body && body.message) || '网络错误')
    }
    return Promise.reject(error)
  }
)

export default service
