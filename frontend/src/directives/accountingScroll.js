// Always visible, keyboard/touch accessible horizontal control for Accounting tables.
const instances = new WeakMap()
export default {
  mounted(el) {
    const top = document.createElement('div')
    top.className = 'accounting-top-scroll'
    Object.assign(top.style, { height: '18px', maxWidth: '100%', marginBottom: '4px' })
    const slider = document.createElement('input')
    slider.type = 'range'; slider.min = '0'; slider.step = '1'; slider.value = '0'
    slider.setAttribute('aria-label', 'Scroll accounting table horizontally')
    top.appendChild(slider); el.before(top)
    let wrap, body, frame
    const fromTop = () => { if (wrap) wrap.scrollLeft = Number(slider.value) }
    const fromBody = () => { if (wrap) slider.value = String(wrap.scrollLeft) }
    const observer = new ResizeObserver(() => schedule())
    const sync = () => {
      const next = el.querySelector('.el-table__body-wrapper .el-scrollbar__wrap')
      const nextBody = el.querySelector('.el-table__body')
      if (next !== wrap) {
        wrap?.removeEventListener('scroll', fromBody)
        if (wrap) observer.unobserve(wrap)
        wrap = next
        if (wrap) { wrap.addEventListener('scroll', fromBody, { passive: true }); observer.observe(wrap) }
      }
      if (nextBody !== body) {
        if (body) observer.unobserve(body)
        body = nextBody
        if (body) observer.observe(body)
      }
      if (!wrap) return
      top.style.width = `${wrap.clientWidth}px`
      slider.max = String(Math.max(0, wrap.scrollWidth - wrap.clientWidth))
      top.style.display = Number(slider.max) > 1 ? 'block' : 'none'
      fromBody()
    }
    const schedule = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(sync) }
    slider.addEventListener('input', fromTop)
    observer.observe(el)
    instances.set(el, { schedule, dispose() {
      cancelAnimationFrame(frame); observer.disconnect(); wrap?.removeEventListener('scroll', fromBody)
      slider.removeEventListener('input', fromTop); top.remove()
    } })
    schedule()
  },
  updated(el) { instances.get(el)?.schedule() },
  beforeUnmount(el) { instances.get(el)?.dispose(); instances.delete(el) },
}
