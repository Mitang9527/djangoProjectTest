<template>
  <div class="bk">
    <aside class="bk-side">
      <div class="bk-logo">图灵智绘 <span class="grad">AI</span><span class="bk-sub">工作台</span></div>
      <el-menu :default-active="activeChild" class="bk-menu" @select="onSelect">
        <el-menu-item index="/backend/ai"><span class="ic">🎨</span> AI 生成业务</el-menu-item>
        <el-menu-item index="/backend/profile"><span class="ic">👤</span> 个人中心</el-menu-item>
        <el-menu-item index="/backend/recharge"><span class="ic">💎</span> 个人充值</el-menu-item>
      </el-menu>
      <div class="bk-foot">演示后台 · 纯前端</div>
    </aside>
    <main class="bk-main">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const activeChild = computed(() =>
  route.path.startsWith('/backend/') ? route.path : '/backend/ai'
)
const onSelect = (index) => {
  if (index !== route.path) router.push(index)
}
</script>

<style scoped>
.bk { display: flex; gap: 20px; align-items: flex-start; }
.bk-side {
  width: 220px; flex: none; position: sticky; top: 84px;
  background: var(--card); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 14px; align-self: flex-start;
}
.bk-logo { font-weight: 800; font-size: 18px; padding: 6px 8px 14px; }
.bk-sub { font-size: 12px; color: var(--sub); margin-left: 6px; font-weight: 600; }
.bk-menu { border: none; background: transparent; }
.bk-menu :deep(.el-menu-item) { color: var(--sub); border-radius: 10px; margin-bottom: 4px; height: 44px; }
.bk-menu :deep(.el-menu-item.is-active) {
  background: linear-gradient(90deg, rgba(124, 92, 255, 0.18), rgba(55, 198, 255, 0.12));
  color: var(--txt);
}
.bk-menu .ic { margin-right: 8px; }
.bk-foot { margin-top: 14px; padding: 10px 8px 2px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--line); }
.bk-main { flex: 1; min-width: 0; }
@media (max-width: 768px) {
  .bk { flex-direction: column; }
  .bk-side { width: 100%; position: static; }
  .bk-menu { display: flex; flex-wrap: wrap; gap: 6px; }
  .bk-menu :deep(.el-menu-item) { margin-bottom: 0; }
  .bk-foot { display: none; }
}
</style>
