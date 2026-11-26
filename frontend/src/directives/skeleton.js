// 載入骨架條（2026-11-26 業主決定）：取代 Element Plus 的 v-loading 轉圈遮罩。灰條的位置直接量自畫面上的真實元素。
// 用法：v-skeleton="{ on: loading, kind: 'table', rows: 6, rowH: 48 }"
//   on    是否載入中（與原本 v-loading 的值相同）
//   kind  table：保留真實的標題、工具列與表頭，只在資料列位置依實際欄位位置畫灰條（rows／rowH＝還沒有資料列時要畫幾列、列高）
//         blocks：保留卡片與標題，只把標了 data-sk 的資料元素換成同位置、同大小的灰條（Dashboard 用）
//         mirror（預設）：區塊內每一段文字、按鈕、輸入框的位置各畫一條灰條，卡片框照常顯示；區塊還是空的時畫幾行（rows）
// kind=table／blocks 時，區塊裡標了 data-sk 的元素也一併換成灰條（例如標題裡的筆數、統計數字）。
// 載入中區塊上蓋一層透明層擋住點擊（與 v-loading 相同）；樣式在 alpha/styles/skeleton.css；減少動態效果時長條不閃動。
const STATES = new WeakMap()
const MAX_BARS = 400

function div(className) { const el = document.createElement('div'); el.className = className; return el }
function visible(node) { const r = node.getBoundingClientRect(); return r.width > 0 && r.height > 0 }

// 量出要畫的灰條（座標相對於區塊內緣）
function measure(el, o) {
  const base = el.getBoundingClientRect()
  const dx = base.left + el.clientLeft - el.scrollLeft, dy = base.top + el.clientTop - el.scrollTop
  const bars = []
  const add = (type, x, y, w, h) => { if (w >= 4 && h >= 2 && bars.length < MAX_BARS) bars.push({ type, x: Math.round(x - dx), y: Math.round(y - dy), w: Math.round(w), h: Math.round(h) }) }
  const kind = o.kind || 'mirror'
  if (kind === 'table') {
    const tables = el.matches('.el-table') ? [el] : [...el.querySelectorAll('.el-table')]
    for (const table of tables.filter(visible)) {
      const box = table.getBoundingClientRect()
      const head = table.querySelector('.el-table__header-wrapper')
      if (!head) continue
      const clip = (type, r, y, h) => { // 欄位超出表格可視範圍的部分不畫
        const left = Math.max(r.left, box.left), right = Math.min(r.right, box.right)
        const pad = Math.min(12, (right - left) / 4)
        add(type, left + pad, y, (right - left - pad * 2) * type.fill, h)
      }
      const real = [...table.querySelectorAll('.el-table__body-wrapper tbody tr.el-table__row')].filter(visible)
      if (real.length) { // 重新載入：資料列就在原位置
        const limit = Math.min(box.bottom, window.innerHeight + 200)
        real.forEach((row, r) => {
          const rr = row.getBoundingClientRect()
          if (rr.top >= limit) return
          ;[...row.children].forEach((cell, c) => { const cr = cell.getBoundingClientRect(); if (cr.right > box.left && cr.left < box.right) clip(cellType(r, c), cr, cr.top + cr.height / 2 - 6, 12) })
        })
      } else { // 第一次載入：照表頭欄位位置往下畫
        const ths = [...head.querySelectorAll('thead tr:last-child th:not(.gutter)')].filter(visible)
        const top = head.getBoundingClientRect().bottom
        const rows = Math.min(o.rows || 6, 12), rowH = o.rowH || 48
        for (let r = 0; r < rows; r++) ths.forEach((th, c) => { const tr = th.getBoundingClientRect(); if (tr.right > box.left && tr.left < box.right) clip(cellType(r, c), tr, top + r * rowH + rowH / 2 - 6, 12) })
      }
    }
  }
  if (kind === 'table' || kind === 'blocks') {
    for (const node of el.querySelectorAll('[data-sk]')) {
      if (!visible(node)) continue
      const r = node.getBoundingClientRect()
      const h = r.height > 60 ? r.height : Math.max(8, r.height - 6)
      add({ name: r.height > 60 ? 'area' : 'value', fill: 1 }, r.left, r.top + (r.height - h) / 2, r.width, h)
    }
  } else {
    const controls = [...el.querySelectorAll('button, .el-input__wrapper, .el-select__wrapper, .el-textarea__inner, .status-badge, .pending-badge, .el-upload-dragger')].filter(visible)
    for (const node of controls) { const r = node.getBoundingClientRect(); add({ name: 'control', fill: 1 }, r.left, r.top, r.width, r.height) }
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
    const range = document.createRange()
    for (let t = walker.nextNode(); t; t = walker.nextNode()) {
      const parent = t.parentElement
      if (!t.textContent.trim() || !parent || parent.closest('.skeleton-mask') || controls.some(c => c.contains(parent))) continue
      range.selectNodeContents(t)
      for (const r of range.getClientRects()) { const h = Math.min(14, Math.max(8, r.height - 6)); if (r.width > 0) add({ name: 'text', fill: 1 }, r.left, r.top + (r.height - h) / 2, r.width, h) }
    }
    if (bars.length < 2) { // 區塊還沒有任何內容
      const width = el.clientWidth
      for (let i = 0; i < (o.rows || 3); i++) add({ name: 'line', fill: 1 }, dx + 16, dy + 16 + i * 26, (width - 32) * [0.92, 0.64, 0.78, 0.55, 0.86][i % 5], 12)
    }
  }
  return bars
}
// 同一欄的灰條寬度固定比例輪流，避免整齊得像格線（同一個畫面永遠長一樣）
const FILL = [0.9, 0.62, 0.76, 0.55, 0.84, 0.68]
function cellType(r, c) { return { name: 'cell', fill: FILL[(r * 3 + c) % FILL.length], row: r, col: c } }

// 第一次載入時表格是空的、很矮；撐出要畫的列數，灰條才不會蓋到下面的內容
function reserve(el, o, state) {
  if ((o.kind || 'mirror') === 'table') {
    const tables = el.matches('.el-table') ? [el] : [...el.querySelectorAll('.el-table')]
    for (const table of tables) {
      if (state.sized.has(table) || !visible(table) || table.querySelector('tr.el-table__row')) continue
      const head = table.querySelector('.el-table__header-wrapper')
      if (!head) continue
      state.sized.set(table, table.style.minHeight)
      table.style.minHeight = Math.round(head.getBoundingClientRect().height + Math.min(o.rows || 6, 12) * (o.rowH || 48)) + 'px'
    }
  } else if ((o.kind || 'mirror') === 'mirror' && !state.sized.has(el) && !el.textContent.trim()) {
    state.sized.set(el, el.style.minHeight)
    el.style.minHeight = (o.rows || 3) * 26 + 24 + 'px'
  }
}
function draw(el, state) {
  const o = state.options
  reserve(el, o, state)
  const bars = measure(el, o)
  const signature = bars.map(b => `${b.x},${b.y},${b.w},${b.h}`).join(';')
  if (signature !== state.signature || !state.node.isConnected) {
    state.signature = signature
    state.node.replaceChildren(...bars.map(b => {
      const bar = div('sk-bar sk-' + b.type.name)
      Object.assign(bar.style, { left: b.x + 'px', top: b.y + 'px', width: b.w + 'px', height: b.h + 'px' })
      if (b.type.row !== undefined) { bar.dataset.row = b.type.row; bar.dataset.col = b.type.col }
      return bar
    }))
  }
  if (!state.node.isConnected) el.append(state.node)
  // 版面在載入期間還可能移動（表格算欄寬、上方提示出現）：剛開始每格畫面重量一次，之後每 150 毫秒一次，位置有變才重畫
  state.frame = setTimeout(() => draw(el, state), state.ticks++ < 4 ? 16 : 150)
}
function remove(el) {
  const state = STATES.get(el)
  if (!state) return
  clearTimeout(state.frame)
  state.node.remove()
  for (const [node, previous] of state.sized) node.style.minHeight = previous
  STATES.delete(el)
  el.removeAttribute('aria-busy'); el.removeAttribute('data-sk-loading'); el.classList.remove('skeleton-parent')
}
function apply(el, binding) {
  const o = binding.value || {}
  if (!o.on) { remove(el); return }
  // 蓋在區塊上需要區塊是定位容器；和 v-loading 一樣在區塊還是 static 時才補。區塊重繪後再補一次（Vue 可能洗掉 class）
  if (getComputedStyle(el).position === 'static') el.classList.add('skeleton-parent')
  el.setAttribute('aria-busy', 'true')
  el.setAttribute('data-sk-loading', o.kind || 'mirror')
  let state = STATES.get(el)
  if (state) { state.options = o; return }
  const node = div('skeleton-mask')
  node.setAttribute('aria-hidden', 'true')
  node.dataset.testid = 'skeleton'
  state = { node, options: o, signature: null, sized: new Map(), frame: 0, ticks: 0 }
  STATES.set(el, state)
  el.append(node)
  draw(el, state)
}
export const vSkeleton = { mounted: apply, updated: apply, unmounted: remove }
