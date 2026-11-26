// 載入骨架條（2026-11-26 業主決定）：取代 Element Plus 的 v-loading 轉圈遮罩。
// 用法：v-skeleton="{ on: loading, kind: 'table', cols: 8, rows: 6 }"
//   tool  table 專用：false＝不畫最上面的工具列（區塊自己已有工具列時用）
//   on    是否載入中（與原本 v-loading 的值相同）
//   kind  table（工具列＋表頭＋資料列）、lines（幾行文字，小區塊用）、form（幾個欄位）、dashboard（統計卡＋圖表）
// 載入中時在該區塊上蓋一層不透明的白底，畫出「資料即將出現」的灰色長條（亮光輕輕流動）；載入完成就移除。
// 不碰區塊內容；樣式在 alpha/styles/skeleton.css；減少動態效果時長條不流動。
const OVERLAYS = new WeakMap()

function box(className, style) {
  const el = document.createElement('div')
  el.className = className
  if (style) Object.assign(el.style, style)
  return el
}
// 長條寬度用固定樣式輪流，避免每次都一樣整齊、也不需要亂數（同一個畫面永遠長一樣）
const WIDTHS = [92, 64, 78, 55, 86, 70, 60, 82]
function bar(i, extra = '') { return box('sk-bar ' + extra, { width: WIDTHS[i % WIDTHS.length] + '%' }) }

function build(o) {
  const root = box('skeleton-mask')
  root.setAttribute('aria-hidden', 'true')
  root.dataset.testid = 'skeleton'
  const kind = o.kind || 'lines'
  if (kind === 'table') {
    const cols = Math.min(Math.max(o.cols || 6, 2), 10), rows = Math.min(o.rows || 6, 12)
    if (o.tool !== false) { const tool = box('sk-tool'); tool.append(box('sk-bar sk-pill', { width: '220px' }), box('sk-bar sk-pill', { width: '120px' })); root.append(tool) }
    const head = box('sk-row sk-head'); for (let c = 0; c < cols; c++) head.append(box('sk-bar sk-th', { flex: c === 0 ? '1.4' : '1' })); root.append(head)
    for (let r = 0; r < rows; r++) { const row = box('sk-row'); for (let c = 0; c < cols; c++) row.append(bar(r * 3 + c, 'sk-cell')); root.append(row) }
  } else if (kind === 'form') {
    for (let i = 0; i < (o.rows || 3); i++) { const f = box('sk-field'); f.append(box('sk-bar sk-label', { width: '30%' }), box('sk-bar sk-input')); root.append(f) }
  } else if (kind === 'dashboard') {
    const kpis = box('sk-kpis'); for (let i = 0; i < 3; i++) { const k = box('sk-card'); k.append(box('sk-bar', { width: '45%' }), box('sk-bar sk-big', { width: '70%' }), box('sk-bar', { width: '35%' })); kpis.append(k) } root.append(kpis)
    const grid = box('sk-grid'); grid.append(box('sk-card sk-chart'))
    const side = box('sk-card'); for (let i = 0; i < 5; i++) side.append(bar(i)); grid.append(side); root.append(grid)
    const rows = box('sk-grid'); for (let j = 0; j < 2; j++) { const c = box('sk-card'); for (let i = 0; i < 4; i++) c.append(bar(i + j)); rows.append(c) } root.append(rows)
  } else {
    for (let i = 0; i < (o.rows || 3); i++) root.append(bar(i, 'sk-line'))
  }
  return root
}
// 蓋在區塊上需要區塊是定位容器；和 v-loading 一樣在區塊還是 static 時才補。每次區塊重繪後再補一次（Vue 可能洗掉 class）
function ensureParent(el) {
  if (getComputedStyle(el).position === 'static') el.classList.add('skeleton-parent')
}
// 載入中區塊常常是空的（高度只有一點點），骨架會被裁掉；載入期間給區塊一個最小高度，讓骨架畫得出來
function minHeight(o) {
  const kind = o.kind || 'lines'
  if (kind === 'table') return (o.tool === false ? 0 : 50) + 46 + Math.min(o.rows || 6, 12) * 40 + 32
  if (kind === 'form') return (o.rows || 3) * 66 + 32
  if (kind === 'dashboard') return 560
  return (o.rows || 3) * 24 + 32
}
function apply(el, binding) {
  const o = binding.value || {}
  const shown = OVERLAYS.get(el)
  if (o.on) {
    ensureParent(el)
    el.setAttribute('aria-busy', 'true')
    el.style.minHeight = minHeight(o) + 'px'
    if (!shown || shown.dataset.kind !== (o.kind || 'lines') + (o.cols || '') + (o.rows || '') + (o.tool === false ? 'x' : '')) {
      if (shown) shown.remove()
      const node = build(o); node.dataset.kind = (o.kind || 'lines') + (o.cols || '') + (o.rows || '') + (o.tool === false ? 'x' : '')
      el.append(node); OVERLAYS.set(el, node)
    }
  } else if (shown) {
    shown.remove(); OVERLAYS.delete(el); el.removeAttribute('aria-busy'); el.classList.remove('skeleton-parent'); el.style.minHeight = ''
  }
}
export const vSkeleton = {
  mounted: apply,
  updated: apply,
  unmounted(el) { const shown = OVERLAYS.get(el); if (shown) shown.remove(); OVERLAYS.delete(el); el.style.minHeight = '' },
}
