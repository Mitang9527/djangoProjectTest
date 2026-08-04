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
