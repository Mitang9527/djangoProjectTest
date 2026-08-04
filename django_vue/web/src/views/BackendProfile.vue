<template>
  <div class="bk-page">
    <div class="head">
      <div><h2>个人中心</h2><p>管理你的账户信息、通知偏好与安全设置</p></div>
    </div>

    <div class="pf-grid">
      <el-card shadow="never" class="panel pf-card">
        <div class="avatar">{{ initial }}</div>
        <div class="uname">{{ user.username || '未登录' }}</div>
        <el-tag effect="dark" round :type="user.isAdmin ? 'warning' : 'info'">
          {{ user.isAdmin ? '管理员' : '普通会员' }}
        </el-tag>
        <ul class="meta">
          <li><span>用户 ID</span><b>#{{ uid }}</b></li>
          <li><span>注册时间</span><b>2026-01-12</b></li>
          <li><span>会员等级</span><b>黄金会员</b></li>
          <li><span>可用额度</span><b class="ok">{{ user.quota.balance }}</b></li>
        </ul>
      </el-card>

      <div class="pf-right">
        <el-card shadow="never" class="panel">
          <div class="panel-h"><h3>账户资料</h3></div>
          <el-form :model="form" label-width="84px" @submit.prevent>
            <el-form-item label="昵称"><el-input v-model="form.nickname" /></el-form-item>
            <el-form-item label="邮箱"><el-input v-model="form.email" placeholder="you@example.com" /></el-form-item>
            <el-form-item label="手机号"><el-input v-model="form.phone" placeholder="可选" /></el-form-item>
            <el-form-item><el-button type="primary" :loading="saving" @click="save">保存修改</el-button></el-form-item>
          </el-form>
        </el-card>

        <el-card shadow="never" class="panel">
          <div class="panel-h"><h3>通知偏好</h3></div>
          <div class="switch-row"><span>生成完成邮件通知</span><el-switch v-model="prefs.email" /></div>
          <div class="switch-row"><span>额度不足短信提醒</span><el-switch v-model="prefs.sms" /></div>
          <div class="switch-row"><span>营销活动推送</span><el-switch v-model="prefs.promo" /></div>
        </el-card>

        <el-card shadow="never" class="panel">
          <div class="panel-h"><h3>安全设置</h3></div>
          <el-form :model="pwd" label-width="84px" @submit.prevent>
            <el-form-item label="原密码"><el-input v-model="pwd.old" type="password" show-password /></el-form-item>
            <el-form-item label="新密码"><el-input v-model="pwd.nw" type="password" show-password /></el-form-item>
            <el-form-item label="确认密码"><el-input v-model="pwd.nw2" type="password" show-password /></el-form-item>
            <el-form-item><el-button @click="changePwd">更新密码</el-button></el-form-item>
          </el-form>
        </el-card>
      </div>
    </div>

    <el-alert class="tip" type="info" :closable="false" title="演示提示"
      description="本页为伪页面：资料保存、通知开关与密码修改均为本地模拟，不调用后端接口。" />
  </div>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/store/user'

const user = useUserStore()
const uid = 100237
const initial = computed(() =>
  user.username ? user.username.trim().charAt(0).toUpperCase() : 'U'
)

const form = reactive({ nickname: '', email: '', phone: '' })
const prefs = reactive({ email: true, sms: false, promo: false })
const pwd = reactive({ old: '', nw: '', nw2: '' })
const saving = ref(false)

const save = () => {
  saving.value = true
  setTimeout(() => {
    saving.value = false
    ElMessage.success('（演示）资料已保存')
  }, 400)
}
const changePwd = () => {
  if (!pwd.old || !pwd.nw) return ElMessage.warning('请填写原密码与新密码')
  if (pwd.nw !== pwd.nw2) return ElMessage.warning('两次输入的新密码不一致')
  ElMessage.success('（演示）密码已更新')
  pwd.old = pwd.nw = pwd.nw2 = ''
}
</script>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; }
.head h2 { margin: 0; font-size: 24px; }
.head p { margin: 4px 0 0; color: var(--sub); font-size: 14px; }
.pf-grid { display: grid; grid-template-columns: 280px 1fr; gap: 16px; align-items: start; }
.panel { background: var(--card); border: 1px solid var(--line); color: var(--txt); padding: 18px; border-radius: var(--radius); }
.pf-card { text-align: center; }
.avatar {
  width: 72px; height: 72px; border-radius: 50%; margin: 6px auto 12px;
  display: grid; place-items: center; font-size: 30px; font-weight: 800; color: #fff;
  background: linear-gradient(135deg, var(--brand), var(--brand2));
}
.uname { font-size: 18px; font-weight: 700; margin-bottom: 10px; }
.meta { list-style: none; padding: 14px 0 0; margin: 14px 0 0; border-top: 1px solid var(--line); text-align: left; }
.meta li { display: flex; justify-content: space-between; padding: 7px 0; font-size: 14px; color: var(--sub); }
.meta li b { color: var(--txt); font-weight: 600; }
.meta li b.ok { color: var(--ok); }
.pf-right { display: grid; gap: 16px; }
.panel-h { margin-bottom: 14px; }
.panel-h h3 { margin: 0; font-size: 16px; }
.switch-row { display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-bottom: 1px dashed var(--line); }
.switch-row:last-child { border-bottom: none; }
.tip { margin-top: 16px; }
@media (max-width: 880px) { .pf-grid { grid-template-columns: 1fr; } }
</style>
