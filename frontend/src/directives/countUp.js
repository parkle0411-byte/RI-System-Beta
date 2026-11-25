// 數字滾動：v-countup="{ to, fmt?, dec?, empty? }"。
// 值改變時從目前顯示的數字滾到新數字；第一次從 0 開始。減少動態效果時直接顯示結果。
// 目的只是畫面回饋：最終顯示的文字與原本的格式化結果完全相同（最後一格一律用 fmt 輸出精確值）。
const states = new WeakMap()
const DURATION = 450

function reduced() {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
}
// 最終值與原本的 {{ value }} 或 fmt 輸出完全相同（不加千分位）；滾動途中的整數取整數
function render(el, value, options, final) {
  el.textContent = options.fmt ? options.fmt(value) : (final ? String(value) : String(Math.round(value)))
}
function run(el, binding) {
  const options = binding.value || {}
  // null／undefined／空字串＝沒有資料（例如 Retention 的 N/A），不能當成 0
  const to = options.to === null || options.to === undefined || options.to === '' ? NaN : Number(options.to)
  const state = states.get(el) || { to: undefined, shown: 0, raf: 0 }
  states.set(el, state)
  if (!Number.isFinite(to)) {
    cancelAnimationFrame(state.raf)
    el.textContent = options.empty ?? '—'
    state.to = undefined
    state.shown = 0
    return
  }
  if (state.to === to) return
  cancelAnimationFrame(state.raf)
  const from = Number.isFinite(state.shown) ? state.shown : 0
  state.to = to
  if (reduced() || from === to) { render(el, to, options, true); state.shown = to; return }
  const t0 = performance.now()
  const frame = now => {
    const p = Math.min(1, (now - t0) / DURATION)
    if (p >= 1) { render(el, to, options, true); state.shown = to; return }
    const eased = 1 - Math.pow(1 - p, 3)
    state.shown = from + (to - from) * eased
    render(el, state.shown, options, false)
    state.raf = requestAnimationFrame(frame)
  }
  state.raf = requestAnimationFrame(frame)
}
export default {
  mounted: run,
  updated: run,
  unmounted(el) { const state = states.get(el); if (state) cancelAnimationFrame(state.raf); states.delete(el) }
}
