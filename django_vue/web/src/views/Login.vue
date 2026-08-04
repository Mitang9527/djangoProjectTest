<template>
  <div class="login-wrap">
    <el-card class="login-card" shadow="never">
      <h2>登录 / 注册</h2>
      <p class="sub">演示模式：输入任意用户名即创建账号并获赠 50 额度</p>
      <el-input
        v-model="username"
        placeholder="手机号 / 邮箱 / 用户名"
        @keyup.enter="onLogin"
      />
      <el-button type="primary" class="lb" :loading="loading" @click="onLogin">
        登录 / 注册
      </el-button>
      <el-button text class="back" @click="router.push('/')">返回首页</el-button>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/store/user'

const user = useUserStore()
const route = useRoute()
const router = useRouter()
const username = ref('')
const loading = ref(false)

const onLogin = async () => {
  if (!username.value.trim()) {
    ElMessage.warning('请输入用户名')
    return
  }
  loading.value = true
  try {
    await user.login(username.value.trim())
    ElMessage.success('登录成功，获赠 50 额度 🎉')
    // 登录后根据角色纠正落地页：管理员优先进后台，普通用户不能进后台
    let target = route.query.redirect
    if (user.isAdmin) {
      if (target === '/console') target = '/admin'
    } else if (target === '/admin') {
      target = '/console'
    }
    router.push(target || (user.isAdmin ? '/admin' : '/console'))
  } catch (e) {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  display: grid;
  place-items: center;
  min-height: 60vh;
}
.login-card {
  width: 100%;
  max-width: 380px;
  background: var(--card);
  border: 1px solid var(--line);
}
.login-card h2 {
  margin: 0 0 6px;
}
.sub {
  color: var(--sub);
  font-size: 13px;
  margin: 0 0 18px;
}
.login-card :deep(.el-input) {
  margin-bottom: 14px;
}
.lb {
  width: 100%;
}
.back {
  width: 100%;
  margin-top: 6px;
}
</style>
