// Shared by the Case form, readiness checks and document download checks.
export function sumItemKey(value) {
  return String(value ?? '').trim().replace(/\s+/g, ' ').toLowerCase()
}

export function allSumInsuredFacility(payload) {
  const named = (Array.isArray(payload?.reinsurers) ? payload.reinsurers : []).filter(row => String(row?.name ?? '').trim())
  return named.length > 0 && named.every(row => /\(Facility\)\s*$/i.test(String(row.name).trim()))
}

export function sumLocationIndex(row, count) {
  const raw = row?.locationIndex === undefined ? 0 : row.locationIndex
  if (raw == null || String(raw).trim() === '') return null
  const index = Number(raw)
  return Number.isInteger(index) && index >= 0 && index < count ? index : null
}

export function sumInsuredPlacementIssues(payload) {
  const rows = Array.isArray(payload?.sumInsured) ? payload.sumInsured : []
  const situations = Array.isArray(payload?.situations) ? payload.situations : []
  const facility = allSumInsuredFacility(payload), seen = new Set(), covered = new Set(), issues = []
  rows.forEach((row, index) => {
    const location = facility ? 0 : sumLocationIndex(row, situations.length)
    if (!facility) {
      if (location === null) issues.push({ field: `sumInsured.${index}.locationIndex`, label: `Sum insured ${index + 1} must be assigned to a valid Location`, kind: 'location' })
      else covered.add(location)
    }
    const name = sumItemKey(row?.category), key = JSON.stringify([location, name])
    if (name && location !== null) {
      if (seen.has(key)) issues.push({ field: `sumInsured.${index}.category`, label: `Sum insured ${index + 1} Interest insured must be unique within ${facility ? 'Facility items' : `Location ${location + 1}`}`, kind: 'duplicate' })
      seen.add(key)
    }
  })
  if (!facility) situations.forEach((_, index) => {
    if (!covered.has(index)) issues.push({ field: `sumInsuredLocation.${index}`, label: `Location ${index + 1} requires at least one Sum Insured entry`, kind: 'location' })
  })
  return issues
}

export function mergeFacilitySumItems(rows) {
  const result = [], groups = new Map()
  rows.forEach(row => {
    const name = sumItemKey(row.category)
    if (!name || !groups.has(name)) {
      const item = { ...row, category: String(row.category ?? '').trim(), locationIndex: null }
      result.push(item)
      if (name) groups.set(name, item)
      return
    }
    const item = groups.get(name), a = item.amount, b = row.amount
    item.amount = a != null && b != null && String(a).trim() && String(b).trim() && Number.isFinite(Number(a)) && Number.isFinite(Number(b)) ? Number(a) + Number(b) : null
  })
  return result
}

export function sumInsuredLimitWarning(payload) {
  const rows = Array.isArray(payload?.sumInsured) ? payload.sumInsured : []
  const rawLimit = payload?.limitOfLiability
  if (!rows.length || rawLimit == null || String(rawLimit).trim() === '' || !Number.isFinite(Number(rawLimit)) || Number(rawLimit) < 0
    || rows.some(row => row?.amount == null || String(row.amount).trim() === '' || !Number.isFinite(Number(row.amount)) || Number(row.amount) <= 0)) return null
  // Match the Word generator's item order and money formatting, including ties.
  const ordered = allSumInsuredFacility(payload) ? rows : rows.slice().sort((a, b) => {
    const index = row => Number.isInteger(Number(row.locationIndex)) && Number(row.locationIndex) >= 0 ? Number(row.locationIndex) : 0
    return index(a) - index(b)
  })
  const wordNumber = value => { const number = Number.parseFloat(value); return Number.isFinite(number) ? number : 0 }
  const total = ordered.reduce((sum, row) => sum + wordNumber(row.amount), 0)
  if (!Number.isFinite(total)) return null
  const currency = String(payload?.currency || '').trim().toUpperCase() || 'TWD'
  const decimals = currency === 'USD' ? 2 : 0
  const format = value => wordNumber(value).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
  const totalText = format(total), limitText = format(rawLimit)
  if (totalText === limitText) return null
  return { code: 'sum_insured_limit_mismatch', currency, total: totalText, limit: limitText,
    message: `Total Sum Insured (${currency} ${totalText}) differs from Limit of Liability (${currency} ${limitText}). You can continue.` }
}
