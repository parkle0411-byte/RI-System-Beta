export const isStp = p => String(p?.classCode || '').trim().toUpperCase() === 'ST' || String(p?.classOfBusiness || '').trim().toLowerCase() === 'stock throughput'
const filled = value => typeof value === 'string' && value.trim().length > 0
const positive = value => value !== null && value !== '' && value !== undefined && Number.isFinite(Number(value)) && Number(value) > 0
export function stpIssues(p) {
  if (!isStp(p)) return []
  const out = [], add = (field, label) => out.push({field, label})
  if (!['QS', 'FACULTATIVE'].includes(String(p.reinsuranceStructure || '').toUpperCase())) add('reinsuranceStructure', 'Stock Throughput requires Quota Share')
  for (const [field,label] of [['conveyance','Conveyance'],['voyage','Voyage'],['limitOfLiability','Limit of Liability'],['reinsuredRetention','Reinsured’s Retention'],['expressWarranties','Express Warranties'],['conditionsPrecedent','Conditions Precedent'],['subjectivities','Subjectivities']]) if (!filled(p[field])) add(field,label)
  for (const [field,label] of [['riCommPct','Ceding Commission'],['taxPct','Cedant Tax']]) if (p[field] == null || p[field] === '') add(field,label)
  ;(p.reinsurers || []).forEach((r,i) => { if (/\bfacility\b/i.test(r?.name || '')) add(`reinsurers.${i}.name`, 'Facility is not available for Stock Throughput') })
  const hubs = Array.isArray(p.stpHubs) ? p.stpHubs : []
  if (!hubs.length) add('stpHubs', 'At least one HUB is required')
  hubs.forEach((r,i) => {
    for (const [key,label] of [['name','Location name'],['address','Address'],['currency','Currency']]) if (!filled(r?.[key])) add(`stpHubs.${i}.${key}`,`HUB ${i+1} ${label}`)
    if (!positive(r?.amount)) add(`stpHubs.${i}.amount`,`HUB ${i+1} Insured Amount must be greater than 0`)
  })
  const entries = Array.isArray(p.stpTurnover) ? p.stpTurnover : []
  if (!['combined','companies'].includes(p.stpTurnoverMode)) add('stpTurnoverMode','Choose an Estimated Turnover mode')
  if (!entries.length) add('stpTurnover','At least one Estimated Turnover entry is required')
  const names = new Set()
  entries.forEach((r,i) => {
    if (p.stpTurnoverMode === 'companies') {
      const n = String(r?.company || '').trim().toLowerCase()
      if (!n) add(`stpTurnover.${i}.company`,`Turnover ${i+1} Company`)
      else if (names.has(n)) add(`stpTurnover.${i}.company`,`Turnover ${i+1} Company must be unique`)
      names.add(n)
    }
    if (!filled(r?.currency)) add(`stpTurnover.${i}.currency`,`Turnover ${i+1} Currency`)
    if (!positive(r?.amount)) add(`stpTurnover.${i}.amount`,`Turnover ${i+1} Amount must be greater than 0`)
  })
  return out
}

// Turnover and hub values have no specified decimal precision; preserve the
// entered decimal places, and add by decimal digits instead of binary floats.
function decimalParts(value) {
  const n = Number(value)
  if (!Number.isFinite(n) || n < 0) return { digits: '0', scale: 0 }
  const match = String(n).match(/^(\d+)(?:\.(\d+))?(?:e([+-]?\d+))?$/i)
  const fraction = match[2] || '', exponent = Number(match[3] || 0)
  let digits = match[1] + fraction, scale = fraction.length - exponent
  if (scale < 0) { digits += '0'.repeat(-scale); scale = 0 }
  return { digits, scale }
}
function formatDigits(digits, scale) {
  let raw = String(digits).padStart(scale + 1, '0')
  const integer = (scale ? raw.slice(0, -scale) : raw).replace(/^0+(?=\d)/, '').replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  const fraction = scale ? raw.slice(-scale).replace(/0+$/, '') : ''
  return integer + (fraction ? '.' + fraction : '')
}
export function formatStpAmount(value) {
  const p = decimalParts(value)
  return formatDigits(p.digits, p.scale)
}
export function sumStpAmounts(values) {
  const parts = values.map(decimalParts)
  const scale = Math.max(0, ...parts.map(p => p.scale))
  const total = parts.reduce((sum,p) => sum + BigInt(p.digits) * 10n ** BigInt(scale - p.scale), 0n)
  return formatDigits(total.toString(), scale)
}
