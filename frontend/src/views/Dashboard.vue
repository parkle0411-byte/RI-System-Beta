<script setup>
// 移植自 Alpha index.html 的 activeView === 'dashboard'（模板第 71–148 行原樣）與 app.js 的 loadDashboard()、
// dashboardTrendValues()／dashboardTrendMax()／dashboardTrendX()／dashboardTrendY()／dashboardTrendPoints()／dashboardTrendSeries()、formatThousands()。
// 與 Alpha 不同的地方（見 VM-RULES.md）：後端用台北時間、趨勢用 Production 的規則；畫面是 fetch() → apiFetch()，
// 以及下面的 <style>：占比長條的填色 <i class="mix-fill"> 是行內元素，Alpha 的 height:100% 對它無效、長條沒有填色，補上 display:block。
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiFetch } from '../api'
import { can } from '../auth'
import { formatAmount } from '../alpha/format'
import { shell } from '../alpha/shell'

const twoDecimals = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const formatTwoDecimals = value => twoDecimals.format(Number(value) || 0)

const router = useRouter()
const dashboardLoading = ref(false)
const selectedTrendYear = ref(null)
const trendYears = computed(() => dashboard.value.period?.year ? Array.from({ length: 5 }, (_, i) => dashboard.value.period.year - i) : [])

const dashboard = ref({ period: { year: null, currentMonth: '', monthNumber: 1 }, metrics: {}, brokerage: { labels: [], current: [], prior: [], target: [], annualTarget: null }, classMix: [], reinsurers: [] })

function formatThousands(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return `${new Intl.NumberFormat('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(number / 1000)}K`
}

function dashboardTrendValues() {
  return [
    ...(dashboard.value?.brokerage?.current || []),
    ...(dashboard.value?.brokerage?.prior || []),
    ...(dashboard.value?.brokerage?.target || [])
  ].map(Number).filter(Number.isFinite)
}
function dashboardTrendMax() {
  return Math.max(1, ...dashboardTrendValues())
}
function dashboardTrendX(index, total) {
  if (total <= 1) return 450
  return 110 + (index * 742 / (total - 1))
}
function dashboardTrendMin() {
  return Math.min(0, ...dashboardTrendValues())
}
function dashboardTrendTick(fraction) {
  return dashboardTrendMin() + (dashboardTrendMax() - dashboardTrendMin()) * fraction
}
function dashboardTrendY(value) {
  return 184 - ((Number(value || 0) - dashboardTrendMin()) / (dashboardTrendMax() - dashboardTrendMin()) * 150)
}
function dashboardBarWidth() {
  const count = dashboard.value.brokerage?.labels?.length || 1
  return Math.min(18, (count > 1 ? 742 / (count - 1) : 60) * 0.32)
}
function dashboardTrendPoints(series) {
  const values = Array.isArray(series) ? series : []
  return values.map((value, index) => dashboardTrendX(index, values.length) + ',' + dashboardTrendY(value)).join(' ')
}
function dashboardTrendSeries(series) {
  const values = Array.isArray(series) ? series : []
  return values.map((value, index) => ({
    x: dashboardTrendX(index, values.length),
    y: dashboardTrendY(value),
    value: Number(value || 0)
  }))
}

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
  } catch (err) {
    selectedTrendYear.value = previousYear || null
    shell.error = err instanceof Error ? err.message : String(err)
  } finally {
    dashboardLoading.value = false
  }
}

onMounted(() => loadDashboard())
</script>

<template>
<div class="rdash" v-loading="dashboardLoading">
  <el-alert v-if="dashboard.metrics?.dataErrors?.length" type="error" :closable="false" show-icon title="Some cases have invalid financial data" description="Their amounts are pending confirmation and excluded from financial totals. Correct the saved case data before using complete totals." />
  <div class="row3">
    <section class="card">
      <div class="card-head"><h3>Total Bound YTD</h3><span class="chip muted">{{ dashboard.period?.year }}</span></div>
      <div class="stat2"><span class="stat-value">{{ dashboard.metrics?.ytdCurrent || 0 }}</span><div class="side-stat"><div class="label">Prior-Year YTD</div><div class="val">{{ dashboard.metrics?.ytdPrior || 0 }}</div></div></div>
    </section>
    <section class="card">
      <div class="card-head"><h3>Renewals Bound MTD</h3><span class="chip muted">vs. Expected</span></div>
      <div class="stat2"><span class="stat-value">{{ dashboard.metrics?.renewalsMtd || 0 }}</span><div class="side-stat"><div class="label">Expected Renewals</div><div class="val">{{ dashboard.metrics?.expectedRenewalsMtd || 0 }}</div></div></div>
    </section>
    <section class="card new-business-card">
      <div class="card-head"><h3>New Business MTD</h3><span class="chip muted">{{ dashboard.period?.currentMonth }}</span></div>
      <div class="stat2"><span class="stat-value">{{ dashboard.metrics?.newBusinessMtd || 0 }}</span><el-button v-if="can('cases.write')" size="small" class="primary-button" data-testid="dashboard-new-case" @click="router.push({ path: '/cases', query: { action: 'new' } })">+ New Case</el-button></div>
    </section>
  </div>

  <section class="card">
    <div class="card-head"><h3>YTD Brokerage Trend (TWD)</h3><el-select v-model="selectedTrendYear" aria-label="Brokerage trend year" data-testid="dashboard-trend-year" size="small" style="width: 110px" :disabled="dashboardLoading" @change="loadDashboard"><el-option v-for="year in trendYears" :key="year" :label="String(year)" :value="year" /></el-select></div>
    <div v-if="dashboard.brokerage?.labels?.length" class="trend-chart" aria-label="YTD brokerage grouped bar chart">
      <svg class="trend-svg" viewBox="0 0 900 220" role="img" aria-label="Prior year bars on the left, current year bars on the right, and monthly target line">
        <g class="trend-grid">
          <line x1="92" y1="34" x2="870" y2="34"></line>
          <line x1="92" y1="84" x2="870" y2="84"></line>
          <line x1="92" y1="134" x2="870" y2="134"></line>
          <line x1="92" y1="184" x2="870" y2="184"></line>
        </g>
        <g class="trend-axis-labels">
          <text x="84" y="38" text-anchor="end">{{ formatThousands(dashboardTrendMax()) }}</text>
          <text x="84" y="88" text-anchor="end">{{ formatThousands(dashboardTrendTick(2 / 3)) }}</text>
          <text x="84" y="138" text-anchor="end">{{ formatThousands(dashboardTrendTick(1 / 3)) }}</text>
          <text x="84" y="188" text-anchor="end">{{ formatThousands(dashboardTrendMin()) }}</text>
        </g>
        <line class="trend-zero" x1="92" :y1="dashboardTrendY(0)" x2="870" :y2="dashboardTrendY(0)" />
        <g v-for="(point,index) in dashboardTrendSeries(dashboard.brokerage.prior)" :key="'prior-bar-' + index">
          <rect class="trend-bar prior" :x="point.x - dashboardBarWidth() - 2" :y="Math.min(point.y, dashboardTrendY(0))" :width="dashboardBarWidth()" :height="Math.abs(point.y - dashboardTrendY(0))"><title>{{ dashboard.brokerage.labels[index] }} · {{ selectedTrendYear - 1 }} · Prior {{ formatAmount(point.value) }}</title></rect>
        </g>
        <g v-for="(point,index) in dashboardTrendSeries(dashboard.brokerage.current)" :key="'current-bar-' + index">
          <rect class="trend-bar current" :x="point.x + 2" :y="Math.min(point.y, dashboardTrendY(0))" :width="dashboardBarWidth()" :height="Math.abs(point.y - dashboardTrendY(0))"><title>{{ dashboard.brokerage.labels[index] }} · {{ selectedTrendYear }} · Current {{ formatAmount(point.value) }}</title></rect>
        </g>
        <polyline class="trend-line target" :points="dashboardTrendPoints(dashboard.brokerage.target)"></polyline>
        <g v-for="(point,index) in dashboardTrendSeries(dashboard.brokerage.target)" :key="'target-point-' + index">
          <circle class="trend-point target" :cx="point.x" :cy="point.y" r="3"><title>{{ dashboard.brokerage.labels[index] }} · Target {{ formatAmount(point.value) }}</title></circle>
        </g>
        <g class="trend-month-labels">
          <text v-for="(label,index) in dashboard.brokerage.labels" :key="'month-' + label" :x="dashboardTrendX(index, dashboard.brokerage.labels.length)" y="208" text-anchor="middle">{{ label }}</text>
        </g>
      </svg>
    </div>
    <div v-else class="empty-note">No performance months yet.</div>
    <p class="empty-note">Closed months use official Production amounts; other months are estimates. {{ (dashboard.brokerage?.labels||[]).map((month,index)=>month+': '+(dashboard.brokerage?.currentStatus?.[index]||'estimated')).join(' · ') }}</p><div class="legend"><span class="legend-item"><i style="background:#5F5F5F"></i>Prior year ({{ selectedTrendYear - 1 }})</span><span class="legend-item"><i style="background:#AF2D41"></i>Current year ({{ selectedTrendYear }})</span><span class="legend-item"><i style="background:#4A3AA7"></i>Monthly target</span></div>
  </section>

  <section class="card">
    <h3 style="margin-bottom:14px">Key Performance Indicators</h3>
    <div class="kpi-grid">
      <div class="kpi"><div class="label">In-Force Policies</div><div class="val">{{ dashboard.metrics?.inForcePolicies || 0 }}</div></div>
      <div class="kpi"><div class="label">Active Endorsements</div><div class="val">{{ dashboard.metrics?.activeEndorsements || 0 }}</div></div>
      <div class="kpi"><div class="label">Open Quotes</div><div class="val">{{ dashboard.metrics?.openQuotes || 0 }}</div></div>
      <div class="kpi"><div class="label">Renewal Retention Ratio</div><div class="val">{{ dashboard.metrics?.retentionRatio == null ? 'N/A' : formatAmount(dashboard.metrics.retentionRatio) }}<small v-if="dashboard.metrics?.retentionRatio != null">%</small></div></div>
      <div class="kpi"><div class="label">Total Gross Premium</div><div class="val">TWD {{ formatTwoDecimals(dashboard.metrics?.grossPremiumNtd || 0) }}</div></div>
      <div class="kpi"><div class="label">Accounting · Receivable / Payable</div><div class="val">TWD {{ formatAmount(dashboard.metrics?.outstandingLeg1Ntd || 0) }} / {{ formatAmount(dashboard.metrics?.outstandingLeg2Ntd || 0) }}</div><small v-if="dashboard.metrics?.missingPostingRates?.length">Awaiting FX — Past 5 years record only.</small><small v-else-if="dashboard.metrics?.accountingTotalEstimated">Estimated using latest FX until Production recognition</small><small v-if="dashboard.metrics?.outstandingSince && !dashboard.metrics?.missingPostingRates?.length" data-testid="outstanding-since">Past 5 years record only.</small></div>
    </div>
  </section>

  <div class="row2">
    <section class="card">
      <h3 style="margin-bottom:14px">Mix by Class of Business</h3>
      <div v-if="dashboard.classMix?.length" class="mix-list"><div v-for="row in dashboard.classMix" :key="'class-' + row.name" class="mix-row"><span>{{ row.name }}</span><span class="mix-track"><i class="mix-fill" :style="{width: Math.max(2,Number(row.pct || 0)) + '%'}"></i></span><strong>{{ Number(row.pct || 0).toFixed(1) }}%</strong></div></div>
      <div v-else class="empty-note">No in-force premium yet.</div>
    </section>
    <section class="card">
      <h3 style="margin-bottom:14px">Top Reinsurers/RI Broker by Ceded Premium</h3>
      <div v-if="dashboard.reinsurers?.length" class="mix-list"><div v-for="row in dashboard.reinsurers" :key="'reinsurer-' + row.name" class="mix-row"><span>{{ row.name }}</span><span class="mix-track"><i class="mix-fill" :style="{width: Math.max(2,Number(row.pct || 0)) + '%'}"></i></span><strong>{{ Number(row.pct || 0).toFixed(1) }}%</strong></div></div>
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
