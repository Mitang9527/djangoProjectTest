import { createRouter, createWebHashHistory } from 'vue-router'
import Home from '@/views/Home.vue'
import Studio from '@/views/Studio.vue'
import Login from '@/views/Login.vue'
import UserConsole from '@/views/UserConsole.vue'
import AdminConsole from '@/views/AdminConsole.vue'
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
