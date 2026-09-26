// 所有 API 呼叫都經過這裡：
//  - 寫入請求自動帶 X-CSRFToken（先向 /api/auth/csrf 取得 cookie）
//  - 後端錯誤統一轉成 ApiError（帶 status 與 code，code 與 Alpha 相同）
//  - 401 時通知登入狀態（回到登入頁），不由各頁面各自處理

export class ApiError extends Error {
  constructor(message, status, code) {
    super(message)
    this.status = status
    this.code = code
  }
}

let onUnauthorized = () => {}
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn
}

let onPasswordChangeRequired = () => {}
export function setPasswordChangeRequiredHandler(fn) {
  onPasswordChangeRequired = fn
}

function readCookie(name) {
  const hit = document.cookie.split('; ').find((row) => row.startsWith(name + '='))
  return hit ? decodeURIComponent(hit.slice(name.length + 1)) : ''
}

async function csrfToken() {
  let token = readCookie('csrftoken')
  if (!token) {
    await fetch('/api/auth/csrf', { credentials: 'same-origin', cache: 'no-store' })
    token = readCookie('csrftoken')
  }
  return token
}

export async function api(url, { method = 'GET', body, quiet401 = false } = {}) {
  const headers = { Accept: 'application/json' }
  const init = { method, headers, credentials: 'same-origin', cache: 'no-store' }
  if (method !== 'GET' && method !== 'HEAD') {
    headers['Content-Type'] = 'application/json'
    headers['X-CSRFToken'] = await csrfToken()
    init.body = JSON.stringify(body ?? {})
  }
  const res = await fetch(url, init)
  let data = null
  try {
    data = await res.json()
  } catch {
    data = null
  }
  if (!res.ok) {
    if (res.status === 401 && !quiet401) onUnauthorized()
    if (res.status === 403 && data && data.error === 'PASSWORD_CHANGE_REQUIRED') onPasswordChangeRequired()
    const message =
      (data && (data.message || data.detail)) ||
      (res.status === 429 ? '嘗試次數過多，請稍後再試。' : `HTTP ${res.status}`)
    throw new ApiError(message, res.status, data && (data.error || data.code))
  }
  return data
}

// Alpha 的畫面程式直接用 fetch() 並自己讀 response.ok／response.json()。
// 為了讓移植的程式碼與 Alpha 逐行對得上，這裡提供同樣介面的 apiFetch()：
// 回傳原本的 Response；另外補上 VM 需要的 CSRF、同源 cookie，以及 401／強制改密碼的通知。
export async function apiFetch(url, options = {}) {
  const method = (options.method || 'GET').toUpperCase()
  const headers = { ...(options.headers || {}) }
  if (method !== 'GET' && method !== 'HEAD') headers['X-CSRFToken'] = await csrfToken()
  const response = await fetch(url, { cache: 'no-store', ...options, method, headers, credentials: 'same-origin' })
  if (response.status === 401) onUnauthorized()
  if (response.status === 403) {
    const body = await response.clone().json().catch(() => null)
    if (body && body.error === 'PASSWORD_CHANGE_REQUIRED') onPasswordChangeRequired()
  }
  return response
}
