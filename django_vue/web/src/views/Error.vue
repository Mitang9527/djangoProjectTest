<template>
  <div class="err">
    <div class="code grad">{{ code }}</div>
    <p class="msg">{{ message }}</p>
    <div class="actions">
      <el-button type="primary" @click="goHome">返回首页</el-button>
      <el-button @click="goBack">返回上一页</el-button>
      <a class="doc-link" href="/api/schema/swagger-ui/" target="_self">查看 API 文档</a>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const code = computed(() => {
  const c = Number(route.query.code ?? route.params.code)
  return Number.isFinite(c) && c >= 400 && c < 600 ? c : 404
})

const message = computed(() => {
  if (route.query.message) return String(route.query.message)
  const map = {
    400: '请求参数有误，请检查后重试。',
    401: '登录已失效，请重新登录。',
    403: '抱歉，您没有访问该页面的权限。',
    404: '抱歉，您访问的页面或接口不存在。',
    500: '服务器内部错误，请稍后重试或联系管理员。',
    502: '网关错误，服务暂时不可用。',
    503: '服务暂不可用，请稍后重试。',
  }
  return map[code.value] || '发生未知错误，请稍后重试。'
})

const goHome = () => router.push('/')
const goBack = () => router.back()
</script>

<style scoped>
.err {
  text-align: center;
  padding: 80px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  min-height: 60vh;
  justify-content: center;
}
.code {
  font-size: 120px;
  font-weight: 800;
  line-height: 1;
  letter-spacing: -2px;
}
.msg {
  color: var(--sub);
  font-size: 16px;
  margin: 0;
}
.actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
  flex-wrap: wrap;
  justify-content: center;
}
.doc-link {
  color: var(--brand2);
  font-size: 14px;
  margin-left: 4px;
}
.doc-link:hover {
  text-decoration: underline;
}
@media (max-width: 768px) {
  .code {
    font-size: 88px;
  }
}
</style>
