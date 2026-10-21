import { normalizeClauseCode, normalizeClauseList } from './constants'

// Clause MDM is the title authority. Older fixed-clause copies and saved Cases
// may keep the selected codes while their titles lag behind the Clause record.
export function resolveClauseTitles(clauses, records, caseData = {}) {
  const masters = Array.isArray(records) ? records : []
  const titles = new Map()
  const names = new Set((caseData.reinsurers || []).map(row => String(row?.name || '').trim().toLowerCase()))
  const selected = masters.filter(row => row.entityType === 'class' && row.name === caseData.classOfBusiness)
    .concat(masters.filter(row => row.entityType === 'reinsurer' && names.has(String(row.name || '').trim().toLowerCase())))
  for (const master of selected) {
    for (const row of normalizeClauseList(master.payload?.fixedClauses)) {
      if (!titles.has(row.code)) titles.set(row.code, row.title)
    }
  }
  for (const master of masters) {
    if (master.entityType !== 'clause') continue
    const code = normalizeClauseCode(master.code)
    const title = String(master.name || '').trim()
    if (code && title) titles.set(code, title)
  }
  return normalizeClauseList(clauses).map(row => ({ ...row, title: titles.get(row.code) || row.title }))
}
