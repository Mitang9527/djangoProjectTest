import { createRouter, createWebHashHistory } from 'vue-router'
import Home from '@/views/Home.vue'
import Studio from '@/views/Studio.vue'
import Login from '@/views/Login.vue'
import UserConsole from '@/views/UserConsole.vue'
import AdminConsole from '@/views/AdminConsole.vue'
import Backend from '@/views/Backend.vue'
import BackendAi from '@/views/BackendAi.vue'
import BackendProfile from '@/views/BackendProfile.vue'
import BackendRecharge from '@/views/BackendRecharge.vue'
import Error from '@/views/Error.vue'
import { useUserStore } from '@/store/user'

const routes = [
  { path: '/', name: 'home', component: Home },
  { path: '/studio', name: 'studio', component: Studio, meta: { requiresAuth: true } },
  { path: '/login', name: 'login', component: Login },
  {
    path: '/console',
    name: 'console',
    component: UserConsole,
    meta: { requiresAuth: true, title: '我的控制台' },
  },
  {
    path: '/admin',
    name: 'admin',
    component: AdminConsole,
    meta: { requiresAuth: true, requiresAdmin: true, title: '管理后台' },
  },
  {
    path: '/backend',
    name: 'backend',
    component: Backend,
    redirect: '/backend/ai',
    meta: { requiresAuth: true, title: '工作台' },
    children: [
      { path: 'ai', name: 'backend-ai', component: BackendAi, meta: { title: 'AI 生成业务' } },
      { path: 'profile', name: 'backend-profile', component: BackendProfile, meta: { title: '个人中心' } },
      { path: 'recharge', name: 'backend-recharge', component: BackendRecharge, meta: { title: '个人充值' } },
    ],
  },
  // 公共错误页（免登录兜底）：未知路径 → 404；可通过 ?code=500&message=... 自定义
  { path: '/:pathMatch(.*)*', name: 'error', component: Error, meta: { title: '出错了' } },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.beforeEach((to) => {
  const user = useUserStore()
  const token = localStorage.getItem('tsai_token')
  if (to.meta.requiresAuth && !token) {
    return '/login?redirect=' + encodeURIComponent(to.fullPath)
  }
  if (to.meta.requiresAdmin && !user.isAdmin) {
    // 非管理员不得进入管理后台，退回个人控制台
    return '/console'
  }
  return true
})

export default router
