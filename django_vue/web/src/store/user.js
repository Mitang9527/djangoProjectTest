import { defineStore } from 'pinia'
import { demoLogin, getMe } from '@/api/aiStudio'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem('tsai_token') || '',
    username: localStorage.getItem('tsai_user') || '',
    is_staff: localStorage.getItem('tsai_is_staff') === '1',
    is_superuser: localStorage.getItem('tsai_is_superuser') === '1',
    quota: { balance: 0, frozen: 0 },
  }),
  getters: {
    isAdmin: (s) => s.is_staff || s.is_superuser,
    isLoggedIn: (s) => !!s.token,
  },
  actions: {
    _persist(biz) {
      this.token = biz.access
      this.username = biz.user.username
      this.is_staff = !!biz.user.is_staff
      this.is_superuser = !!biz.user.is_superuser
      this.quota = biz.quota
      localStorage.setItem('tsai_token', biz.access)
      localStorage.setItem('tsai_user', biz.user.username)
      localStorage.setItem('tsai_is_staff', this.is_staff ? '1' : '0')
      localStorage.setItem('tsai_is_superuser', this.is_superuser ? '1' : '0')
    },
    async login(username) {
      const biz = await demoLogin(username)
      this._persist(biz)
      return biz
    },
    async fetchMe() {
      if (!this.token) return
      try {
        const biz = await getMe()
        this.username = biz.username
        this.is_staff = !!biz.is_staff
        this.is_superuser = !!biz.is_superuser
        this.quota = biz.quota
        localStorage.setItem('tsai_is_staff', this.is_staff ? '1' : '0')
        localStorage.setItem('tsai_is_superuser', this.is_superuser ? '1' : '0')
      } catch (e) {
        /* 401 由拦截器处理 */
      }
    },
    setQuota(q) {
      this.quota = q
    },
    logout() {
      this.token = ''
      this.username = ''
      this.is_staff = false
      this.is_superuser = false
      this.quota = { balance: 0, frozen: 0 }
      localStorage.removeItem('tsai_token')
      localStorage.removeItem('tsai_user')
      localStorage.removeItem('tsai_is_staff')
      localStorage.removeItem('tsai_is_superuser')
    },
  },
})
