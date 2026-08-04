<template>
  <div class="console">
    <!-- 顶部欢迎 -->
    <div class="head">
      <div>
        <h2>我的控制台</h2>
        <p>欢迎，<b>{{ user.username }}</b> · 在这里查看额度、使用功能、管理充值</p>
      </div>
      <el-tag type="info" effect="dark" round>可用额度 {{ user.quota.balance }}</el-tag>
    </div>

    <el-tabs v-model="tab" class="tabs">
      <!-- 我的额度 -->
      <el-tab-pane label="我的额度" name="quota">
        <div class="cards">
          <el-card shadow="never" class="stat">
            <div class="num ok">{{ user.quota.balance }}</div>
            <div class="lbl">可用额度</div>
          </el-card>
          <el-card shadow="never" class="stat">
            <div class="num warn">{{ user.quota.frozen }}</div>
            <div class="lbl">冻结中</div>
          </el-card>
          <el-card shadow="never" class="stat">
            <div class="num">{{ user.quota.total_granted }}</div>
            <div class="lbl">累计获得</div>
          </el-card>
        </div>
        <el-alert
          class="tip"
          type="success"
          :closable="false"
          title="额度说明"
          description="注册赠送 50 额度；生成图片/视频按渠道单次消耗计费；额度不足时无法发起生成。"
        />
      </el-tab-pane>

      <!-- 我的功能 -->
      <el-tab-pane label="我的功能" name="features">
        <div v-if="channels.length === 0" class="empty">
          <div class="big">🧩</div>
          <div>暂无可用渠道 / Agent，请联系管理员为你开通</div>
        </div>
        <div class="grid feat">
          <el-card
            v-for="c in channels"
            :key="c.id"
            shadow="hover"
            class="feat-card"
          >
            <div class="row">
              <span class="fname">{{ c.name }}</span>
              <el-tag size="small" :type="c.kind === 'AGENT' ? 'success' : 'primary'" effect="dark">
                {{ c.kind === 'AGENT' ? '自建 Agent' : 'API 渠道' }}
              </el-tag>
            </div>
            <p class="desc">{{ c.description || '暂无描述' }}</p>
            <div class="cost">每次调用消耗 <b>{{ c.cost_per_call }}</b> 额度</div>
            <el-button type="primary" round @click="useChannel(c)">去使用 →</el-button>
          </el-card>
        </div>
      </el-tab-pane>

      <!-- 充值 -->
      <el-tab-pane label="充值" name="recharge">
        <el-card shadow="never" class="form-card">
          <el-form :model="rechargeForm" label-width="90px" @submit.prevent>
            <el-form-item label="充值额度">
              <el-input-number v-model="rechargeForm.amount" :min="1" :max="1000000" />
            </el-form-item>
            <el-form-item label="支付方式">
              <el-radio-group v-model="rechargeForm.method">
                <el-radio value="mock">模拟支付（记账）</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="rloading" @click="onRecharge">确认充值</el-button>
            </el-form-item>
          </el-form>
          <el-alert type="info" :closable="false" title="说明：当前为记账式 MVP，提交即入账，后续可接入真实支付。" />
        </el-card>
      </el-tab-pane>

      <!-- 我的任务 -->
      <el-tab-pane label="我的任务" name="tasks">
        <div v-if="tasks.length === 0" class="empty">
          <div class="big">🗂️</div>
          <div>还没有生成任务，去「我的功能」挑一个渠道开始吧</div>
        </div>
        <el-table v-else :data="tasks" class="tbl">
          <el-table-column prop="id" label="ID" width="80" />
          <el-table-column label="类型" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.kind === 'video' ? 'warning' : 'info'">
                {{ row.kind === 'video' ? '视频' : '图片' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="prompt" label="描述" show-overflow-tooltip />
          <el-table-column label="消耗" width="90">
            <template #default="{ row }"><b>{{ row.cost }}</b></template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="时间" width="170">
            <template #default="{ row }">{{ fmt(row.created_at) }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/store/user'
import { listMyChannels, listTasks, recharge as apiRecharge } from '@/api/aiStudio'

const router = useRouter()
const user = useUserStore()

const tab = ref('quota')
const channels = ref([])
const tasks = ref([])
const rechargeForm = ref({ amount: 100, method: 'mock' })
const rloading = ref(false)

const loadChannels = async () => {
  try {
    const data = await listMyChannels()
    channels.value = data.channels || []
  } catch (e) { /* ignore */ }
}
const loadTasks = async () => {
  try {
    const data = await listTasks()
    tasks.value = data.tasks || []
  } catch (e) { /* ignore */ }
}

const useChannel = (c) => {
  router.push('/studio?channel_id=' + c.id)
}

const onRecharge = async () => {
  rloading.value = true
  try {
    const resp = await apiRecharge(rechargeForm.value.amount, rechargeForm.value.method)
    user.setQuota({ balance: resp.balance, frozen: resp.frozen })
    ElMessage.success(`充值成功，到账 ${resp.quota_amount} 额度`)
    tab.value = 'quota'
  } catch (e) { /* 拦截器提示 */ }
  finally { rloading.value = false }
}

const statusType = (s) =>
  ({ PENDING: 'info', RUNNING: 'warning', SUCCESS: 'success', FAILED: 'danger' }[s] || 'info')
const statusText = (s) =>
  ({ PENDING: '排队中', RUNNING: '生成中', SUCCESS: '成功', FAILED: '失败' }[s] || s)
const fmt = (t) => (t ? new Date(t).toLocaleString('zh-CN') : '')

onMounted(() => {
  loadChannels()
  loadTasks()
})
</script>

<style scoped>
.head { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; margin-bottom:18px; }
.head h2 { margin:0; font-size:24px; }
.head p { margin:4px 0 0; color:var(--sub); font-size:14px; }
.cards { display:grid; grid-template-columns:repeat(3,1fr); gap:16px; }
.stat { background:var(--card); border:1px solid var(--line); color:var(--txt); text-align:center; }
.stat .num { font-size:34px; font-weight:900; }
.stat .num.ok { color:var(--ok); }
.stat .num.warn { color:var(--warn); }
.stat .lbl { color:var(--sub); font-size:13px; margin-top:4px; }
.tip { margin-top:18px; }
.grid.feat { display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:16px; }
.feat-card { background:var(--card); border:1px solid var(--line); color:var(--txt); }
.feat-card .row { display:flex; align-items:center; justify-content:space-between; gap:8px; }
.fname { font-weight:700; font-size:16px; }
.desc { color:var(--sub); font-size:13px; min-height:34px; margin:10px 0; }
.cost { color:var(--sub); font-size:13px; margin-bottom:14px; }
.cost b { color:var(--brand2); }
.form-card { background:var(--card); border:1px solid var(--line); color:var(--txt); max-width:520px; }
.tbl { background:var(--card); border-radius:12px; }
.empty { display:grid; place-items:center; height:240px; color:var(--muted); text-align:center; gap:8px; }
.empty .big { font-size:42px; }
@media (max-width:768px){ .cards{ grid-template-columns:1fr; } }
</style>
