// 按鈕點擊漣漪（2026-11-25 互動層）。全站只有一個 pointerdown 監聽，不改任何元件。
// 只在點擊當下暫時加上一個漣漪容器，動畫結束就移除；停用、文字／連結型按鈕與減少動態效果時不做。
const SELECTOR = '.el-button:not(.is-disabled):not(.is-loading):not(.is-link):not(.is-text):not([disabled])'
const DURATION = 560

export function installRipple() {
  if (typeof document === 'undefined') return
  document.addEventListener('pointerdown', event => {
    if (event.button !== 0) return
    if (typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const button = event.target instanceof Element ? event.target.closest(SELECTOR) : null
    if (!button) return
    const box = button.getBoundingClientRect()
    if (!box.width || !box.height) return
    const size = Math.max(box.width, box.height) * 2
    // 漣漪放在自己的外層容器裡裁切，不改按鈕本身的 class（按鈕是 Vue 管理的，重新繪製時會洗掉外加的 class）
    const holder = document.createElement('span')
    holder.className = 'ripple-wrap'
    holder.setAttribute('aria-hidden', 'true')
    const wave = document.createElement('span')
    wave.className = 'ripple'
    wave.style.cssText = `width:${size}px;height:${size}px;left:${event.clientX - box.left - size / 2}px;top:${event.clientY - box.top - size / 2}px`
    if (button.classList.contains('el-button--primary') || button.classList.contains('primary-button')) wave.classList.add('on-dark')
    holder.appendChild(wave)
    // 只有原本不是定位元素時才暫時設成 relative（inline style 不會被 Vue 的 class 重繪洗掉），避免改動浮動或固定位置的按鈕
    const wasStatic = getComputedStyle(button).position === 'static'
    if (wasStatic) button.style.position = 'relative'
    button.appendChild(holder)
    window.setTimeout(() => {
      holder.remove()
      if (wasStatic && !button.querySelector(':scope > .ripple-wrap')) button.style.position = ''
    }, DURATION + 40)
  }, { passive: true })
}
