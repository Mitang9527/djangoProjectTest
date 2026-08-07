<template>
  <div>
    <!-- Hero -->
    <section class="hero">
      <h1>用一句话，生成<span class="grad">电商级商品图 &amp; 视频</span></h1>
      <p>上传参考图或描述需求，AI 自动生成白底图、场景图与短视频。注册即送额度，按生成扣费，Web 与手机浏览器无缝同享。</p>
      <div class="cta">
        <template v-if="!user.token">
          <el-button type="primary" size="large" round @click="toStudio">免费试用 →</el-button>
          <el-button size="large" round plain @click="scrollTo('price')">查看套餐</el-button>
        </template>
        <template v-else>
          <el-button type="primary" size="large" round @click="toConsoleOrAdmin">
            {{ user.isAdmin ? '进入管理后台' : '进入我的控制台' }} →
          </el-button>
          <el-button size="large" round plain @click="toStudio">去工作台</el-button>
        </template>
      </div>
      <div class="tags">
        <el-tag v-for="t in tags" :key="t" effect="dark" round>{{ t }}</el-tag>
      </div>
    </section>

    <!-- 功能 -->
    <section id="feat" class="section">
      <h2 class="sec-title">一个工作台，覆盖电商全链路素材</h2>
      <p class="sec-sub">从主图到详情页视频，皆由同一套额度与任务系统驱动</p>
      <div class="grid feat">
        <el-card v-for="f in features" :key="f.title" shadow="hover">
          <div class="ic">{{ f.icon }}</div>
          <h3>{{ f.title }}</h3>
          <p>{{ f.desc }}</p>
        </el-card>
      </div>
    </section>

    <!-- 套餐 -->
    <section id="price" class="section">
      <h2 class="sec-title">简单透明的额度套餐</h2>
      <p class="sec-sub">注册赠送 50 额度，生成图片按张扣费，视频按秒计费</p>
      <div class="grid price">
        <el-card
          v-for="(p, i) in plans"
          :key="p.name"
          shadow="hover"
          :class="{ hot: i === 1 }"
        >
          <el-tag v-if="i === 1" type="primary" effect="dark" class="badge">最受欢迎</el-tag>
          <div class="pname">{{ p.name }}</div>
          <div class="pdesc">{{ p.desc }}</div>
          <div class="pamt">{{ p.amt }}<small>{{ p.unit }}</small></div>
          <ul>
            <li v-for="li in p.items" :key="li">{{ li }}</li>
          </ul>
          <el-button
            :type="i === 1 ? 'primary' : 'default'"
            round
            block
            @click="toStudio"
          >
            {{ p.btn }}
          </el-button>
        </el-card>
      </div>
    </section>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/store/user'

const router = useRouter()
const user = useUserStore()

const tags = ['白底商品图', '场景合成', 'AI 模特', '短视频生成', '批量出图']
const features = [
  { icon: '🖼️', title: 'AI 商品图', desc: '白底、场景、平铺、细节放大，一键生成多版候选。' },
  { icon: '🎬', title: 'AI 视频', desc: '商品转动、场景演绎、口播短片，文生 / 图生视频。' },
  { icon: '⚡', title: '批量生成', desc: '上传 SKU 表格，批量产出统一风格素材，效率翻倍。' },
  { icon: '🔌', title: '开放 API', desc: '把生成能力嵌入你的 ERP / 店铺后台，按量计费。' },
]
const plans = [
  {
    name: '体验版', desc: '个人尝鲜，注册即送', amt: '50', unit: ' 额度 / 永久',
    items: ['赠送 50 生成额度', '标准分辨率出图', '每日 20 次任务上限', '社区支持'],
    btn: '选择',
  },
  {
    name: '专业版', desc: '高频电商团队', amt: '¥99', unit: ' / 月 · 800 额度',
    items: ['每月 800 生成额度', '高清 / 4K 出图', '视频生成权益', '优先队列 & 并发提升', '邮件支持'],
    btn: '选择',
  },
  {
    name: '企业版', desc: '私有化 / 大规模', amt: '定制', unit: ' / 联系商务',
    items: ['不限额度套餐', '专属模型微调', '私有化部署', 'SSO 对接', '专属客户成功'],
    btn: '联系我们',
  },
]

const scrollTo = (id) => {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
}
const toStudio = () => {
  if (!user.token) {
    ElMessage.info('请先登录 / 注册（演示账号随意填）')
    router.push('/login?redirect=' + encodeURIComponent('/studio'))
    return
  }
  // 已登录：直接进入工作台
  router.push('/studio')
}

// 已登录后：管理员进管理后台，普通用户进个人控制台
const toConsoleOrAdmin = () => {
  router.push(user.isAdmin ? '/admin' : '/console')
}
</script>

<style scoped>
.hero {
  text-align: center;
  padding: 72px 0 48px;
  position: relative;
}
.hero h1 {
  font-size: clamp(28px, 5vw, 50px);
  font-weight: 900;
  line-height: 1.1;
  margin: 0;
}
.hero p {
  margin: 18px auto 0;
  max-width: 640px;
  color: var(--sub);
}
.cta {
  margin-top: 28px;
  display: flex;
  gap: 14px;
  justify-content: center;
  flex-wrap: wrap;
}
.tags {
  margin-top: 24px;
  display: flex;
  gap: 10px;
  justify-content: center;
  flex-wrap: wrap;
}
.feat {
  grid-template-columns: repeat(4, 1fr);
}
.feat .ic {
  font-size: 26px;
  margin-bottom: 10px;
}
.feat h3 {
  margin: 0 0 6px;
  font-size: 17px;
}
.feat p {
  margin: 0;
  color: var(--sub);
  font-size: 14px;
}
.price {
  grid-template-columns: repeat(3, 1fr);
  align-items: stretch;
}
.price .el-card {
  position: relative;
}
.price .badge {
  position: absolute;
  top: -12px;
  left: 20px;
}
.price .pname {
  font-size: 18px;
  font-weight: 700;
}
.price .pdesc {
  color: var(--sub);
  font-size: 13px;
  min-height: 34px;
  margin-top: 4px;
}
.price .pamt {
  margin: 16px 0;
  font-size: 32px;
  font-weight: 900;
}
.price .pamt small {
  font-size: 14px;
  color: var(--sub);
  font-weight: 500;
}
.price ul {
  list-style: none;
  padding: 0;
  margin: 0 0 20px;
  color: var(--sub);
  font-size: 14px;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.price li::before {
  content: '✓ ';
  color: var(--ok);
  font-weight: 700;
}
@media (max-width: 980px) {
  .feat {
    grid-template-columns: repeat(2, 1fr);
  }
  .price {
    grid-template-columns: 1fr;
    max-width: 420px;
    margin-left: auto;
    margin-right: auto;
  }
}
@media (max-width: 680px) {
  .feat {
    grid-template-columns: 1fr;
  }
}
</style>
