<script setup>
// 移植自 Alpha index.html 的 activeView === 'dashboard' 與 app.js 的 loadDashboard()。
// 與 Alpha 不同的地方（見 VM-RULES.md）：後端用台北時間、趨勢用 Production 的規則；畫面是 fetch() → apiFetch()，
// 以及下面的 <style>：占比長條的填色 <i class="mix-fill"> 是行內元素，Alpha 的 height:100% 對它無效、長條沒有填色，補上 display:block。
// 2026-11-25 互動層：數字滾動、Total Gross Premium 移到頂端、載入時間與 Refresh、Accounting 獨立小卡、Retention 評價、
// 占比長條滑過與排序、互動柱狀圖（DashboardTrend）。資料與 API 完全不變。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiFetch } from '../api'
import { can } from '../auth'
import { formatAmount } from '../alpha/format'
import { shell } from '../alpha/shell'
import vCountup from '../directives/countUp'
import DashboardTrend from '../components/DashboardTrend.vue'
import '../alpha/styles/dashboard-interaction.css'

const twoDecimals = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const formatTwoDecimals = value => twoDecimals.format(Number(value) || 0)

const router = useRouter()
const dashboardLoading = ref(false)
const selectedTrendYear = ref(null)
const trendYears = computed(() => dashboard.value.period?.year ? Array.from({ length: 5 }, (_, i) => dashboard.value.period.year - i) : [])

const dashboard = ref({ period: { year: null, currentMonth: '', monthNumber: 1 }, metrics: {}, brokerage: { labels: [], current: [], prior: [], target: [], annualTarget: null }, classMix: [], reinsurers: [] })

// 載入時間（顯示的是這個畫面最近一次向伺服器取得資料的時間；伺服器端另有結果快取）
const loadedAt = ref(null)
const nowTick = ref(Date.now())
const growKey = ref(0)
let clock = null
const loadedText = computed(() => {
  if (!loadedAt.value) return '—'
  const seconds = Math.max(0, Math.round((nowTick.value - loadedAt.value) / 1000))
  return seconds < 10 ? 'just now' : seconds < 60 ? `${seconds} s ago` : `${Math.floor(seconds / 60)} min ago`
})

async function loadDashboard() {
  const previousYear = dashboard.value.brokerage?.selectedYear || dashboard.value.period?.year
  if (!can('dashboard.read')) return
  dashboardLoading.value = true
  shell.error = ''
  try {
    const response = await apiFetch('/api/dashboard' + (selectedTrendYear.value ? '?brokerageYear=' + selectedTrendYear.value : ''), { headers: { Accept: 'application/json' } })
    const body = await response.json()
    if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
    dashboard.value = body
    selectedTrendYear.value = selectedTrendYear.value || body.period.year
    dashboard.value.brokerage.selectedYear = selectedTrendYear.value
    loadedAt.value = Date.now()
  } catch (err) {
    selectedTrendYear.value = previousYear || null
    shell.error = err instanceof Error ? err.message : String(err)
  } finally {
    dashboardLoading.value = false
  }
}
async function refresh() {
  await loadDashboard()
  growKey.value++ // 柱子重新長出
}

// Renewal Retention Ratio 評價：以各級下限判定（整數邊界之間的小數，例如 90.5，歸入較低一級）
const RATE_BANDS = [
  { min: 91, name: 'Excellent', range: '100 – 91', tone: 'ok' },
  { min: 81, name: 'Very Good', range: '90 – 81', tone: 'ok' },
  { min: 71, name: 'Good', range: '80 – 71', tone: 'info' },
  { min: 61, name: 'Satisfactory', range: '70 – 61', tone: 'info' },
  { min: 41, name: 'Average', range: '60 – 41', tone: 'warn' },
  { min: 21, name: 'Below Average', range: '40 – 21', tone: 'bad' },
  { min: 0, name: 'Unsatisfactory', range: '20 – 0', tone: 'bad' }
]
const rating = computed(() => {
  const value = dashboard.value.metrics?.retentionRatio
  if (value == null || !Number.isFinite(Number(value))) return null
  return RATE_BANDS.find(band => Number(value) >= band.min) || RATE_BANDS[RATE_BANDS.length - 1]
})

// 占比長條：排序（Share／A–Z）
const mixSort = ref('share')
const reinsurerSort = ref('share')
const sortRows = (rows, mode) => (mode === 'name' ? [...(rows || [])].sort((a, b) => String(a.name).localeCompare(String(b.name))) : (rows || []))
const classRows = computed(() => sortRows(dashboard.value.classMix, mixSort.value))
const reinsurerRows = computed(() => sortRows(dashboard.value.reinsurers, reinsurerSort.value))
const rowTip = row => `TWD ${formatAmount(row.amount)} · ${Number(row.pct || 0).toFixed(1)}%`

// Accounting 小卡：原幣別理賠明細可收合
const claimsOpen = ref(false)

onMounted(() => {
  loadDashboard()
  clock = setInterval(() => { nowTick.value = Date.now() }, 10000)
})
onBeforeUnmount(() => clearInterval(clock))
</script>

<template>
<div class="rdash" v-loading="dashboardLoading">
  <el-alert v-if="dashboard.metrics?.dataErrors?.length" type="error" :closable="false" show-icon title="Some cases have invalid financial data" description="Their amounts are pending confirmation and excluded from financial totals. Correct the saved case data before using complete totals." />
  <div class="dash-bar">
    <div class="gp" data-testid="dashboard-gross-premium"><span class="gp-l">Total Gross Premium</span><span class="gp-v">TWD <span v-countup="{ to: dashboard.metrics?.grossPremiumNtd || 0, fmt: formatTwoDecimals }"></span></span></div>
    <span class="upd">Loaded <b>{{ loadedText }}</b></span>
    <el-button class="secondary-button" size="small" data-testid="dashboard-refresh" :disabled="dashboardLoading" @click="refresh">Refresh</el-button>
  </div>
  <div class="row3">
    <section class="card">
      <div class="card-head"><h3>Total Bound YTD</h3><span class="chip muted">{{ dashboard.period?.year }}</span></div>
      <div class="stat2"><span class="stat-value" v-countup="{ to: dashboard.metrics?.ytdCurrent || 0 }"></span><div class="side-stat"><div class="label">Prior-Year YTD</div><div class="val">{{ dashboard.metrics?.ytdPrior || 0 }}</div></div></div>
    </section>
    <section class="card">
      <div class="card-head"><h3>Renewals Bound MTD</h3><span class="chip muted">vs. Expected</span></div>
      <div class="stat2"><span class="stat-value" v-countup="{ to: dashboard.metrics?.renewalsMtd || 0 }"></span><div class="side-stat"><div class="label">Expected Renewals</div><div class="val">{{ dashboard.metrics?.expectedRenewalsMtd || 0 }}</div></div></div>
    </section>
    <section class="card new-business-card">
      <div class="card-head"><h3>New Business MTD</h3><span class="chip muted">{{ dashboard.period?.currentMonth }}</span></div>
      <div class="stat2"><span class="stat-value" v-countup="{ to: dashboard.metrics?.newBusinessMtd || 0 }"></span><el-button v-if="can('cases.write')" size="small" class="primary-button" data-testid="dashboard-new-case" @click="router.push({ path: '/cases', query: { action: 'new' } })">+ New Case</el-button></div>
    </section>
  </div>

  <section class="card trend-card">
    <div class="card-head"><h3>YTD Brokerage Trend (TWD)</h3><el-select v-model="selectedTrendYear" aria-label="Brokerage trend year" data-testid="dashboard-trend-year" size="small" style="width: 110px" :disabled="dashboardLoading" @change="loadDashboard"><el-option v-for="year in trendYears" :key="year" :label="String(year)" :value="year" /></el-select></div>
    <DashboardTrend v-if="dashboard.brokerage?.labels?.length" :labels="dashboard.brokerage.labels" :current="dashboard.brokerage.current" :prior="dashboard.brokerage.prior" :target="dashboard.brokerage.target" :current-status="dashboard.brokerage.currentStatus || []" :prior-status="dashboard.brokerage.priorStatus || []" :year="selectedTrendYear" :grow-key="growKey" />
    <div v-else class="empty-note">No performance months yet.</div>
    <p class="empty-note">Closed months use official Production amounts; other months are estimates. {{ (dashboard.brokerage?.labels||[]).map((month,index)=>month+': '+(dashboard.brokerage?.currentStatus?.[index]||'estimated')).join(' · ') }}</p>
  </section>

  <div class="row2">
    <section class="card">
      <h3 style="margin-bottom:14px">Key Performance Indicators</h3>
      <div class="kpi-grid">
        <div class="kpi"><div class="label">In-Force Policies</div><div class="val"><span v-countup="{ to: dashboard.metrics?.inForcePolicies || 0 }"></span></div></div>
        <div class="kpi"><div class="label">Active Endorsements</div><div class="val"><span v-countup="{ to: dashboard.metrics?.activeEndorsements || 0 }"></span></div></div>
        <div class="kpi"><div class="label">Open Quotes</div><div class="val"><span v-countup="{ to: dashboard.metrics?.openQuotes || 0 }"></span></div></div>
        <div class="kpi"><div class="label">Renewal Retention Ratio</div><div class="val retval"><span><span v-countup="{ to: dashboard.metrics?.retentionRatio, fmt: formatAmount, empty: 'N/A' }"></span><small v-if="dashboard.metrics?.retentionRatio != null">%</small></span>
          <span v-if="rating" class="rate" :class="'rate-' + rating.tone" tabindex="0" aria-describedby="retention-scale">{{ rating.name }}<span id="retention-scale" class="rate-pop" role="tooltip"><b>Renewal Retention Ratio</b><span v-for="band in RATE_BANDS" :key="band.name" class="rp-row" :class="{ on: band === rating }"><i class="rp-dot" :class="'rate-' + band.tone"></i><span>{{ band.name }}</span><em>{{ band.range }}%</em></span></span></span></div></div>
      </div>
    </section>
    <section class="card accounting-card" data-testid="dashboard-accounting">
      <h3 style="margin-bottom:14px">Accounting · Receivable / Payable</h3>
      <div class="val acc-val">TWD <span v-countup="{ to: dashboard.metrics?.outstandingLeg1Ntd || 0, fmt: formatAmount }"></span> / <span v-countup="{ to: dashboard.metrics?.outstandingLeg2Ntd || 0, fmt: formatAmount }"></span></div>
      <div class="acc-notes"><small v-if="dashboard.metrics?.missingPostingRates?.length">Awaiting FX — Past 5 years record only.</small><small v-else-if="dashboard.metrics?.accountingTotalEstimated">Estimated using latest FX until Production recognition</small><small v-if="dashboard.metrics?.outstandingSince && !dashboard.metrics?.missingPostingRates?.length" data-testid="outstanding-since">Past 5 years record only.</small></div>
      <div v-if="dashboard.metrics?.claimOutstandingByCurrency?.length">
        <button type="button" class="el-button secondary-button acc-toggle" :class="{ open: claimsOpen }" :aria-expanded="claimsOpen" style="margin-top:8px" @click="claimsOpen = !claimsOpen"><span class="chev">▸</span>Claims by original currency</button>
        <div class="acc-claims" :class="{ open: claimsOpen }"><div><small style="display:block;margin-top:8px">Claim receivable / payable by original currency</small><div v-for="row in dashboard.metrics.claimOutstandingByCurrency" :key="row.currency">{{ row.currency }} {{ formatAmount(row.receivable) }} / {{ formatAmount(row.payable) }}</div></div></div>
      </div>
    </section>
  </div>

  <div class="row2">
    <section class="card">
      <div class="card-head"><h3 style="margin-bottom:14px">Mix by Class of Business</h3><div v-if="dashboard.classMix?.length > 1" class="seg" role="group" aria-label="Sort classes"><button type="button" :class="{ on: mixSort === 'share' }" @click="mixSort = 'share'">Share</button><button type="button" :class="{ on: mixSort === 'name' }" @click="mixSort = 'name'">A–Z</button></div></div>
      <transition-group v-if="dashboard.classMix?.length" tag="div" name="mix-flip" class="mix-list"><div v-for="row in classRows" :key="'class-' + row.name" class="mix-row" :data-tip="rowTip(row)"><span>{{ row.name }}</span><span class="mix-track"><i class="mix-fill" :style="{width: Math.max(2,Number(row.pct || 0)) + '%'}"></i></span><strong>{{ Number(row.pct || 0).toFixed(1) }}%</strong></div></transition-group>
      <div v-else class="empty-note">No in-force premium yet.</div>
    </section>
    <section class="card">
      <div class="card-head"><h3 style="margin-bottom:14px">Top Reinsurers/RI Broker by Ceded Premium</h3><div v-if="dashboard.reinsurers?.length > 1" class="seg" role="group" aria-label="Sort reinsurers"><button type="button" :class="{ on: reinsurerSort === 'share' }" @click="reinsurerSort = 'share'">Share</button><button type="button" :class="{ on: reinsurerSort === 'name' }" @click="reinsurerSort = 'name'">A–Z</button></div></div>
      <transition-group v-if="dashboard.reinsurers?.length" tag="div" name="mix-flip" class="mix-list"><div v-for="row in reinsurerRows" :key="'reinsurer-' + row.name" class="mix-row" :data-tip="rowTip(row)"><span>{{ row.name }}</span><span class="mix-track"><i class="mix-fill" :style="{width: Math.max(2,Number(row.pct || 0)) + '%'}"></i></span><strong>{{ Number(row.pct || 0).toFixed(1) }}%</strong></div></transition-group>
      <div v-else class="empty-note">No in-force premium yet.</div>
    </section>
  </div>
</div>
</template>

<style>
/* 占比長條需要 display:block 才有填色（Alpha v57 起在模板上加了同樣的修正；Alpha 的 CSS 檔保持原樣） */
.rdash .mix-fill { display: block; }
.rdash .new-business-card { display: flex; flex-direction: column; }
.rdash .new-business-card .stat2 { margin-top: auto; }
.rdash .trend-bar.prior { fill: #5F5F5F; }
.rdash .trend-bar.current { fill: #AF2D41; }
.rdash .trend-zero { stroke: #999; stroke-width: 1; }
</style>
