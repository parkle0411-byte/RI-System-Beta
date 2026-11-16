// Accounting server paging parity, browser half (2026-11-17). Reads qa/accounting_pages_backend.py output on stdin,
// rebuilds the rows exactly as the Accounting screen used to (accountingRows.js + the former history merge), filters and
// sorts them with the screen's own accountingList.js, and compares every server page, its total, registrations,
// correction histories and the dropdown options.
// The screen's modules import without file extensions (resolved by Vite); they are copied unchanged except for that.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
const files = ['alpha/accountingRows.js', 'alpha/transactionNumber.js', 'alpha/transactionParty.js', 'alpha/manualTwRef.js', 'views/accountingCash.js', 'views/accountingList.js']
for (const file of files) {
  mkdirSync('/tmp/acct/' + file.split('/')[0], { recursive: true })
  writeFileSync('/tmp/acct/' + file, readFileSync('/src/' + file, 'utf8').replace(/from '(\.\.?\/[^']+?)(?<!\.js)'/g, "from '$1.js'"))
}
const { accountingRows } = await import('/tmp/acct/alpha/accountingRows.js')
const { listRows, partyOptions, SERVER_PAGE_SIZE } = await import('/tmp/acct/views/accountingList.js')

const raw = readFileSync(0, 'utf8')
const data = JSON.parse(raw.slice(raw.indexOf('ACCOUNTING-PAGES-BEGIN') + 22, raw.indexOf('ACCOUNTING-PAGES-END')))
const canon = value => JSON.stringify(value, (key, v) => v && typeof v === 'object' && !Array.isArray(v) ? Object.fromEntries(Object.keys(v).sort().map(k => [k, v[k]])) : v)

// Former Accounting.vue apply() + mergeHistory()
let rows = accountingRows(data.open)
const historyIds = new Set((data.history.cashBatches || []).map(x => x.batchId))
rows = [...rows.filter(r => !r.legacyHistorical), ...accountingRows({ transactionRows: data.history.transactionRows || [] })]
const batches = [...(data.open.cashBatches || []).filter(x => !historyIds.has(x.batchId)), ...(data.history.cashBatches || [])]
const caseHistories = { ...(data.open.caseHistories || {}), ...(data.history.caseHistories || {}) }
const currencies = [...new Set([...(data.open.currencies || []), ...(data.history.currencies || [])])].sort()
const collator = new Intl.Collator()

const problems = []
const expectOptions = { ...partyOptions(rows), currencies }
if (canon(expectOptions) !== canon(data.options)) problems.push({ what: 'options', expected: expectOptions, server: data.options })
let pagesCompared = 0, rowsCompared = 0
for (const check of data.checks) {
  const expected = listRows(rows, check.tab, check.filters, check.text, data.now, collator)
  for (const [number, page] of Object.entries(check.pages)) {
    pagesCompared += 1
    const n = Number(number)
    const want = expected.slice((n - 1) * SERVER_PAGE_SIZE, n * SERVER_PAGE_SIZE)
    const label = `${check.tab} page ${n} ${canon({ filters: check.filters, text: check.text })}`
    if (page.total !== expected.length) problems.push({ what: 'total', label, expected: expected.length, server: page.total })
    if (page.pageSize !== SERVER_PAGE_SIZE || page.page !== n) problems.push({ what: 'paging', label, server: [page.page, page.pageSize] })
    if (page.rows.length !== want.length) { problems.push({ what: 'row count', label, expected: want.length, server: page.rows.length }); continue }
    want.forEach((row, i) => {
      rowsCompared += 1
      if (canon(row) !== canon(page.rows[i])) problems.push({ what: 'row', label, index: i, expected: [row.key, row.txNo], server: [page.rows[i].key, page.rows[i].txNo],
        firstDifference: Object.keys({ ...row, ...page.rows[i] }).filter(k => canon(row[k]) !== canon(page.rows[i][k])).slice(0, 5) })
    })
    const wanted = new Set(want.flatMap(r => (r.entries || []).map(e => e.batchId || e.offsetId || 'legacy:' + e.id)))
    const expectBatches = []
    for (const id of wanted) { const b = batches.find(x => x.batchId === id); if (b) expectBatches.push(canon(b)) }
    if (canon(expectBatches.sort()) !== canon(page.cashBatches.map(canon).sort())) problems.push({ what: 'cashBatches', label, expected: expectBatches.length, server: page.cashBatches.length })
    const uids = new Set(want.map(r => r.caseUid))
    const expectHistories = Object.fromEntries(Object.entries(caseHistories).filter(([uid]) => uids.has(uid)))
    if (canon(expectHistories) !== canon(page.caseHistories)) problems.push({ what: 'caseHistories', label })
  }
}
console.log(JSON.stringify({ rows: rows.length, checks: data.checks.length, pagesCompared, rowsCompared, problems: problems.length, samples: problems.slice(0, 8) }))
