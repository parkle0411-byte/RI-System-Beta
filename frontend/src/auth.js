import { reactive } from 'vue'
import { createIdleSession } from './sessionIdle'
import { api, ApiError, setPasswordChangeRequiredHandler, setUnauthorizedHandler, setSessionResponseHandler } from './api'

// 目前登入者與權限（來源：後端 /api/app-context，格式與 Alpha 相同）。
// 前端的權限判斷只影響「顯示什麼」；真正的權限檢查在後端，前端不能作為安全防線。
export const auth = reactive({
  ready: false,
  principal: null,
  auditLogRecordingEnabled: false,
  idleWarningSeconds: null,
})

let idleSession = null

export async function continueSession() { await idleSession?.continueUsing() }

export function can(permission) {
  return !!auth.principal && auth.principal.permissions.includes(permission)
}

export async function loadContext() {
  try {
    const data = await api('/api/app-context', { quiet401: true })
    auth.principal = data.principal
    auth.auditLogRecordingEnabled = data.auditLogRecordingEnabled === true
    idleSession?.start(data.session)
  } catch (e) {
    if (!(e instanceof ApiError) || ![401, 403].includes(e.status)) throw e
    auth.principal = null
    idleSession?.stop()
  } finally {
    auth.ready = true
  }
}

export async function login(username, password) {
  await api('/api/auth/csrf', { quiet401: true }) // 確保有 csrftoken cookie
  const data = await api('/api/auth/login', { method: 'POST', body: { username, password }, quiet401: true })
  auth.principal = data.principal
  auth.auditLogRecordingEnabled = data.auditLogRecordingEnabled === true
  idleSession?.start(data.session)
}

export async function logout() {
  idleSession?.stop()
  try {
    await api('/api/auth/logout', { method: 'POST', quiet401: true })
  } finally {
    auth.principal = null
  }
}

export async function changePassword(currentPassword, newPassword) {
  const data = await api('/api/auth/change-password', { method: 'POST', body: { currentPassword, newPassword } })
  if (data && data.principal) auth.principal = data.principal // mustChangePassword 會在這裡變回 false
}

// 任何 API 回 401（session 過期或被停用）時，清掉登入狀態；路由守衛會帶回登入頁。
export function installUnauthorizedHandler(router) {
  const signedOut = (reason) => {
    const target = router.currentRoute.value.fullPath
    idleSession?.stop()
    auth.principal = null
    if (router.currentRoute.value.name !== 'login') {
      router.replace({ name: 'login', query: { redirect: target, ...(reason === 'idle' ? { reason: 'idle' } : {}) } })
    }
  }
  idleSession = createIdleSession({
    sendActivity: async (sessionId) => (await api('/api/auth/activity', { method: 'POST', body: { sessionId }, quiet401: true, keepalive: true })).session,
    readStatus: async () => (await api('/api/auth/session', { quiet401: true })).session,
    onWarning: (seconds) => { auth.idleWarningSeconds = seconds },
    onExpired: signedOut,
    onSessionChanged: async () => { auth.principal = null; await loadContext(); router.replace('/') },
  })
  setSessionResponseHandler((state) => { if (auth.principal) idleSession.observe(state) })
  // 後端因為「必須先改密碼」拒絕業務 API 時（例如管理員剛重設了密碼），畫面也切到強制改密碼
  setPasswordChangeRequiredHandler(() => {
    if (auth.principal) auth.principal.mustChangePassword = true
  })
  setUnauthorizedHandler((code) => signedOut(code === 'SESSION_IDLE_TIMEOUT' || idleSession.isExpired() ? 'idle' : 'invalid'))
}
