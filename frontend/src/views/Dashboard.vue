<script setup>
// 移植自 Alpha index.html 的 activeView === 'dashboard'（模板第 71–148 行原樣）與 app.js 的 loadDashboard()、
// dashboardTrendValues()／dashboardTrendMax()／dashboardTrendX()／dashboardTrendY()／dashboardTrendPoints()／dashboardTrendSeries()、formatThousands()。
// 與 Alpha 不同的地方（見 MIGRATION-STATUS.md）：後端用台北時間、趨勢用 Production 的規則；畫面是 fetch() → apiFetch()，
// 以及下面的 <style>：占比長條的填色 <i class="mix-fill"> 是行內元素，Alpha 的 height:100% 對它無效、長條沒有填色，補上 display:block。
import { onMounted, ref } from 'vue'
import { apiFetch } from '../api'
import { can } from '../auth'
import { formatAmount } from '../alpha/format'
import { shell } from '../alpha/shell'

const dashboardLoading = ref(false)
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
  return 92 + (index * 778 / (total - 1))
}
function dashboardTrendY(value) {
  return 184 - (Math.max(0, Number(value || 0)) / dashboardTrendMax() * 150)
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
  if (!can('dashboard.read')) return
  dashboardLoading.value = true
  shell.error = ''
  try {
    const response = await apiFetch('/api/dashboard', { headers: { Accept: 'application/json' } })
    const body = await response.json()
    if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
    dashboard.value = body
  } catch (err) {
    shell.error = err instanceof Error ? err.message : String(err)
  } finally {
    dashboardLoading.value = false
  }
}

onMounted(loadDashboard)
</script>

<template>
<div class="rdash" v-loading="dashboardLoading">
  <div class="row3">
    <section class="card">
      <div class="card-head"><h3>YTD Case Volume</h3><span class="chip muted">{{ dashboard.period?.year }}</span></div>
      <div class="stat2"><span class="stat-value">{{ dashboard.metrics?.ytdCurrent || 0 }}</span><div class="side-stat"><div class="label">Prior-Year YTD</div><div class="val">{{ dashboard.metrics?.ytdPrior || 0 }}</div></div></div>
    </section>
    <section class="card">
      <div class="card-head"><h3>Renewals Bound MTD</h3><span class="chip muted">vs. Expected</span></div>
      <div class="stat2"><span class="stat-value">{{ dashboard.metrics?.renewalsMtd || 0 }}</span><div class="side-stat"><div class="label">Expected Renewals</div><div class="val">{{ dashboard.metrics?.expectedRenewalsMtd || 0 }}</div></div></div>
    </section>
    <section class="card">
      <div class="card-head"><h3>New Business MTD</h3><span class="chip muted">{{ dashboard.period?.currentMonth }}</span></div>
      <div class="stat2"><span class="stat-value">{{ dashboard.metrics?.newBusinessMtd || 0 }}</span></div>
    </section>
  </div>

  <section class="card">
    <div class="card-head"><h3>YTD Brokerage Trend</h3><span class="chip muted">{{ dashboard.period?.year }}</span></div>
    <div v-if="dashboard.brokerage?.labels?.length" class="trend-chart" aria-label="YTD brokerage trend line chart">
      <svg class="trend-svg" viewBox="0 0 900 220" role="img" aria-label="Current year, prior year and target brokerage trend">
        <g class="trend-grid">
          <line x1="92" y1="34" x2="870" y2="34"></line>
          <line x1="92" y1="84" x2="870" y2="84"></line>
          <line x1="92" y1="134" x2="870" y2="134"></line>
          <line x1="92" y1="184" x2="870" y2="184"></line>
        </g>
        <g class="trend-axis-labels">
          <text x="84" y="38" text-anchor="end">{{ formatThousands(dashboardTrendMax()) }}</text>
          <text x="84" y="88" text-anchor="end">{{ formatThousands(dashboardTrendMax() * 2 / 3) }}</text>
          <text x="84" y="138" text-anchor="end">{{ formatThousands(dashboardTrendMax() / 3) }}</text>
          <text x="84" y="188" text-anchor="end">0K</text>
        </g>
        <polyline class="trend-line prior" :points="dashboardTrendPoints(dashboard.brokerage.prior)"></polyline>
        <polyline class="trend-line target" :points="dashboardTrendPoints(dashboard.brokerage.target)"></polyline>
        <polyline class="trend-line current" :points="dashboardTrendPoints(dashboard.brokerage.current)"></polyline>
        <g v-for="(point,index) in dashboardTrendSeries(dashboard.brokerage.prior)" :key="'prior-point-' + index">
          <circle class="trend-point prior" :cx="point.x" :cy="point.y" r="3"><title>{{ dashboard.brokerage.labels[index] }} · Prior {{ formatAmount(point.value) }}</title></circle>
        </g>
        <g v-for="(point,index) in dashboardTrendSeries(dashboard.brokerage.target)" :key="'target-point-' + index">
          <circle class="trend-point target" :cx="point.x" :cy="point.y" r="3"><title>{{ dashboard.brokerage.labels[index] }} · Target {{ formatAmount(point.value) }}</title></circle>
        </g>
        <g v-for="(point,index) in dashboardTrendSeries(dashboard.brokerage.current)" :key="'current-point-' + index">
          <circle class="trend-point current" :cx="point.x" :cy="point.y" r="4"><title>{{ dashboard.brokerage.labels[index] }} · Current {{ formatAmount(point.value) }}</title></circle>
        </g>
        <g class="trend-month-labels">
          <text v-for="(label,index) in dashboard.brokerage.labels" :key="'month-' + label" :x="dashboardTrendX(index, dashboard.brokerage.labels.length)" y="208" text-anchor="middle">{{ label }}</text>
        </g>
      </svg>
    </div>
    <div v-else class="empty-note">No performance months yet.</div>
    <div class="legend"><span class="legend-item"><i style="background:#AF2D41"></i>Current year</span><span class="legend-item"><i style="background:#5F5F5F"></i>Prior year</span><span class="legend-item"><i style="background:#4A3AA7"></i>Monthly target</span></div>
  </section>

  <section class="card">
    <h3 style="margin-bottom:14px">Key Performance Indicators</h3>
    <div class="kpi-grid">
      <div class="kpi"><div class="label">In-Force Policies</div><div class="val">{{ dashboard.metrics?.inForcePolicies || 0 }}</div></div>
      <div class="kpi"><div class="label">Active Endorsements</div><div class="val">{{ dashboard.metrics?.activeEndorsements || 0 }}</div></div>
      <div class="kpi"><div class="label">Open Quotes</div><div class="val">{{ dashboard.metrics?.openQuotes || 0 }}</div></div>
      <div class="kpi"><div class="label">Renewal Retention Ratio</div><div class="val">{{ dashboard.metrics?.retentionRatio == null ? 'N/A' : formatAmount(dashboard.metrics.retentionRatio) }}<small v-if="dashboard.metrics?.retentionRatio != null">%</small></div></div>
      <div class="kpi"><div class="label">Total Gross Premium</div><div class="val">{{ formatAmount(dashboard.metrics?.grossPremiumNtd || 0) }}<small>NT$</small></div></div>
      <div class="kpi"><div class="label">Outstanding · Cedant / Reinsurer</div><div class="val">{{ formatAmount(dashboard.metrics?.outstandingLeg1Ntd || 0) }} / {{ formatAmount(dashboard.metrics?.outstandingLeg2Ntd || 0) }}<small>NT$</small></div></div>
    </div>
  </section>

  <div class="row2">
    <section class="card">
      <h3 style="margin-bottom:14px">Mix by Class of Business</h3>
      <div v-if="dashboard.classMix?.length" class="mix-list"><div v-for="row in dashboard.classMix" :key="'class-' + row.name" class="mix-row"><span>{{ row.name }}</span><span class="mix-track"><i class="mix-fill" :style="{width: Math.max(2,Number(row.pct || 0)) + '%'}"></i></span><strong>{{ Number(row.pct || 0).toFixed(1) }}%</strong></div></div>
      <div v-else class="empty-note">No in-force premium yet.</div>
    </section>
    <section class="card">
      <h3 style="margin-bottom:14px">Top Reinsurers by Ceded Premium</h3>
      <div v-if="dashboard.reinsurers?.length" class="mix-list"><div v-for="row in dashboard.reinsurers" :key="'reinsurer-' + row.name" class="mix-row"><span>{{ row.name }}</span><span class="mix-track"><i class="mix-fill" :style="{width: Math.max(2,Number(row.pct || 0)) + '%'}"></i></span><strong>{{ Number(row.pct || 0).toFixed(1) }}%</strong></div></div>
      <div v-else class="empty-note">No in-force premium yet.</div>
    </section>
  </div>
</div>
</template>

<style>
/* VM 修正：Alpha 的 .mix-fill 沒有 display:block，長條不會顯示（Alpha 的 CSS 檔保持原樣） */
.rdash .mix-fill { display: block; }
</style>
