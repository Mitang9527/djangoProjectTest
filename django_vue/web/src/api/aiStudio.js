import request from './request'

// 演示登录（查找/创建用户并签发 JWT，自动赠送注册额度）
export const demoLogin = async (username) =>
  (await request.post('/api/ai_studio/demo-login/', { username })).data

// 当前登录用户身份（角色分流 / 刷新）
export const getMe = async () => (await request.get('/api/ai_studio/me/')).data

// 查询额度
export const getQuota = async () => (await request.get('/api/ai_studio/quota/')).data

// 任务列表
export const listTasks = async () => (await request.get('/api/ai_studio/tasks/')).data

// 创建生成任务（冻结额度 -> mock 生成 -> 确认扣减）
export const generate = async (params) =>
  (await request.post('/api/ai_studio/generate/', params)).data

// 充值（记账式 MVP）
export const recharge = async (amount, method = 'mock') =>
  (await request.post('/api/ai_studio/recharge/', { amount, method })).data

// ============ 管理员：工作台概览 ============
export const getDashboard = async () =>
  (await request.get('/api/ai_studio/admin/dashboard/')).data

// ============ 渠道 / Agent 管理（管理员） ============
export const listChannels = async () =>
  (await request.get('/api/ai_studio/channels/')).data

export const createChannel = async (payload) =>
  (await request.post('/api/ai_studio/channels/', payload)).data

export const updateChannel = async (id, payload) =>
  (await request.put(`/api/ai_studio/channels/${id}/`, payload)).data

export const deleteChannel = async (id) =>
  (await request.delete(`/api/ai_studio/channels/${id}/`)).data

// ============ 用户-渠道授权（管理员控制点） ============
export const listGrants = async (params = {}) =>
  (await request.get('/api/ai_studio/grants/', { params })).data

export const createGrant = async (payload) =>
  (await request.post('/api/ai_studio/grants/', payload)).data

export const deleteGrant = async (params) =>
  (await request.delete('/api/ai_studio/grants/', { params })).data

// ============ 用户管理（管理员） ============
export const listUsers = async () =>
  (await request.get('/api/ai_studio/admin/users/')).data

export const adminGrant = async (payload) =>
  (await request.post('/api/ai_studio/admin/grant/', payload)).data

// ============ 当前用户可用渠道（功能入口） ============
export const listMyChannels = async () =>
  (await request.get('/api/ai_studio/my-channels/')).data

// ============ 单点登录桥接：跳转 Django 后端页面 ============
// 前端持 JWT 换一张 60s 短时票据，再用它打开后端页面并自动建立 Session，
// 避免把长效 JWT 暴露在 URL / 浏览器历史 / 访问日志中。
export const getSsoTicket = async () =>
  (await request.post('/api/ai_studio/sso/ticket/')).data

// 后端页面的来源地址：开发期前后端分离（vite 只代理 /api，/saas/ 不在代理内），
// 需用绝对地址直达后端；生产同域部署时留空即可走相对路径。
export const BACKEND_ORIGIN = import.meta.env.VITE_BACKEND_ORIGIN || ''

/**
 * 换票后在新标签页打开 Django 后端页面。
 * @param {string} next 后端站内路径，需在后端白名单内（/saas/、/admin/ 等）
 */
export const openBackendPage = async (next = '/saas/') => {
  const { ticket } = await getSsoTicket()
  const url =
    `${BACKEND_ORIGIN}/api/ai_studio/sso/bridge/` +
    `?ticket=${encodeURIComponent(ticket)}&next=${encodeURIComponent(next)}`
  window.open(url, '_blank', 'noopener')
}
