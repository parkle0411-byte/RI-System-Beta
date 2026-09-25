// 密碼規則（與後端 settings.py 的 AUTH_PASSWORD_VALIDATORS 一致，兩邊要一起改）：
// 至少 8 個字元，且必須同時包含英文字母與數字。
export const PASSWORD_RULE_TEXT = '密碼至少需要 8 個字元，且必須同時包含英文字母與數字。'

// 回傳錯誤訊息；符合規則時回傳空字串。後端仍會再檢查一次，這裡只是讓使用者不用等伺服器就知道。
export function checkPassword(password) {
  const value = String(password || '')
  if (value.length < 8) return '密碼太短，必須至少 8 個字元。'
  if (!/[A-Za-z]/.test(value) || !/[0-9]/.test(value)) return '密碼必須同時包含英文字母與數字。'
  return ''
}
