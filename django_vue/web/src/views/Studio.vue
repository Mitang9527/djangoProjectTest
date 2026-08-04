<template>
  <div>
    <div v-if="!user.token" class="login-tip">
      <el-alert type="info" show-icon :closable="false" title="请先登录" description="登录后可生成并查看额度（演示账号随意填）" />
      <el-button type="primary" @click="goLogin">去登录</el-button>
    </div>

    <div class="studio-head">
      <div>
        <h2>创作工作台</h2>
        <p>上传参考图、描述需求，实时查看额度消耗与生成结果</p>
      </div>
      <el-tag v-if="user.token" type="info" effect="dark" round>当前额度 {{ user.quota.balance }}</el-tag>
    </div>

    <el-alert
      v-if="selectedChannel"
      class="ch-banner"
      type="primary"
      :closable="false"
      show-icon
    >
      <template #title>
        正在使用渠道：<b>{{ selectedChannel.name }}</b>
        <el-tag size="small" class="ml">{{ selectedChannel.kind === 'AGENT' ? '自建 Agent' : 'API 渠道' }}</el-tag>
      </template>
      每次调用消耗 <b>{{ selectedChannel.cost_per_call }}</b> 额度（按数量计）
    </el-alert>

    <el-tabs v-model="kind" class="kind-tabs">
      <el-tab-pane label="图片生成" name="image" />
      <el-tab-pane label="视频生成" name="video" />
    </el-tabs>

    <div class="studio-grid">
      <!-- 左：参数 -->
      <el-card shadow="never" class="panel">
        <el-upload
          class="uploader"
          drag
          :auto-upload="false"
          :show-file-list="false"
          :on-change="onFileChange"
          accept="image/*"
        >
          <div v-if="previewUrl" class="preview"><img :src="previewUrl" alt="ref" /></div>
          <div v-else>
            <div class="up-icon">📤</div>
            <div>点击或拖拽上传参考图（可选）</div>
          </div>
        </el-upload>

        <el-input
          v-model="prompt"
          type="textarea"
          :rows="3"
          placeholder="描述需求，例如：为这款水杯生成 ins 风白底主图，柔和自然光"
          style="margin-top:16px"
        />

        <div class="row2">
          <el-select v-model="styleVal" placeholder="风格">
            <el-option v-for="s in styles" :key="s" :label="s" :value="s" />
          </el-select>
          <el-select v-model="sizeVal" placeholder="尺寸">
            <el-option v-for="s in sizes" :key="s" :label="s" :value="s" />
          </el-select>
        </div>
        <div class="row2">
          <el-select v-model="countVal" placeholder="数量">
            <el-option v-for="c in [1, 2, 4]" :key="c" :label="c + ' 张'" :value="c" />
          </el-select>
          <el-select v-model="resolutionVal" placeholder="分辨率">
            <el-option label="标准" value="standard" />
            <el-option label="高清" value="hd" />
            <el-option label="4K" value="4k" />
          </el-select>
        </div>

        <div class="cost-hint">
          预计消耗 <b>{{ unitCost }} 额度</b>
          <span v-if="!selectedChannel && kind === 'video'">（视频 ×4）</span>
          <span v-if="selectedChannel">（按渠道单价 × 数量）</span>
        </div>

        <el-button type="primary" class="gen-btn" :loading="loading" @click="onGenerate">
          {{ loading ? '生成中…' : '开始生成' }}
        </el-button>
        <el-progress v-if="loading" :percentage="Math.floor(progress)" :stroke-width="6" style="margin-top:12px" />
      </el-card>

      <!-- 右：结果 -->
      <el-card shadow="never" class="panel">
        <div class="results-top">
          <h3>🎨 生成结果</h3>
          <span class="cnt">{{ results.length }} 张</span>
        </div>
        <div v-if="results.length === 0" class="empty">
          <div class="big">🪄</div>
          <div>设置好参数后点击「开始生成」<br />结果会实时出现在这里</div>
        </div>
        <div class="gallery">
          <div v-for="(r, i) in results" :key="i" class="item">
            <img :src="r" alt="result" />
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/store/user'
import { generate as apiGenerate, listTasks, listMyChannels } from '@/api/aiStudio'

const route = useRoute()
const router = useRouter()
const user = useUserStore()

const kind = ref('image')
const prompt = ref('')
const styleVal = ref('白底主图')
const sizeVal = ref('1:1')
const countVal = ref(1)
const resolutionVal = ref('standard')
const refBase64 = ref(null)
const previewUrl = ref('')
const loading = ref(false)
const progress = ref(0)
const results = ref([])
const selectedChannel = ref(null)

const styles = ['白底主图', '场景合成', 'ins 风', '极简', '国潮']
const sizes = ['1:1', '3:4', '4:3', '16:9']

const unitCost = computed(() => {
  if (selectedChannel.value) {
    return selectedChannel.value.cost_per_call * countVal.value
  }
  const base = { standard: 5, hd: 8, '4k': 12 }[resolutionVal.value] || 5
  return kind.value === 'video' ? base * 4 : base
})

const onFileChange = (file) => {
  const raw = file.raw
  if (!raw) return
  const reader = new FileReader()
  reader.onload = (e) => {
    refBase64.value = e.target.result
    previewUrl.value = e.target.result
  }
  reader.readAsDataURL(raw)
}

const onGenerate = async () => {
  if (!user.token) {
    goLogin()
    return
  }
  loading.value = true
  progress.value = 0
  const timer = setInterval(() => {
    if (progress.value < 90) progress.value += Math.random() * 15
  }, 250)
  try {
    const resp = await apiGenerate({
      kind: kind.value,
      prompt: prompt.value,
      ref_image: refBase64.value || '',
      style: styleVal.value,
      size: sizeVal.value,
      resolution: resolutionVal.value,
      count: countVal.value,
      channel_id: selectedChannel.value ? selectedChannel.value.id : undefined,
    })
    results.value = [...resp.result_urls, ...results.value]
    user.setQuota(resp.quota)
    progress.value = 100
    ElMessage.success(`生成成功，消耗 ${resp.cost} 额度`)
  } catch (e) {
    // 错误已由请求拦截器提示
  } finally {
    clearInterval(timer)
    loading.value = false
  }
}

const goLogin = () => router.push('/login?redirect=' + encodeURIComponent('/studio'))

onMounted(async () => {
  if (!user.token) return
  // 若从「我的功能」带 channel_id 进入，定位渠道信息
  const cid = route.query.channel_id
  if (cid) {
    try {
      const data = await listMyChannels()
      selectedChannel.value = (data.channels || []).find((c) => String(c.id) === String(cid)) || null
    } catch (e) { /* ignore */ }
  }
  try {
    const data = await listTasks()
    const all = []
    ;(data.tasks || []).forEach((t) => {
      if (t.result_urls && t.result_urls.length) all.push(...t.result_urls)
    })
    results.value = all.slice(0, 24)
  } catch (e) {
    /* ignore */
  }
})
</script>

<style scoped>
.login-tip { display:flex; align-items:center; gap:14px; margin-bottom:16px; flex-wrap:wrap; }
.ch-banner { margin-bottom:16px; }
.ch-banner .ml { margin-left:8px; }
.studio-head { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; margin-bottom:16px; }
.studio-head h2 { margin:0; font-size:24px; }
.studio-head p { margin:4px 0 0; color:var(--sub); font-size:14px; }
.kind-tabs { margin-bottom:8px; }
.studio-grid { display:grid; grid-template-columns:380px 1fr; gap:20px; }
.panel { background:var(--card); border:1px solid var(--line); color:var(--txt); }
.uploader :deep(.el-upload-dragger) { background:var(--bg2); border:1px dashed var(--line); padding:24px; }
.preview img { width:96px; height:96px; object-fit:cover; border-radius:10px; }
.up-icon { font-size:36px; }
.row2 { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:14px; }
.cost-hint { margin-top:14px; background:var(--bg2); border:1px solid var(--line); border-radius:10px; padding:11px 13px; font-size:14px; color:var(--sub); display:flex; justify-content:space-between; }
.gen-btn { width:100%; margin-top:16px; }
.results-top { display:flex; align-items:center; justify-content:space-between; margin-bottom:16px; }
.results-top h3 { margin:0; }
.cnt { color:var(--sub); font-size:13px; }
.empty { display:grid; place-items:center; height:320px; color:var(--muted); text-align:center; gap:8px; }
.gallery { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:14px; }
.item { border-radius:12px; overflow:hidden; border:1px solid var(--line); background:var(--card2); }
.item img { width:100%; aspect-ratio:1/1; object-fit:cover; display:block; }
@media (max-width:980px){ .studio-grid{ grid-template-columns:1fr; } }
</style>
