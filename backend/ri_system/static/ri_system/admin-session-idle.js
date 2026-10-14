import { createIdleSession } from './session-idle.js'

const initial = document.getElementById('ri-idle-session-state')
if (initial) {
  let csrf = () => document.cookie.split('; ').find((v) => v.startsWith('csrftoken='))?.slice(10) || ''
  async function call(url, body) {
    const options = { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } }
    if (body) {
      if (!csrf()) await fetch('/api/auth/csrf', { credentials: 'same-origin', cache: 'no-store' })
      Object.assign(options, { method: 'POST', body: JSON.stringify(body), keepalive: true })
      options.headers['Content-Type'] = 'application/json'
      options.headers['X-CSRFToken'] = decodeURIComponent(csrf())
    }
    const response = await fetch(url, options)
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw Object.assign(new Error(data.message || 'The session could not be refreshed.'), { status: response.status, code: data.error })
    return data
  }
  const warning = document.createElement('dialog')
  warning.style.cssText = 'max-width:440px;border:1px solid #c5cbd3;border-radius:8px;padding:24px;color:#183247;background:#fff;z-index:10000'
  warning.innerHTML = '<h2>Session expiring</h2><p>You will be signed out in <strong data-countdown></strong> because of inactivity.</p><p>Unsaved changes will be lost.</p><p data-error style="color:#b91c1c"></p><button type="button" data-logout>Log out</button> <button type="button" data-continue>Continue using</button>'
  document.body.appendChild(warning)
  warning.addEventListener('cancel', (event) => event.preventDefault())
  const signIn = (reason) => window.location.replace('/login?redirect=' + encodeURIComponent(location.pathname + location.search) + (reason === 'idle' ? '&reason=idle' : ''))
  const tracker = createIdleSession({
    sendActivity: async (sessionId) => (await call('/api/auth/activity', { sessionId })).session,
    readStatus: async () => (await call('/api/auth/session')).session,
    onWarning(seconds) {
      if (seconds === null) { if (warning.open) warning.close(); return }
      warning.querySelector('[data-countdown]').textContent = Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0')
      if (!warning.open) warning.showModal()
    },
    onExpired: signIn,
    onSessionChanged: () => window.location.reload(),
  })
  warning.querySelector('[data-continue]').addEventListener('click', async () => {
    try { await tracker.continueUsing() } catch (error) { warning.querySelector('[data-error]').textContent = error.message }
  })
  warning.querySelector('[data-logout]').addEventListener('click', async () => {
    tracker.stop()
    try { await call('/api/auth/logout', {}) } finally { signIn('manual') }
  })
  tracker.start(JSON.parse(initial.textContent))
}
