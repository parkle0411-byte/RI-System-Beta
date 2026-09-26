// 用前端真正使用的 src/alpha/caseCalculations.js 算同一批案件，與後端 totals.py 的結果逐欄比對
import { readFileSync } from 'node:fs'
import { RICaseCalculations } from '/src/alpha/caseCalculations.js'
const rows = JSON.parse(readFileSync(0, 'utf8'))
let bad = 0
const samples = []
for (const { case: c, totals } of rows) {
  const js = RICaseCalculations.totals(c)
  const diff = Object.keys(totals).filter((k) => js[k] !== totals[k])
  if (diff.length || Object.keys(js).length !== Object.keys(totals).length) {
    bad += 1
    if (samples.length < 3) samples.push({ diff, js, py: totals })
  }
}
console.log(JSON.stringify({ total: rows.length, bad, samples }))
