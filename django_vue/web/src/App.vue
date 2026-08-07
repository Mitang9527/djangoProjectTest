<template>
  <el-config-provider>
    <div class="app-root">
      <!-- 桌面顶栏 -->
      <header v-if="!isMobile" class="topbar">
        <div class="brand" @click="go('/')">图灵智绘 <span class="grad">AI</span></div>
        <el-menu
          mode="horizontal"
          :ellipsis="false"
          :default-active="activeMenu"
          class="menu"
          @select="onMenuSelect"
        >
          <el-menu-item index="/">首页</el-menu-item>
          <el-menu-item :index="consolePath">{{ consoleLabel }}</el-menu-item>
          <el-menu-item index="/backend">工作台</el-menu-item>
        </el-menu>
        <div class="right">
          <el-tag v-if="user.token" type="info" effect="dark" round>
            额度 {{ user.quota.balance }}
          </el-tag>
          <el-tag v-if="user.isAdmin" type="warning" effect="dark" round>管理员</el-tag>
          <el-button v-if="!user.token" type="primary" @click="go('/login')">登录</el-button>
          <el-button v-else text @click="doLogout()">退出</el-button>
        </div>
      </header>

      <!-- 移动顶栏（Vant） -->
      <van-nav-bar
        v-else
        :title="user.isAdmin ? '图灵智绘 · 管理' : '图灵智绘 AI'"
        left-text="菜单"
        :left-arrow="false"
        @click-left="showMenu = true"
      />

      <van-popup v-if="isMobile" v-model:show="showMenu" position="left" class="mobile-menu">
        <div class="m-brand" @click="go('/')">图灵智绘 <span class="grad">AI</span></div>
        <van-cell title="首页" @click="go('/')" />
        <van-cell :title="consoleLabel" @click="go(consolePath)" />
        <van-cell title="工作台" @click="go('/backend')" />
        <van-cell v-if="!user.token" title="登录" @click="go('/login')" />
        <van-cell v-else :title="user.isAdmin ? '退出登录（管理员）' : '退出登录'" @click="doLogout()" />
      </van-popup>

      <main class="content">
        <router-view />
      </main>

      <!-- 移动底栏（Vant） -->
      <van-tabbar v-if="isMobile" route>
        <van-tabbar-item to="/" icon="home-o">首页</van-tabbar-item>
        <van-tabbar-item :to="consolePath" icon="apps-o">{{ consoleShort }}</van-tabbar-item>
        <van-tabbar-item to="/backend" icon="brush-o">工作台</van-tabbar-item>
      </van-tabbar>
    </div>
  </el-config-provider>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/store/user'

const user = useUserStore()
const route = useRoute()
const router = useRouter()
const isMobile = ref(false)
const showMenu = ref(false)

const consolePath = computed(() => (user.isAdmin ? '/admin' : '/console'))
const consoleLabel = computed(() => (user.isAdmin ? '管理后台' : '我的控制台'))
const consoleShort = computed(() => (user.isAdmin ? '后台' : '控制台'))

// 工作台（/backend 及其子页）在顶栏高亮时统一映射到 /backend
const activeMenu = computed(() =>
  route.path.startsWith('/backend') ? '/backend' : route.path
)

const check = () => {
  isMobile.value = window.innerWidth <= 768
}
onMounted(() => {
  check()
  window.addEventListener('resize', check)
  // 刷新页面后重新拉取身份（isAdmin / 额度）避免角色丢失
  if (user.token) user.fetchMe()
})
onUnmounted(() => window.removeEventListener('resize', check))

const go = (p) => {
  showMenu.value = false
  router.push(p)
}

// el-menu 未开启 router 模式，这里手动分发：其余走前端路由
const onMenuSelect = (index) => {
  if (
    index !== route.path &&
    !(index === '/backend' && route.path.startsWith('/backend'))
  ) {
    router.push(index)
  }
}
const doLogout = () => {
  showMenu.value = false
  user.logout()
  router.push('/')
}
</script>

<style scoped>
.mobile-menu {
  width: 70%;
  max-width: 280px;
  padding: 16px 0;
  background: var(--bg2);
}
.m-brand {
  font-weight: 800;
  font-size: 18px;
  padding: 8px 16px 16px;
}
@media (max-width: 768px) {
  .content {
    padding-bottom: 60px;
  }
}
</style>
