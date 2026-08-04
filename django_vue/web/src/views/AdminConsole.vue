<template>
  <div class="admin">
    <div class="head">
      <div>
        <h2>管理后台</h2>
        <p>管理已接入的 API 渠道 / 自建 Agent，控制用户额度与可用功能</p>
      </div>
      <el-tag type="warning" effect="dark" round>管理员 · {{ user.username }}</el-tag>
    </div>

    <el-tabs v-model="tab" class="tabs">
      <!-- 概览 -->
      <el-tab-pane label="概览" name="dash">
        <div class="cards">
          <el-card shadow="never" class="stat"><div class="num">{{ d.users.total }}</div><div class="lbl">用户总数</div></el-card>
          <el-card shadow="never" class="stat"><div class="num ok">{{ d.users.active }}</div><div class="lbl">活跃用户</div></el-card>
          <el-card shadow="never" class="stat"><div class="num">{{ d.quota_pool.available }}</div><div class="lbl">额度池（可用）</div></el-card>
          <el-card shadow="never" class="stat"><div class="num warn">{{ d.quota_pool.frozen }}</div><div class="lbl">冻结中</div></el-card>
          <el-card shadow="never" class="stat"><div class="num">{{ d.channels.total }}</div><div class="lbl">渠道总数</div></el-card>
          <el-card shadow="never" class="stat"><div class="num">{{ d.channels.active }}</div><div class="lbl">启用中</div></el-card>
        </div>
        <div class="cards2">
          <el-card shadow="never" class="mini">
            <div class="mt">任务分布（按状态）</div>
            <div v-for="(v,k) in d.tasks.by_status" :key="k" class="kv">
              <span>{{ statusText(k) }}</span><b>{{ v }}</b>
            </div>
          </el-card>
          <el-card shadow="never" class="mini">
            <div class="mt">任务分布（按类型）</div>
            <div v-for="(v,k) in d.tasks.by_kind" :key="k" class="kv">
              <span>{{ k === 'video' ? '视频' : '图片' }}</span><b>{{ v }}</b>
            </div>
          </el-card>
          <el-card shadow="never" class="mini">
            <div class="mt">运营数据</div>
            <div class="kv"><span>累计获得额度</span><b>{{ d.quota_pool.total_granted }}</b></div>
            <div class="kv"><span>累计生成任务</span><b>{{ d.tasks.total }}</b></div>
            <div class="kv"><span>充值到账总额</span><b>{{ d.recharge_paid_total }}</b></div>
          </el-card>
        </div>
      </el-tab-pane>

      <!-- 渠道 / Agent 管理 -->
      <el-tab-pane label="渠道 / Agent" name="channels">
        <div class="bar">
          <el-button type="primary" @click="openChannel()">+ 新建渠道 / Agent</el-button>
        </div>
        <el-table :data="channels" class="tbl">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="name" label="名称" min-width="140" />
          <el-table-column label="类型" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="row.kind === 'AGENT' ? 'success' : 'primary'" effect="dark">
                {{ row.kind === 'AGENT' ? '自建 Agent' : 'API 渠道' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="描述" show-overflow-tooltip />
          <el-table-column label="单次消耗" width="100">
            <template #default="{ row }"><b>{{ row.cost_per_call }}</b></template>
          </el-table-column>
          <el-table-column label="启用" width="90">
            <template #default="{ row }">
              <el-switch v-model="row.is_active" @change="(v) => toggleChannel(row, v)" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140">
            <template #default="{ row }">
              <el-button text type="primary" @click="openChannel(row)">编辑</el-button>
              <el-button text type="danger" @click="removeChannel(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 授权管理 -->
      <el-tab-pane label="功能授权" name="grants">
        <el-card shadow="never" class="form-card">
          <div class="mt">为用户开通 / 调整可用渠道</div>
          <el-form :model="grantForm" label-width="90px" inline @submit.prevent>
            <el-form-item label="用户名" required>
              <el-input v-model="grantForm.username" placeholder="目标用户名" style="width:160px" />
            </el-form-item>
            <el-form-item label="渠道" required>
              <el-select v-model="grantForm.channel_id" placeholder="选择渠道" style="width:200px">
                <el-option v-for="c in channels" :key="c.id" :label="c.name" :value="c.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="可用">
              <el-switch v-model="grantForm.enabled" />
            </el-form-item>
            <el-form-item label="专属额度上限">
              <el-input-number v-model="grantForm.per_user_quota" :min="1" :controls="false" placeholder="不限制" style="width:130px" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="gloading" @click="saveGrant">保存授权</el-button>
            </el-form-item>
          </el-form>
        </el-card>
        <el-table :data="grants" class="tbl" style="margin-top:16px">
          <el-table-column prop="username" label="用户" width="140" />
          <el-table-column prop="channel_name" label="渠道 / Agent" min-width="140" />
          <el-table-column label="可用" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '可用' : '停用' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="专属上限" width="110">
            <template #default="{ row }">{{ row.per_user_quota || '不限制' }}</template>
          </el-table-column>
          <el-table-column label="已消耗" width="100">
            <template #default="{ row }"><b>{{ row.used_quota }}</b></template>
          </el-table-column>
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button text type="danger" @click="revokeGrant(row)">撤销</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 用户管理 -->
      <el-tab-pane label="用户管理" name="users">
        <el-table :data="users" class="tbl">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="username" label="用户名" min-width="130" />
          <el-table-column prop="email" label="邮箱" min-width="160" show-overflow-tooltip />
          <el-table-column label="角色" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.is_staff ? 'warning' : 'info'">{{ row.is_staff ? '管理员' : '用户' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="可用额度" width="100"><template #default="{ row }"><b>{{ row.balance }}</b></template></el-table-column>
          <el-table-column label="冻结" width="80"><template #default="{ row }">{{ row.frozen }}</template></el-table-column>
          <el-table-column label="累计获得" width="100"><template #default="{ row }">{{ row.total_granted }}</template></el-table-column>
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button text type="primary" @click="openAdjust(row)">调整额度</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 渠道编辑弹窗 -->
    <el-dialog v-model="chDlg" :title="chForm.id ? '编辑渠道' : '新建渠道 / Agent'">
      <el-form :model="chForm" label-width="100px">
        <el-form-item label="名称" required>
          <el-input v-model="chForm.name" placeholder="如：商品图生成 Agent" />
        </el-form-item>
        <el-form-item label="类型" required>
          <el-radio-group v-model="chForm.kind">
            <el-radio value="API">API 渠道</el-radio>
            <el-radio value="AGENT">自建 Agent</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="chForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="单次消耗" required>
          <el-input-number v-model="chForm.cost_per_call" :min="1" />
        </el-form-item>
        <el-form-item label="配置(JSON)">
          <el-input v-model="chForm.configText" type="textarea" :rows="3" placeholder='{"endpoint":"...","model":"..."}' />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="chForm.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="chDlg = false">取消</el-button>
        <el-button type="primary" :loading="chLoading" @click="saveChannel">保存</el-button>
      </template>
    </el-dialog>

    <!-- 额度调整弹窗 -->
    <el-dialog v-model="adjDlg" :title="'调整额度 · ' + (adjUser?.username || '')">
      <el-form :model="adjForm" label-width="100px">
        <el-form-item label="调整额度" required>
          <el-input-number v-model="adjForm.amount" :step="10" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="adjForm.reason" placeholder="如：活动赠送 / 违规扣减" />
        </el-form-item>
      </el-form>
      <el-alert type="info" :closable="false" title="正数发放，负数扣减" />
      <template #footer>
        <el-button @click="adjDlg = false">取消</el-button>
        <el-button type="primary" :loading="adjLoading" @click="saveAdjust">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '@/store/user'
import {
  getDashboard, listChannels, createChannel, updateChannel, deleteChannel,
  listGrants, createGrant, deleteGrant, listUsers, adminGrant,
} from '@/api/aiStudio'

const user = useUserStore()
const tab = ref('dash')

// 概览
const d = ref({
  users: { total: 0, active: 0 },
  quota_pool: { available: 0, frozen: 0, total_granted: 0 },
  channels: { total: 0, active: 0 },
  tasks: { by_status: {}, by_kind: {}, total: 0 },
  recharge_paid_total: 0,
})

// 渠道
const channels = ref([])
const chDlg = ref(false)
const chLoading = ref(false)
const chForm = ref(blankChannel())

// 授权
const grants = ref([])
const gloading = ref(false)
const grantForm = ref({ username: '', channel_id: null, enabled: true, per_user_quota: null })

// 用户
const users = ref([])
const adjDlg = ref(false)
const adjLoading = ref(false)
const adjUser = ref(null)
const adjForm = ref({ amount: 10, reason: '' })

function blankChannel() {
  return { id: null, name: '', kind: 'API', description: '', cost_per_call: 10, configText: '', is_active: true }
}

const statusText = (s) => ({ PENDING: '排队中', RUNNING: '生成中', SUCCESS: '成功', FAILED: '失败' }[s] || s)

const loadAll = async () => {
  try { d.value = await getDashboard() } catch (e) {}
  try { const r = await listChannels(); channels.value = r.channels || [] } catch (e) {}
  try { const r = await listGrants(); grants.value = r.grants || [] } catch (e) {}
  try { const r = await listUsers(); users.value = r.users || [] } catch (e) {}
}

// 渠道
const openChannel = (row) => {
  chForm.value = row ? { ...row, configText: row.config ? JSON.stringify(row.config, null, 2) : '' } : blankChannel()
  chDlg.value = true
}
const saveChannel = async () => {
  chLoading.value = true
  const payload = {
    name: chForm.value.name,
    kind: chForm.value.kind,
    description: chForm.value.description,
    cost_per_call: chForm.value.cost_per_call,
    is_active: chForm.value.is_active,
  }
  try {
    if (chForm.value.configText) payload.config = JSON.parse(chForm.value.configText)
    else payload.config = {}
  } catch (e) {
    chLoading.value = false
    ElMessage.error('配置 JSON 格式不正确')
    return
  }
  try {
    if (chForm.value.id) await updateChannel(chForm.value.id, payload)
    else await createChannel(payload)
    ElMessage.success('已保存')
    chDlg.value = false
    const r = await listChannels(); channels.value = r.channels || []
  } catch (e) {}
  finally { chLoading.value = false }
}
const toggleChannel = async (row, v) => {
  try { await updateChannel(row.id, { is_active: v }) } catch (e) { row.is_active = !v }
}
const removeChannel = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除渠道「${row.name}」？`, '提示', { type: 'warning' })
  } catch (e) { return }
  try {
    await deleteChannel(row.id)
    ElMessage.success('已删除')
    const r = await listChannels(); channels.value = r.channels || []
  } catch (e) {}
}

// 授权
const saveGrant = async () => {
  if (!grantForm.value.username || !grantForm.value.channel_id) {
    ElMessage.warning('请填写用户名并选择渠道')
    return
  }
  gloading.value = true
  try {
    await createGrant({ ...grantForm.value })
    ElMessage.success('授权已保存')
    const r = await listGrants(); grants.value = r.grants || []
  } catch (e) {}
  finally { gloading.value = false }
}
const revokeGrant = async (row) => {
  try {
    await deleteGrant({ username: row.username, channel_id: row.channel })
    ElMessage.success('已撤销')
    const r = await listGrants(); grants.value = r.grants || []
  } catch (e) {}
}

// 用户额度
const openAdjust = (row) => {
  adjUser.value = row
  adjForm.value = { amount: 10, reason: '' }
  adjDlg.value = true
}
const saveAdjust = async () => {
  adjLoading.value = true
  try {
    const resp = await adminGrant({ username: adjUser.value.username, amount: adjForm.value.amount, reason: adjForm.value.reason })
    ElMessage.success(`已${adjForm.value.amount >= 0 ? '发放' : '扣减'} ${Math.abs(adjForm.value.amount)} 额度`)
    adjDlg.value = false
    const r = await listUsers(); users.value = r.users || []
  } catch (e) {}
  finally { adjLoading.value = false }
}

onMounted(loadAll)
</script>

<style scoped>
.head { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; margin-bottom:18px; }
.head h2 { margin:0; font-size:24px; }
.head p { margin:4px 0 0; color:var(--sub); font-size:14px; }
.cards { display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-bottom:16px; }
.stat { background:var(--card); border:1px solid var(--line); color:var(--txt); text-align:center; }
.stat .num { font-size:30px; font-weight:900; }
.stat .num.ok { color:var(--ok); }
.stat .num.warn { color:var(--warn); }
.stat .lbl { color:var(--sub); font-size:13px; margin-top:4px; }
.cards2 { display:grid; grid-template-columns:repeat(3,1fr); gap:16px; }
.mini { background:var(--card); border:1px solid var(--line); color:var(--txt); }
.mini .mt { font-weight:700; margin-bottom:12px; }
.kv { display:flex; justify-content:space-between; color:var(--sub); font-size:14px; padding:6px 0; border-bottom:1px dashed var(--line); }
.kv b { color:var(--txt); }
.bar { margin-bottom:14px; }
.tbl { background:var(--card); border-radius:12px; }
.form-card { background:var(--card); border:1px solid var(--line); color:var(--txt); }
@media (max-width:768px){ .cards,.cards2{ grid-template-columns:1fr; } }
</style>
