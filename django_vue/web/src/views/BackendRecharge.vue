<template>
  <div class="bk-page">
    <div class="head">
      <div><h2>个人充值</h2><p>选择套餐为账户充值额度，支持多种支付方式</p></div>
      <el-tag type="info" effect="dark" round>当前余额 {{ user.quota.balance }} 额度</el-tag>
    </div>

    <el-card shadow="never" class="panel">
      <div class="panel-h"><h3>选择充值套餐</h3><span class="sub">演示价格</span></div>
      <div class="pkgs">
        <div
          v-for="p in packages"
          :key="p.id"
          class="pkg"
          :class="{ active: sel === p.id }"
          @click="sel = p.id"
        >
          <div class="p-amt">{{ p.amount }}<span>额度</span></div>
          <div class="p-price">¥{{ p.price }}</div>
          <div v-if="p.bonus" class="p-bonus">赠 {{ p.bonus }}</div>
          <div v-if="p.hot" class="p-tag">超值</div>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="panel">
      <div class="panel-h"><h3>支付方式</h3></div>
      <el-radio-group v-model="method" class="pay">
        <el-radio-button value="wechat">微信支付</el-radio-button>
        <el-radio-button value="alipay">支付宝</el-radio-button>
        <el-radio-button value="mock">模拟支付</el-radio-button>
      </el-radio-group>
      <div class="summary">
        <div><span>充值额度</span><b>{{ current.amount }} 额度</b></div>
        <div v-if="current.bonus"><span>赠送</span><b class="ok">+{{ current.bonus }}</b></div>
        <div><span>支付金额</span><b class="brand">¥{{ current.price }}</b></div>
      </div>
      <el-button type="primary" size="large" :loading="paying" @click="pay">确认支付</el-button>
    </el-card>

    <el-card shadow="never" class="panel">
      <div class="panel-h"><h3>充值记录</h3><span class="sub">演示数据</span></div>
      <el-table :data="records" class="tbl">
        <el-table-column prop="no" label="订单号" width="190" />
        <el-table-column prop="pkg" label="套餐" />
        <el-table-column label="金额" width="100">
          <template #default="{ row }">¥{{ row.amount }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.paid ? 'success' : 'warning'">
              {{ row.paid ? '已支付' : '处理中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="time" label="时间" width="170" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/store/user'

const user = useUserStore()

const packages = [
  { id: 1, amount: 100, price: 30, bonus: 0, hot: false },
  { id: 2, amount: 500, price: 138, bonus: 60, hot: true },
  { id: 3, amount: 2000, price: 498, bonus: 400, hot: false },
  { id: 4, amount: 5000, price: 1180, bonus: 1200, hot: false },
]
const sel = ref(2)
const method = ref('mock')
const paying = ref(false)
const current = computed(() => packages.find((p) => p.id === sel.value) || packages[0])

const records = [
  { no: 'R20260804140217', pkg: '500 额度 +60', amount: 138, paid: true, time: '2026-08-04 14:02' },
  { no: 'R20260728103309', pkg: '100 额度', amount: 30, paid: true, time: '2026-07-28 10:33' },
  { no: 'R20260720091544', pkg: '2000 额度 +400', amount: 498, paid: true, time: '2026-07-20 09:15' },
]

const pay = () => {
  paying.value = true
  setTimeout(() => {
    paying.value = false
    const got = current.value.amount + (current.value.bonus || 0)
    ElMessage.success(`（演示）支付成功，已模拟到账 ${got} 额度`)
  }, 600)
}
</script>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; }
.head h2 { margin: 0; font-size: 24px; }
.head p { margin: 4px 0 0; color: var(--sub); font-size: 14px; }
.panel { background: var(--card); border: 1px solid var(--line); color: var(--txt); padding: 18px; border-radius: var(--radius); margin-bottom: 16px; }
.panel:last-child { margin-bottom: 0; }
.panel-h { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.panel-h h3 { margin: 0; font-size: 16px; }
.sub { color: var(--sub); font-size: 12px; }
.pkgs { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.pkg {
  position: relative; cursor: pointer; padding: 18px 14px; text-align: center;
  background: var(--bg2); border: 1px solid var(--line); border-radius: 12px; transition: .15s;
}
.pkg:hover { border-color: var(--brand); }
.pkg.active {
  border-color: var(--brand);
  box-shadow: 0 0 0 2px rgba(124, 92, 255, .35) inset;
  background: linear-gradient(180deg, rgba(124, 92, 255, .12), rgba(55, 198, 255, .06));
}
.p-amt { font-size: 26px; font-weight: 900; }
.p-amt span { font-size: 12px; font-weight: 600; color: var(--sub); margin-left: 4px; }
.p-price { margin-top: 6px; color: var(--brand2); font-weight: 700; }
.p-bonus { margin-top: 4px; font-size: 12px; color: var(--ok); }
.p-tag {
  position: absolute; top: 8px; right: 8px; font-size: 11px; background: var(--warn);
  color: #1a1205; padding: 1px 7px; border-radius: 999px; font-weight: 700;
}
.pay { margin-bottom: 16px; }
.summary { display: flex; flex-wrap: wrap; gap: 24px; margin-bottom: 16px; }
.summary div { font-size: 14px; color: var(--sub); }
.summary b { color: var(--txt); margin-left: 6px; font-size: 16px; }
.summary b.ok { color: var(--ok); }
.summary b.brand { color: var(--brand2); }
.tbl :deep(.el-table),
.tbl :deep(.el-table__expanded-cell),
.tbl :deep(.el-table th),
.tbl :deep(.el-table tr),
.tbl :deep(.el-table td) { background: var(--card) !important; color: var(--txt) !important; border-color: var(--line) !important; }
.tbl :deep(.el-table__inner-wrapper::before) { display: none; }
.tbl :deep(.el-table__row:hover > td) { background: var(--card2) !important; }
.tbl :deep(.el-table thead th) { background: var(--bg2) !important; color: var(--sub) !important; font-weight: 600; }
@media (max-width: 768px) { .pkgs { grid-template-columns: repeat(2, 1fr); } }
</style>
