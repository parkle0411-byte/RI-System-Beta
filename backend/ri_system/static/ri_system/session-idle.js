// Shared native browser controller; the same source serves the read-only Django admin.
// Only trusted pointer, keyboard, text and wheel/touch gestures report activity.
// Timers, focus, navigation, synthetic events and API polling never renew a session.
export function createIdleSession({ sendActivity, readStatus, onWarning, onExpired, onSessionChanged }) {
  let state = null
  let deadline = 0
  let timer = null
  let touchTimer = null
  let lastSent = 0
  let dirty = false
  let inFlight = null
  let checking = null
  let revision = 0
  let generation = 0
  const storagePrefix = 'ri-idle-session:'
  const gestures = ['pointerdown', 'keydown', 'input', 'wheel', 'touchmove']

  function stored() {
    try { return JSON.parse(localStorage.getItem(storagePrefix + state.id) || 'null') } catch { return null }
  }
  function publish(type) {
    if (!state) return
    try {
      localStorage.setItem(storagePrefix + state.id, JSON.stringify({ type, state, deadline, at: Date.now() }))
    } catch { /* Server checks and this tab's timer remain effective when storage is unavailable. */ }
  }
  function clearTimers() {
    clearTimeout(timer); clearTimeout(touchTimer)
    timer = touchTimer = null
  }
  function stop() {
    generation += 1
    state = null
    dirty = false
    clearTimers()
    onWarning(null)
  }
  function finish(reason = 'idle') {
    if (!state) return
    publish('expired')
    stop()
    onExpired(reason)
  }
  function schedule() {
    clearTimeout(timer)
    if (!state) return
    const remaining = deadline - Date.now()
    if (remaining <= 0) {
      verifyDeadline()
      return
    }
    const warning = state.warningSeconds * 1000
    if (remaining <= warning) {
      onWarning(Math.ceil(remaining / 1000))
      timer = setTimeout(schedule, Math.min(1000, remaining))
    } else {
      onWarning(null)
      timer = setTimeout(schedule, remaining - warning)
    }
  }
  function accept(next, nextDeadline, broadcast = true) {
    if (!state || !next || next.id !== state.id) return false
    if (Number(next.expiresAt) < Number(state.expiresAt)) return false
    state = { ...next }
    deadline = nextDeadline ?? (Date.now() + next.expiresAt - next.serverNow)
    if (broadcast) publish('state')
    schedule()
    return true
  }
  async function verifyDeadline() {
    if (!state || checking) return checking
    const id = state.id
    const current = generation
    checking = (async () => {
      try {
        const next = await readStatus()
        if (!state || generation !== current) return
        if (next.id !== id) {
          stop()
          onSessionChanged(next)
        } else {
          // A different tab may have renewed it; re-check the server before clearing any screen.
          accept(next)
        }
      } catch (error) {
        if (state && generation === current) finish(error.status === 403 ? 'invalid' : 'idle')
      } finally { checking = null; if (state && generation === current) schedule() }
    })()
    return checking
  }
  async function flush(force = false) {
    clearTimeout(touchTimer); touchTimer = null
    if (!state || (!dirty && !force)) return
    if (deadline <= Date.now()) {
      await verifyDeadline()
      if (!state) return
    }
    if (inFlight) return inFlight
    const id = state.id
    const current = generation
    const sentRevision = revision
    lastSent = Date.now()
    inFlight = (async () => {
      try {
        const next = await sendActivity(id)
        if (!state || generation !== current) return
        if (next.id !== id) {
          stop(); onSessionChanged(next)
          return
        }
        accept(next)
        dirty = revision !== sentRevision
      } catch (error) {
        if (state && generation === current) {
          if (error.status === 401 || error.status === 403) finish(error.status === 403 ? 'invalid' : 'idle')
          else if (error.code === 'SESSION_CHANGED') await verifyDeadline()
          dirty = revision !== sentRevision
          // A failed request never extends the authoritative expiry deadline or causes unattended retries.
        }
        throw error
      } finally {
        inFlight = null
        if (dirty && state && generation === current) queueTouch()
      }
    })()
    return inFlight
  }
  function queueTouch() {
    if (!state || touchTimer !== null) return
    const interval = Math.min(60000, Math.max(1000, state.timeoutSeconds * 250))
    const wait = Math.max(0, lastSent + interval - Date.now())
    touchTimer = setTimeout(() => { touchTimer = null; flush().catch(() => {}) }, wait)
  }
  function activity(event) {
    if (!state || !event.isTrusted) return
    dirty = true
    revision += 1
    queueTouch()
  }
  function wake() {
    if (!state) return
    const item = stored()
    if (item?.type === 'state' && item.state?.id === state.id) accept(item.state, item.deadline, false)
    // Browser sleep and clock changes must be checked without counting focus as activity.
    verifyDeadline()
  }
  function visibility() {
    if (document.visibilityState === 'hidden' && dirty) flush(true).catch(() => {})
    else wake()
  }
  function storage(event) {
    if (!state || event.key !== storagePrefix + state.id || !event.newValue) return
    try {
      const item = JSON.parse(event.newValue)
      if (item.type === 'state') accept(item.state, item.deadline, false)
      else if (item.type === 'expired' && item.state.expiresAt >= state.expiresAt) verifyDeadline()
    } catch { /* An invalid storage value cannot change the server session. */ }
  }
  for (const event of gestures) window.addEventListener(event, activity, { capture: true, passive: true })
  window.addEventListener('storage', storage)
  window.addEventListener('focus', wake)
  document.addEventListener('visibilitychange', visibility)
  window.addEventListener('pagehide', () => { if (dirty) flush(true).catch(() => {}) })

  return {
    start(next) {
      if (!next?.id || !Number.isFinite(next.expiresAt) || !Number.isFinite(next.serverNow)) return
      if (state?.id === next.id) { accept(next); return }
      stop()
      state = { ...next }
      lastSent = 0
      const saved = stored()
      if (saved?.type === 'state' && saved.state?.expiresAt > next.expiresAt) accept(saved.state, saved.deadline, false)
      else accept(next)
    },
    observe(next) {
      if (!state || !next?.id) return
      if (state.id === next.id) accept(next)
      else { stop(); onSessionChanged(next) }
    },
    async continueUsing() { dirty = true; revision += 1; return flush(true) },
    stop,
    isExpired() { return !!state && deadline <= Date.now() },
  }
}
