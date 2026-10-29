import { premiumMoney } from './lib/accounting.js'

function day(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const stamp = Date.parse(value + 'T00:00:00Z')
  return Number.isFinite(stamp) && new Date(stamp).toISOString().slice(0, 10) === value ? stamp : null
}

function monthsAfter(value, months) {
  const date = new Date(value), originalDay = date.getUTCDate()
  date.setUTCDate(1)
  date.setUTCMonth(date.getUTCMonth() + months)
  const last = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)).getUTCDate()
  date.setUTCDate(Math.min(originalDay, last))
  return date.getTime()
}

export function insuranceIssues(p) {
  if (!['QS', 'XOL'].includes(p?.reinsuranceStructure)) return []
  const issues = [], add = (field, label) => issues.push({field, label})
  const start = day(p.policyFrom), end = day(p.policyTo)
  if (start !== null && end !== null) {
    if (end <= start) add('policyTo', 'Expiration date must be later than Effective date.')
    else if (end > monthsAfter(start, 18)) add('policyTo', 'The complete insurance period must not exceed 18 calendar months.')
  }
  if (!p.parentTwRef) return issues
  const effective = day(p.endoEffectiveDate), context = p.endorsementSource || {}
  if (context.policyFrom && !(p.endoTypes || []).includes('Period') && (p.policyFrom !== context.policyFrom || p.policyTo !== context.policyTo || ['policyFromTime','policyToTime'].some(key => (p[key] || '12:00') !== (context[key] || '12:00')))) add('endoTypes', 'Select Period for an endorsement that changes the insurance period.')
  if (p.endoEffectiveDate && effective === null) add('endoEffectiveDate', 'Endorsement effective date must use YYYY-MM-DD.')
  if (effective !== null) {
    const from = day(context.policyFrom), to = day(context.policyTo), previous = day(context.previousEffectiveDate)
    if (!(p.endoTypes || []).includes('Period') && from !== null && to !== null && (effective < from || effective > to)) add('endoEffectiveDate', 'Endorsement effective date must be within the latest insurance period, including both boundary dates.')
    if (previous !== null && effective < previous) add('endoEffectiveDate', 'Endorsement effective date cannot be earlier than the preceding endorsement.')
  }
  return issues
}

export function markRenewalPremium(p, field) {
  if (!p.renewalPremiumBasis) return
  p.renewalPremiumManual = [...new Set([...(p.renewalPremiumManual || []), field])]
}

export function recomputeRenewal(p) {
  const basis = p.renewalPremiumBasis
  if (!basis || p.parentTwRef) return
  const from = day(p.policyFrom), to = day(p.policyTo)
  const days = from === null || to === null ? 0 : (to - from) / 86400000
  const manual = new Set([...(basis.manual || []), ...(p.renewalPremiumManual || [])])
  for (const [field, total] of Object.entries(basis.totals || {})) {
    if (manual.has(field)) continue
    let value = total !== null && days > 0 && basis.sourceDays > 0 ? premiumMoney(total / basis.sourceDays * days, p) : null
    const positiveOnly = field === 'originalPremium' || p.reinsuranceStructure === 'QS' && String(p.classOfBusiness || '').trim().toLowerCase() === 'commercial general liability'
    if (value !== null && (!Number.isFinite(value) || (positiveOnly ? value <= 0 : value < 0))) value = null
    if (field === 'originalPremium') p.originalPremium = value
    else {
      const index = Number(field.split('.')[1]), row = p.reinsurers?.[index]
      if (row) row.premium = String(row.name || '').trim().replace(/\s+/g,' ').toLowerCase() === basis.names[index] ? value : null
    }
    basis.auto[field] = value
  }
}
