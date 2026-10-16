// 2026-10-16：同一次登入中回到 Accounting 時，先顯示上次載入的清單，同時在背景重新載入。
// 只存在這個瀏覽器分頁的記憶體：重新整理、登出或換人登入就清掉，也不會給別的使用者看到。
import { watch } from 'vue'
import { auth } from '../auth'

let memory = null
watch(() => auth.principal?.id, () => { memory = null })   // 登出或換人登入

export function remember(body) {
  memory = auth.principal ? { owner: auth.principal.id, body, at: new Date() } : null
}

export function recall() {
  return memory && auth.principal && memory.owner === auth.principal.id ? memory : null
}
