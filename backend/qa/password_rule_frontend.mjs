// 用前端真正會用到的 passwordRule.js，對同一批密碼做檢查（供與後端結果比對）
import { readFileSync } from 'node:fs'
import { checkPassword } from '/src/passwordRule.js'
const vectors = JSON.parse(readFileSync('/qa/password_vectors.json', 'utf8'))
const out = {}
for (const v of vectors) out[v] = checkPassword(v) === ''
console.log(JSON.stringify(out))
