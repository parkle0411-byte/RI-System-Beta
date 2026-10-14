// Element Plus initializes these attributes at mount. Keep them aligned with
// the native input when disabled or numeric bounds change, without remounting.
function syncInputNumberAria(el) {
  const input = el.querySelector('input')
  if (!input) return
  input.setAttribute('aria-disabled', String(input.disabled))
  for (const [native, aria] of [['min', 'aria-valuemin'], ['max', 'aria-valuemax']]) {
    const value = input.getAttribute(native)
    if (value !== null && value.trim() !== '' && Number.isFinite(Number(value))) {
      input.setAttribute(aria, value)
    } else {
      input.removeAttribute(aria)
    }
  }
}

export default {
  mounted: syncInputNumberAria,
  updated: syncInputNumberAria,
}
