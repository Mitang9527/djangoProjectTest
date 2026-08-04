<template>
  <div class="bk-page">
    <div class="head">
      <div>
        <h2>AI 生成业务</h2>
        <p>管理你的创作任务、查看额度消耗与生成成果</p>
      </div>
      <el-button type="primary" @click="goStudio">＋ 开始创作</el-button>
    </div>

    <div class="cards">
      <el-card v-for="s in stats" :key="s.lbl" shadow="never" class="stat">
        <div class="num" :class="s.cls">{{ s.num }}</div>
        <div class="lbl">{{ s.lbl }}</div>
      </el-card>
    </div>

    <div class="bk-grid">
      <el-card shadow="never" class="panel">
        <div class="panel-h"><h3>📋 最近生成任务</h3><span class="sub">演示数据</span></div>
        <el-table :data="tasks" class="tbl">
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
          <el-table-column prop="time" label="时间" width="170" />
        </el-table>
      </el-card>

      <el-card shadow="never" class="panel">
        <div class="panel-h"><h3>🖼️ 成果画廊</h3><span class="sub">最近 8 张</span></div>
        <div class="gallery">
          <div v-for="(g, i) in gallery" :key="i" class="item" :style="{ background: g }"></div>
        </div>
      </el-card>
    </div>

    <el-alert class="tip" type="info" :closable="false" title="说明"
      description="本页为同风格演示后台，任务与画廊均为本地演示数据；接入真实数据时复用 /api/ai_studio 接口即可。" />
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()

const stats = [
  { num: 128, lbl: '本月生成', cls: '' },
  { num: 640, lbl: '本月消耗额度', cls: 'warn' },
  { num: '96%', lbl: '成功率', cls: 'ok' },
  { num: 2, lbl: '进行中', cls: '' },
]

const tasks = [
  { id: 1042, kind: 'image', prompt: 'ins 风白底水杯主图', cost: 5, status: 'SUCCESS', time: '2026-08-04 14:02' },
  { id: 1041, kind: 'video', prompt: '产品 15s 宣传短片', cost: 32, status: 'RUNNING', time: '2026-08-04 13:48' },
  { id: 1040, kind: 'image', prompt: '国潮风茶叶包装', cost: 8, status: 'SUCCESS', time: '2026-08-04 11:20' },
  { id: 1039, kind: 'image', prompt: '极简风 App 图标', cost: 5, status: 'FAILED', time: '2026-08-03 22:11' },
  { id: 1038, kind: 'image', prompt: '场景合成咖啡杯', cost: 5, status: 'SUCCESS', time: '2026-08-03 19:05' },
]

const gallery = [
  'linear-gradient(135deg,#7c5cff,#37c6ff)',
  'linear-gradient(135deg,#ff5c7c,#ffb020)',
  'linear-gradient(135deg,#23d18b,#37c6ff)',
  'linear-gradient(135deg,#7c5cff,#ff5c7c)',
  'linear-gradient(135deg,#ffb020,#7c5cff)',
  'linear-gradient(135deg,#37c6ff,#23d18b)',
  'linear-gradient(135deg,#ff5c7c,#7c5cff)',
  'linear-gradient(135deg,#23d18b,#ffb020)',
]

const goStudio = () => router.push('/studio')
const statusType = (s) => ({ PENDING: 'info', RUNNING: 'warning', SUCCESS: 'success', FAILED: 'danger' }[s] || 'info')
const statusText = (s) => ({ PENDING: '排队中', RUNNING: '生成中', SUCCESS: '成功', FAILED: '失败' }[s] || s)
</script>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; }
.head h2 { margin: 0; font-size: 24px; }
.head p { margin: 4px 0 0; color: var(--sub); font-size: 14px; }
.cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.stat { background: var(--card); border: 1px solid var(--line); color: var(--txt); text-align: center; }
.stat .num { font-size: 34px; font-weight: 900; }
.stat .num.ok { color: var(--ok); }
.stat .num.warn { color: var(--warn); }
.stat .lbl { color: var(--sub); font-size: 13px; margin-top: 4px; }
.bk-grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: 16px; margin-top: 16px; }
.panel { background: var(--card); border: 1px solid var(--line); color: var(--txt); padding: 18px; border-radius: var(--radius); }
.panel-h { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.panel-h h3 { margin: 0; font-size: 16px; }
.sub { color: var(--sub); font-size: 12px; }
.tbl :deep(.el-table),
.tbl :deep(.el-table__expanded-cell),
.tbl :deep(.el-table th),
.tbl :deep(.el-table tr),
.tbl :deep(.el-table td) { background: var(--card) !important; color: var(--txt) !important; border-color: var(--line) !important; }
.tbl :deep(.el-table__inner-wrapper::before) { display: none; }
.tbl :deep(.el-table__row:hover > td) { background: var(--card2) !important; }
.tbl :deep(.el-table thead th) { background: var(--bg2) !important; color: var(--sub) !important; font-weight: 600; }
.gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(80px, 1fr)); gap: 10px; }
.item { aspect-ratio: 1 / 1; border-radius: 12px; border: 1px solid var(--line); }
.tip { margin-top: 16px; }
@media (max-width: 980px) { .bk-grid { grid-template-columns: 1fr; } }
@media (max-width: 768px) { .cards { grid-template-columns: repeat(2, 1fr); } }
</style>
