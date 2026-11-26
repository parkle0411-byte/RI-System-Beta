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
import DashboardSparkline from '../components/DashboardSparkline.vue'
import '../alpha/styles/dashboard-interaction.css'

const twoDecimals = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const formatTwoDecimals = value => twoDecimals.format(Number(value) || 0)
// 台幣金額不顯示小數（2026-11-26 業主決定）
const wholeNumber = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const formatTwd = value => wholeNumber.format(Math.round(Number(value) || 0))

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

// 占比長條：占比卡固定依占比排序；再保人榜可切 Share／Cases（2026-11-26 業主決定：不要 A–Z）
const reinsurerSort = ref('share') // share｜cases
const reinsurerRows = computed(() => {
  if (reinsurerSort.value === 'cases' && insights.value.reinsurersByCases?.rows?.length) {
    const { rows, policies } = insights.value.reinsurersByCases
    return rows.map(row => ({ name: row.name, pct: policies ? row.cases / policies * 100 : 0, label: `${row.cases}`, tip: `${row.cases} of ${policies} in-force policies` }))
  }
  return (dashboard.value.reinsurers || []).map(row => ({ name: row.name, pct: row.pct, label: `${Number(row.pct || 0).toFixed(1)}%`, tip: rowTip(row) }))
})
const rowTip = row => `TWD ${formatAmount(row.amount)} · ${Number(row.pct || 0).toFixed(1)}%`

// 補充資料（後端 insights；沒有時各項互動自動隱藏）
const insights = computed(() => dashboard.value.insights || {})
// Accounting 小卡（2026-11-26 業主決定）：未結清應收／應付與逾期，依台幣與非台幣（各幣別原金額）分開；台幣不顯示小數、台幣一定有一列
const fractionDigits = currency => {
  if (currency === 'TWD') return 0
  try { return new Intl.NumberFormat('en-US', { style: 'currency', currency }).resolvedOptions().maximumFractionDigits } catch (error) { return 2 }
}
function formatCurrency(value, currency) {
  const digits = fractionDigits(currency)
  const number = Number(value) || 0
  return new Intl.NumberFormat('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(digits === 0 ? Math.round(number) : number)
}
const outstandingRows = computed(() => {
  const rows = (insights.value.outstandingByCurrency || []).map(row => ({ currency: row.currency, receivable: row.receivable || 0, payable: row.payable || 0, overdueReceivable: row.overdueReceivable || 0, overduePayable: row.overduePayable || 0 }))
  if (!rows.some(row => row.currency === 'TWD')) rows.unshift({ currency: 'TWD', receivable: 0, payable: 0, overdueReceivable: 0, overduePayable: 0 })
  return rows
})
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const trendMonthLabel = key => `${MONTH_NAMES[Number(String(key).slice(5, 7)) - 1] || key} ${String(key).slice(0, 4)}`
const trends = computed(() => insights.value.trends)
// Total Gross Premium 的美金對照：用本月或以前最新的 USD 匯率反推（後端提供；沒有匯率時不顯示）
const grossUsd = computed(() => insights.value.grossPremiumUsd || null)
// Total Bound YTD：今年 1 月到本月逐月累計（只有一個月時不畫）；Renewals／New Business：近 12 個月逐月件數
const sparkTotal = computed(() => {
  const t = trends.value
  if (!t) return null
  const year = String(dashboard.value.period?.year || '')
  const keep = t.months.map((m, i) => (m.startsWith(year) ? i : -1)).filter(i => i >= 0)
  let total = 0
  return { labels: keep.map(i => trendMonthLabel(t.months[i])), values: keep.map(i => (total += t.bound[i])) }
})
const sparkRenew = computed(() => (trends.value ? { labels: trends.value.months.map(trendMonthLabel), values: trends.value.renew } : null))
const sparkNew = computed(() => (trends.value ? { labels: trends.value.months.map(trendMonthLabel), values: trends.value.new } : null))
const ytdYoY = computed(() => {
  const prior = Number(dashboard.value.metrics?.ytdPrior), current = Number(dashboard.value.metrics?.ytdCurrent)
  return prior > 0 && Number.isFinite(current) ? (current / prior - 1) * 100 : null
})
// 占比長條點一下，趨勢圖只看該險種（名稱要在後端提供的險種清單內）
const trendClass = ref(null)
const trendClassNames = computed(() => insights.value.brokerage?.byClass?.names || [])
function pickClass(row) {
  if (!trendClassNames.value.includes(row.name)) return
  trendClass.value = trendClass.value === row.name ? null : row.name
}


onMounted(() => {
  loadDashboard()
  clock = setInterval(() => { nowTick.value = Date.now() }, 10000)
})
onBeforeUnmount(() => clearInterval(clock))
</script>

<template>
<div class="rdash" v-skeleton="{ on: dashboardLoading, kind: 'blocks' }">
  <el-alert v-if="dashboard.metrics?.dataErrors?.length" type="error" :closable="false" show-icon title="Some cases have invalid financial data" description="Their amounts are pending confirmation and excluded from financial totals. Correct the saved case data before using complete totals." />
  <div class="dash-bar">
    <div class="gp" data-testid="dashboard-gross-premium"><span class="gp-l">Total Gross Premium</span><span class="gp-v" data-sk title="Each policy is converted at the rate of the month it is recognized">TWD <span v-countup="{ to: dashboard.metrics?.grossPremiumNtd || 0, fmt: formatTwd }"></span></span><span v-if="grossUsd" class="gp-v gp-usd" data-testid="dashboard-gross-premium-usd" title="Each policy is converted to TWD at the rate of the month it is recognized, then to USD at that month's USD rate">USD <span v-countup="{ to: grossUsd.amount, fmt: formatTwoDecimals }"></span></span><span v-else-if="dashboardLoading" class="gp-v gp-usd" data-sk>USD 0,000,000.00</span></div>
    <span class="upd">Loaded <b data-sk>{{ loadedText }}</b></span>
    <el-button class="secondary-button" size="small" data-testid="dashboard-refresh" :disabled="dashboardLoading" @click="refresh">Refresh</el-button>
  </div>
  <div class="row3">
    <section class="card">
      <div class="card-head"><h3>Total Bound YTD</h3><span class="chip muted">{{ dashboard.period?.year }}</span></div>
      <div class="stat2"><span class="stat-value" data-sk v-countup="{ to: dashboard.metrics?.ytdCurrent || 0 }"></span><div class="side-stat"><div class="label">Prior-Year YTD</div><div class="val" data-sk>{{ dashboard.metrics?.ytdPrior || 0 }}</div><div v-if="ytdYoY != null" class="yoy" :class="ytdYoY >= 0 ? 'up' : 'dn'" data-testid="dashboard-yoy">{{ ytdYoY >= 0 ? '▲' : '▼' }} {{ Math.abs(ytdYoY).toFixed(1) }}% vs {{ (dashboard.period?.year || 0) - 1 }}</div></div></div>
      <DashboardSparkline data-sk v-if="sparkTotal && sparkTotal.values.length > 1" :values="sparkTotal.values" :labels="sparkTotal.labels" name="Total Bound YTD by month (cumulative)" unit=" bound" />
      <div v-else-if="dashboardLoading" class="sk-space sk-space-spark" data-sk></div>
    </section>
    <section class="card">
      <div class="card-head"><h3>Renewals Bound MTD</h3><span class="chip muted">vs. Expected</span></div>
      <div class="stat2"><span class="stat-value" data-sk v-countup="{ to: dashboard.metrics?.renewalsMtd || 0 }"></span><div class="side-stat"><div class="label">Expected Renewals</div><div class="val" data-sk>{{ dashboard.metrics?.expectedRenewalsMtd || 0 }}</div></div></div>
      <DashboardSparkline data-sk v-if="sparkRenew" :values="sparkRenew.values" :labels="sparkRenew.labels" color="#5F5F5F" name="Renewals bound per month" unit=" renewed" />
      <div v-else-if="dashboardLoading" class="sk-space sk-space-spark" data-sk></div>
    </section>
    <section class="card new-business-card">
      <div class="card-head"><h3>New Business MTD</h3><span class="chip muted">{{ dashboard.period?.currentMonth }}</span></div>
      <div class="stat2"><span class="stat-value" data-sk v-countup="{ to: dashboard.metrics?.newBusinessMtd || 0 }"></span><el-button v-if="can('cases.write')" size="small" class="primary-button" data-testid="dashboard-new-case" @click="router.push({ path: '/cases', query: { action: 'new' } })">+ New Case</el-button></div>
      <DashboardSparkline data-sk v-if="sparkNew" :values="sparkNew.values" :labels="sparkNew.labels" name="New business bound per month" unit=" new" />
      <div v-else-if="dashboardLoading" class="sk-space sk-space-spark" data-sk></div>
    </section>
  </div>

  <section class="card trend-card">
    <div class="card-head"><h3>YTD Brokerage Trend (TWD)</h3><el-select v-model="selectedTrendYear" aria-label="Brokerage trend year" data-testid="dashboard-trend-year" size="small" style="width: 110px" :disabled="dashboardLoading" @change="loadDashboard"><el-option v-for="year in trendYears" :key="year" :label="String(year)" :value="year" /></el-select></div>
    <DashboardTrend v-if="dashboard.brokerage?.labels?.length" data-sk :labels="dashboard.brokerage.labels" :current="dashboard.brokerage.current" :prior="dashboard.brokerage.prior" :target="dashboard.brokerage.target" :current-status="dashboard.brokerage.currentStatus || []" :prior-status="dashboard.brokerage.priorStatus || []" :year="selectedTrendYear" :grow-key="growKey" :prior2="insights.brokerage?.prior2 || []" :prior2-status="insights.brokerage?.prior2Status || []" :by-class="insights.brokerage?.byClass || null" v-model:class-filter="trendClass" />
    <div v-else-if="dashboardLoading" class="sk-space sk-space-trend" data-sk></div>
    <div v-else class="empty-note">No performance months yet.</div>
  </section>

  <div class="row2">
    <section class="card">
      <h3 style="margin-bottom:14px">Key Performance Indicators</h3>
      <div class="kpi-grid">
        <div class="kpi"><div class="label">In-Force Policies</div><div data-sk class="val"><span v-countup="{ to: dashboard.metrics?.inForcePolicies || 0 }"></span></div></div>
        <div class="kpi"><div class="label">Active Endorsements</div><div data-sk class="val"><span v-countup="{ to: dashboard.metrics?.activeEndorsements || 0 }"></span></div></div>
        <div class="kpi"><div class="label">Open Quotes</div><div data-sk class="val"><span v-countup="{ to: dashboard.metrics?.openQuotes || 0 }"></span></div></div>
        <div class="kpi"><div class="label">Renewal Retention Ratio</div><div data-sk class="val retval"><span><span v-countup="{ to: dashboard.metrics?.retentionRatio, fmt: formatAmount, empty: 'N/A' }"></span><small v-if="dashboard.metrics?.retentionRatio != null">%</small></span>
          <span v-if="rating" class="rate" :class="'rate-' + rating.tone" tabindex="0" aria-describedby="retention-scale">{{ rating.name }}<span id="retention-scale" class="rate-pop" role="tooltip"><b>Renewal Retention Ratio</b><span v-for="band in RATE_BANDS" :key="band.name" class="rp-row" :class="{ on: band === rating }"><i class="rp-dot" :class="'rate-' + band.tone"></i><span>{{ band.name }}</span><em>{{ band.range }}%</em></span></span></span></div></div>
      </div>
    </section>
    <section class="card accounting-card" data-testid="dashboard-accounting">
      <h3 style="margin-bottom:14px">Accounting · Receivable / Payable</h3>
      <table class="acc-table" data-testid="dashboard-outstanding">
        <thead><tr><th></th><th>Receivable</th><th>Payable</th><th title="Overdue receivable: unsettled, actual due date before today">Overdue R.</th><th title="Overdue payable: unsettled, actual due date before today">Overdue P.</th></tr></thead>
        <tbody>
          <tr v-for="row in outstandingRows" :key="row.currency" :data-currency="row.currency">
            <td data-sk>{{ row.currency }}</td>
            <td data-sk><span v-countup="{ to: row.receivable, fmt: v => formatCurrency(v, row.currency) }"></span></td>
            <td data-sk><span v-countup="{ to: row.payable, fmt: v => formatCurrency(v, row.currency) }"></span></td>
            <td data-sk class="od" :class="{ clear: !row.overdueReceivable }"><span v-countup="{ to: row.overdueReceivable, fmt: v => formatCurrency(v, row.currency) }"></span></td>
            <td data-sk class="od" :class="{ clear: !row.overduePayable }"><span v-countup="{ to: row.overduePayable, fmt: v => formatCurrency(v, row.currency) }"></span></td>
          </tr>
        </tbody>
      </table>
      <div class="acc-notes"><small v-if="dashboard.metrics?.outstandingSince" data-testid="outstanding-since">Past 5 years record only.</small></div>
    </section>
  </div>

  <div class="row2">
    <section class="card">
      <div class="card-head"><h3 style="margin-bottom:14px">Mix by Class of Business</h3></div>
      <transition-group v-if="dashboard.classMix?.length" tag="div" name="mix-flip" class="mix-list"><div v-for="row in dashboard.classMix" :key="'class-' + row.name" data-sk class="mix-row" :class="{ pickable: trendClassNames.includes(row.name), picked: trendClass === row.name }" :data-tip="rowTip(row)" :tabindex="trendClassNames.includes(row.name) ? 0 : undefined" :role="trendClassNames.includes(row.name) ? 'button' : undefined" :aria-pressed="trendClassNames.includes(row.name) ? trendClass === row.name : undefined" @click="pickClass(row)" @keydown.enter.prevent="pickClass(row)" @keydown.space.prevent="pickClass(row)"><span>{{ row.name }}</span><span class="mix-track"><i class="mix-fill" :style="{width: Math.max(2,Number(row.pct || 0)) + '%'}"></i></span><strong>{{ Number(row.pct || 0).toFixed(1) }}%</strong></div></transition-group>
      <div v-else-if="dashboardLoading" class="mix-list"><div v-for="n in 5" :key="n" class="sk-space sk-space-row" data-sk></div></div>
      <div v-else class="empty-note">No in-force premium yet.</div>
    </section>
    <section class="card">
      <div class="card-head"><h3 style="margin-bottom:14px">Top Reinsurers/RI Broker by Ceded Premium</h3><div v-if="insights.reinsurersByCases?.rows?.length && dashboard.reinsurers?.length > 1" class="seg" role="group" aria-label="Sort reinsurers"><button type="button" :class="{ on: reinsurerSort === 'share' }" @click="reinsurerSort = 'share'">Share</button><button type="button" :class="{ on: reinsurerSort === 'cases' }" @click="reinsurerSort = 'cases'">Cases</button></div></div>
      <transition-group v-if="dashboard.reinsurers?.length" tag="div" name="mix-flip" class="mix-list"><div v-for="row in reinsurerRows" :key="'reinsurer-' + row.name" data-sk class="mix-row" :data-tip="row.tip"><span>{{ row.name }}</span><span class="mix-track"><i class="mix-fill" :style="{width: Math.max(2,Number(row.pct || 0)) + '%'}"></i></span><strong>{{ row.label }}</strong></div></transition-group>
      <div v-else-if="dashboardLoading" class="mix-list"><div v-for="n in 5" :key="n" class="sk-space sk-space-row" data-sk></div></div>
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
