import { reactive } from 'vue'
import { api, ApiError, setPasswordChangeRequiredHandler, setUnauthorizedHandler } from './api'

// 目前登入者與權限（來源：後端 /api/app-context，格式與 Alpha 相同）。
// 前端的權限判斷只影響「顯示什麼」；真正的權限檢查在後端，前端不能作為安全防線。
export const auth = reactive({
  ready: false,
  principal: null,
})

export function can(permission) {
  return !!auth.principal && auth.principal.permissions.includes(permission)
}

export async function loadContext() {
  try {
    const data = await api('/api/app-context', { quiet401: true })
    auth.principal = data.principal
  } catch (e) {
    if (!(e instanceof ApiError) || ![401, 403].includes(e.status)) throw e
    auth.principal = null
  } finally {
    auth.ready = true
  }
}

export async function login(username, password) {
  await api('/api/auth/csrf', { quiet401: true }) // 確保有 csrftoken cookie
  const data = await api('/api/auth/login', { method: 'POST', body: { username, password }, quiet401: true })
  auth.principal = data.principal
}

export async function logout() {
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
  // 後端因為「必須先改密碼」拒絕業務 API 時（例如管理員剛重設了密碼），畫面也切到強制改密碼
  setPasswordChangeRequiredHandler(() => {
    if (auth.principal) auth.principal.mustChangePassword = true
  })
  setUnauthorizedHandler(() => {
    auth.principal = null
    if (router.currentRoute.value.name !== 'login') {
      router.push({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } })
    }
  })
}
