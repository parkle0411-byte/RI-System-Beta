<script setup>
// YTD Brokerage Trend 的互動柱狀圖（2026-11-25，業主決定：顏色與版面不變，只加互動）。
// 資料完全來自 /api/dashboard 的 brokerage（labels、current、prior、target、currentStatus、priorStatus），不新增任何欄位。
// 保留 VM 測試依賴的結構：svg.trend-svg 內只有一條 polyline.trend-line.target；每個月份各有 rect.trend-bar.prior／.current 與 circle.trend-point.target。
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { formatAmount } from '../alpha/format'

const props = defineProps({
  labels: { type: Array, default: () => [] },
  current: { type: Array, default: () => [] },
  prior: { type: Array, default: () => [] },
  target: { type: Array, default: () => [] },
  currentStatus: { type: Array, default: () => [] },
  priorStatus: { type: Array, default: () => [] },
  year: { type: Number, default: null },
  growKey: { type: Number, default: 0 }
})

const W = 900, H = 250, L = 66, R = 10, B = 26, T0 = 30
const num = v => (Number.isFinite(Number(v)) ? Number(v) : 0)
const short = v => `${new Intl.NumberFormat('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(num(v) / 1000)}K`
const pct = (a, b) => (b ? (a / b - 1) * 100 : null)
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
// 後端的月份標籤是 01～12；提示與摘要用月份縮寫，軸上的標籤維持原樣
const monthName = i => { const label = String(props.labels[i] ?? ''); return /^\d{1,2}$/.test(label) ? (MONTH_NAMES[Number(label) - 1] || label) : label }

// 控制項狀態
const cumulative = ref(false)
const showTarget = ref(true)
const labelMode = ref('off') // off | values | yoy
const sortMode = ref('time') // time | rank
const highlight = ref('all') // all | above | below
const visible = ref({ prior: true, current: true })
const pin = ref(null)
const range = ref(null)
const zoom = ref(null)
const reveal = ref(Infinity)
const hoverIndex = ref(null)
const spot = ref(null)
const tip = ref({ on: false, x: 0, y: 0 })
let dragFrom = null
let timer = null

const count = computed(() => props.labels.length)
const running = arr => { let s = 0; return arr.map(v => (s += num(v))) }
const series = computed(() => {
  let P = props.prior.map(num), C = props.current.map(num), T = props.target.map(num)
  if (cumulative.value) { P = running(P); C = running(C); T = running(T) }
  return { P, C, T }
})
const columns = computed(() => {
  const { P, C, T } = series.value
  let cols = props.labels.map((label, i) => ({
    i, label, P: P[i] ?? 0, C: C[i] ?? 0, T: T[i] ?? 0,
    est: props.currentStatus[i] === 'estimated', pest: props.priorStatus[i] === 'estimated'
  }))
  if (zoom.value) cols = cols.filter(c => c.i >= zoom.value[0] && c.i <= zoom.value[1])
  if (sortMode.value === 'rank') cols = cols.slice().sort((a, b) => b.C - a.C || a.i - b.i)
  return cols
})
const shown = computed(() => columns.value.slice(0, reveal.value))

// 座標：保留原本的負值支援（退款讓月金額可能為負）
const scale = computed(() => {
  const vals = []
  for (const c of columns.value) {
    if (visible.value.prior) vals.push(c.P)
    if (visible.value.current) vals.push(c.C)
    if (showTarget.value) vals.push(c.T)
  }
  const lo = Math.min(0, ...vals), hi = Math.max(1, ...vals)
  const raw = (hi - lo) / 4, pw = Math.pow(10, Math.floor(Math.log10(raw))), step = [1, 2, 2.5, 5, 10].map(k => k * pw).find(v => v >= raw)
  const min = Math.floor(lo / step) * step, max = Math.ceil(hi / step) * step
  const ticks = []
  for (let t = min; t <= max + step / 2; t += step) ticks.push(t)
  return { min, max, ticks }
})
const baseY = H - B
const plotH = H - B - T0
const y = v => baseY - ((v - scale.value.min) / (scale.value.max - scale.value.min || 1)) * plotH
const y0 = computed(() => y(0))
const slotW = computed(() => (W - L - R) / Math.max(1, columns.value.length))
const barGeo = (v, x, w) => {
  const yy = y(v), top = Math.min(yy, y0.value), h = Math.abs(yy - y0.value)
  return { x, y: top, width: w, height: h, neg: v < 0 }
}
function geoStyle(g) { return { x: g.x + 'px', y: g.y + 'px', width: g.width + 'px', height: g.height + 'px' } }
const hit = c => c.T > 0 && c.C >= c.T
const dimmed = c => highlight.value === 'above' ? !hit(c) : highlight.value === 'below' ? hit(c) : false
const targetPoints = computed(() => shown.value.map((c, s) => `${L + s * slotW.value + slotW.value / 2},${y(c.T)}`).join(' '))
const labelText = c => {
  if (labelMode.value === 'values') return short(c.C)
  if (labelMode.value === 'yoy') { const d = pct(c.C, c.P); return d == null ? '' : `${d >= 0 ? '+' : '−'}${Math.abs(d).toFixed(0)}%` }
  return ''
}
const labelClass = c => { if (labelMode.value !== 'yoy') return ''; const d = pct(c.C, c.P); return d == null ? '' : d >= 0 ? 'up' : 'dn' }

// 提示、釘住、範圍
function slotAt(event) {
  const box = chartEl.value?.querySelector('svg')?.getBoundingClientRect()
  if (!box) return -1
  return Math.floor(((event.clientX - box.left) * (W / box.width) - L) / slotW.value)
}
const chartEl = ref(null)
function onMove(event) {
  const slot = slotAt(event), col = shown.value[slot], box = chartEl.value.getBoundingClientRect()
  if (!col) { hoverIndex.value = null; tip.value.on = false; return }
  if (dragFrom != null && sortMode.value === 'time') {
    const a = shown.value[dragFrom]
    if (a) range.value = [Math.min(a.i, col.i), Math.max(a.i, col.i)]
  }
  hoverIndex.value = col.i
  tip.value = { on: true, x: Math.min(event.clientX - box.left + 14, box.width - 190), y: event.clientY - box.top - 10 }
}
function onLeave() { hoverIndex.value = null; tip.value.on = false; if (dragFrom != null) dragFrom = null }
function onDown(event) { const slot = slotAt(event); if (!shown.value[slot]) return; dragFrom = slot; range.value = null }
function onUp(event) {
  const col = shown.value[slotAt(event)], from = dragFrom
  dragFrom = null
  if (from == null || !col) return
  if (range.value && range.value[0] !== range.value[1]) pin.value = null
  else { range.value = null; pin.value = pin.value === col.i ? null : col.i }
}
function onKey(event) {
  const list = shown.value
  if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
    event.preventDefault()
    if (!list.length) return
    const at = list.findIndex(c => c.i === pin.value)
    const next = at < 0 ? (event.key === 'ArrowRight' ? 0 : list.length - 1) : Math.max(0, Math.min(list.length - 1, at + (event.key === 'ArrowRight' ? 1 : -1)))
    range.value = null; pin.value = list[next].i
  } else if (event.key === 'Escape') {
    if (pin.value != null || range.value) { pin.value = null; range.value = null } else if (zoom.value) zoom.value = null
  }
}
const hoverCol = computed(() => columns.value.find(c => c.i === hoverIndex.value))
const tipRows = computed(() => {
  const c = hoverCol.value
  if (!c) return []
  const rows = [{ k: 'title', v: `${monthName(c.i)}${cumulative.value ? ' · YTD' : ''}` }]
  if (visible.value.prior) rows.push({ k: `${props.year - 1}${c.pest ? ' (est.)' : ''}`, v: formatAmount(c.P) })
  if (visible.value.current) rows.push({ k: `${props.year}${c.est ? ' (est.)' : ''}`, v: formatAmount(c.C) })
  if (showTarget.value) rows.push({ k: 'Target', v: c.T ? `${formatAmount(c.T)} · ${(c.C / c.T * 100).toFixed(0)}%` : formatAmount(c.T) })
  return rows
})

// 摘要列
const raw = i => ({ P: num(props.prior[i]), C: num(props.current[i]), T: num(props.target[i]) })
const deltaText = d => (d == null ? '' : `${d >= 0 ? '▲' : '▼'} ${Math.abs(d).toFixed(1)}%`)
const summary = computed(() => {
  if (range.value) {
    let p = 0, c = 0, t = 0
    for (let i = range.value[0]; i <= range.value[1]; i++) { const r = raw(i); p += r.P; c += r.C; t += r.T }
    const n = range.value[1] - range.value[0] + 1
    return { kind: 'range', title: `${monthName(range.value[0])}–${monthName(range.value[1])}`, total: c, avg: c / n, delta: pct(c, p), attain: t ? c / t * 100 : null }
  }
  if (pin.value != null) {
    const r = raw(pin.value)
    return { kind: 'pin', title: `${monthName(pin.value)} ${props.year}`, value: r.C, est: props.currentStatus[pin.value] === 'estimated', prior: r.P, delta: pct(r.C, r.P), attain: r.T ? r.C / r.T * 100 : null }
  }
  if (highlight.value !== 'all') {
    const above = columns.value.filter(hit).length
    return { kind: 'hl', n: highlight.value === 'above' ? above : columns.value.length - above, of: columns.value.length }
  }
  return { kind: 'hint' }
})

function replay() {
  clearInterval(timer)
  reveal.value = 0
  timer = setInterval(() => { reveal.value++; if (reveal.value >= columns.value.length) { clearInterval(timer); reveal.value = Infinity } }, 170)
}
function zoomIn() { if (range.value) { zoom.value = range.value.slice(); range.value = null; pin.value = null; sortMode.value = 'time' } }
function toggleSeries(key) { visible.value = { ...visible.value, [key]: !visible.value[key] } }

watch(() => props.labels.length, () => { pin.value = null; range.value = null; zoom.value = null })
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <div class="trend-wrap">
    <div class="ctools">
      <div class="seg" role="group" aria-label="Basis">
        <button type="button" :class="{ on: !cumulative }" @click="cumulative = false">Monthly</button>
        <button type="button" :class="{ on: cumulative }" @click="cumulative = true">Cumulative</button>
      </div>
      <div class="seg" role="group" aria-label="Order">
        <button type="button" :class="{ on: sortMode === 'time' }" @click="sortMode = 'time'">Time</button>
        <button type="button" :class="{ on: sortMode === 'rank' }" @click="sortMode = 'rank'; range = null">Rank</button>
      </div>
      <div class="seg" role="group" aria-label="Labels">
        <button type="button" :class="{ on: labelMode === 'off' }" @click="labelMode = 'off'">No labels</button>
        <button type="button" :class="{ on: labelMode === 'values' }" @click="labelMode = 'values'">Values</button>
        <button type="button" :class="{ on: labelMode === 'yoy' }" @click="labelMode = 'yoy'">YoY %</button>
      </div>
    </div>
    <div class="ctools">
      <button type="button" class="fchip" :class="{ active: highlight === 'all' }" @click="highlight = 'all'">All</button>
      <button type="button" class="fchip" :class="{ active: highlight === 'above' }" @click="highlight = 'above'">At/above target</button>
      <button type="button" class="fchip" :class="{ active: highlight === 'below' }" @click="highlight = 'below'">Below target</button>
      <label class="tgl"><input v-model="showTarget" type="checkbox"> Target</label>
      <button v-if="zoom" type="button" class="fchip active" @click="zoom = null">Zoom {{ monthName(zoom[0]) }}–{{ monthName(zoom[1]) }} ✕</button>
      <button type="button" class="el-button secondary-button replay-button" @click="replay">▶ Replay</button>
    </div>

    <div ref="chartEl" class="chart trend-chart" :class="{ hovering: hoverIndex != null, spotprior: spot === 'prior', spotcurrent: spot === 'current' }" tabindex="0" aria-label="YTD brokerage grouped bar chart. Arrow keys move between months, Escape clears."
      @pointermove="onMove" @pointerleave="onLeave" @pointerdown="onDown" @pointerup="onUp" @keydown="onKey">
      <svg class="trend-svg" :viewBox="`0 0 ${W} ${H}`" role="img" aria-label="Prior year bars on the left, current year bars on the right, and monthly target line">
        <defs>
          <pattern id="trend-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="#F7E4E7" /><rect width="2.5" height="6" fill="#AF2D41" /></pattern>
        </defs>
        <g class="trend-grid">
          <line v-for="t in scale.ticks" :key="'g' + t" :x1="L" :y1="y(t)" :x2="W - R" :y2="y(t)"></line>
        </g>
        <g class="trend-axis-labels">
          <text v-for="t in scale.ticks" :key="'a' + t" :x="L - 8" :y="y(t) + 4" text-anchor="end">{{ short(t) }}</text>
        </g>
        <line class="trend-zero" :x1="L" :y1="y0" :x2="W - R" :y2="y0" />
        <polyline class="trend-line target" :points="targetPoints" :style="{ opacity: showTarget && sortMode === 'time' ? 1 : 0 }"></polyline>
        <g v-for="(c, slot) in shown" :key="c.i + '-' + growKey" class="col" :class="{ dim: dimmed(c), hot: hoverIndex === c.i }" :style="{ transform: `translateX(${L + slot * slotW}px)`, '--slot': slot }">
          <rect class="band" :class="{ on: hoverIndex === c.i, pin: pin === c.i, rng: range && c.i >= range[0] && c.i <= range[1] }" x="0" :y="T0" :width="slotW" :height="plotH" />
          <rect class="trend-bar prior" :class="{ off: !visible.prior, neg: c.P < 0 }" :x="barGeo(c.P, slotW * .16, slotW * .32).x" :y="barGeo(c.P, 0, 0).y" :width="slotW * .32" :height="barGeo(c.P, 0, 0).height" :style="geoStyle(barGeo(c.P, slotW * .16, slotW * .32))"><title>{{ labels[c.i] }} · {{ year - 1 }} · Prior {{ formatAmount(c.P) }}</title></rect>
          <rect class="trend-bar current" :class="{ off: !visible.current, neg: c.C < 0, est: c.est }" :x="barGeo(c.C, slotW * .52, slotW * .32).x" :y="barGeo(c.C, 0, 0).y" :width="slotW * .32" :height="barGeo(c.C, 0, 0).height" :style="geoStyle(barGeo(c.C, slotW * .52, slotW * .32))"><title>{{ labels[c.i] }} · {{ year }} · Current {{ formatAmount(c.C) }}</title></rect>
          <rect class="tgt" :x="slotW * .08" :y="y(c.T) - 1" :width="slotW * .84" height="2" :style="{ opacity: showTarget && sortMode === 'rank' ? 1 : 0 }" />
          <circle class="trend-point target" :cx="slotW / 2" :cy="y(c.T)" r="3" :style="{ opacity: showTarget ? 1 : 0 }"><title>{{ labels[c.i] }} · Target {{ formatAmount(c.T) }}</title></circle>
          <path v-if="showTarget && hit(c) && visible.current" class="beat" d="M-4 0h8l-4-6z" :style="{ transform: `translate(${slotW * .68}px, ${Math.min(y(c.C), y0) - 4}px)` }" />
          <text v-if="labelMode !== 'off' && visible.current && labelText(c)" class="vlab" :class="labelClass(c)" :x="slotW * .68" :y="Math.min(y(c.C), y0) - (showTarget && hit(c) ? 14 : 6)" text-anchor="middle">{{ labelText(c) }}</text>
          <text class="trend-month" :x="slotW / 2" :y="H - 8" text-anchor="middle">{{ c.label }}</text>
        </g>
      </svg>
      <div class="ctip" :class="{ on: tip.on && tipRows.length }" :style="{ left: tip.x + 'px', top: tip.y + 'px' }">
        <template v-for="row in tipRows" :key="row.k"><b v-if="row.k === 'title'">{{ row.v }}</b><span v-else class="tiprow"><span>{{ row.k }}</span><span>{{ row.v }}</span></span></template>
      </div>
    </div>

    <div class="cdetail" :key="summary.kind + String(pin) + String(range)">
      <template v-if="summary.kind === 'range'">
        <b>{{ summary.title }}</b><span>Total <b>{{ short(summary.total) }}</b></span><span>Avg <b>{{ short(summary.avg) }}</b>/mo</span>
        <span v-if="summary.delta != null" :class="summary.delta >= 0 ? 'up' : 'dn'">{{ deltaText(summary.delta) }} vs {{ year - 1 }}</span>
        <span v-if="summary.attain != null"><b>{{ summary.attain.toFixed(0) }}%</b> of target</span>
        <button type="button" class="x pill" @click="zoomIn">Zoom in ⤢</button><button type="button" class="x" @click="range = null">Clear ✕</button>
      </template>
      <template v-else-if="summary.kind === 'pin'">
        <b>{{ summary.title }}</b><span><b>{{ short(summary.value) }}</b><template v-if="summary.est"> (estimate)</template></span>
        <span v-if="summary.delta != null" :class="summary.delta >= 0 ? 'up' : 'dn'">{{ deltaText(summary.delta) }} vs {{ short(summary.prior) }} in {{ year - 1 }}</span>
        <span v-if="summary.attain != null"><b>{{ summary.attain.toFixed(0) }}%</b> of target</span>
        <button type="button" class="x" @click="pin = null">✕</button>
      </template>
      <template v-else-if="summary.kind === 'hl'"><b>{{ summary.n }} of {{ summary.of }}</b><span>{{ highlight === 'above' ? 'months at or above target' : 'months below target' }}</span></template>
      <span v-else class="cvhint">Hover for values · click to pin · drag across months to total a range · ← → keys to step · Hatched = estimate</span>
    </div>

    <div class="legend">
      <button type="button" class="lgd" :class="{ off: !visible.prior }" @click="toggleSeries('prior')" @mouseenter="spot = 'prior'" @mouseleave="spot = null"><i style="background:#5F5F5F"></i>Prior year ({{ year - 1 }})</button>
      <button type="button" class="lgd" :class="{ off: !visible.current }" @click="toggleSeries('current')" @mouseenter="spot = 'current'" @mouseleave="spot = null"><i style="background:#AF2D41"></i>Current year ({{ year }})</button>
      <span class="legend-item"><i style="background:#4A3AA7"></i>Monthly target</span>
      <span class="legend-item"><i class="hatch-swatch"></i>Estimate</span>
    </div>
  </div>
</template>
