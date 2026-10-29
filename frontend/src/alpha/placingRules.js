export const PLACING_RULES_VERSION = 'placing-qs-20261028-v1'
export const BUSINESS_OPTIONS = ['Manufacturer', 'Distributor', 'Importer', 'Exporter', 'Other']
export const REGION_OPTIONS = ['USA/Canada', 'Rest of World', 'Other']
export const placingRulesEnabled = p => p?.placingRulesVersion === PLACING_RULES_VERSION && p?.reinsuranceStructure === 'QS' && ['Property', 'Commercial General Liability'].includes(p?.classOfBusiness)
export const newCgl = p => placingRulesEnabled(p) && p.classOfBusiness === 'Commercial General Liability'
export const ordinaryPlacement = p => !(p?.reinsurers || []).some(r => r?.name) || (p?.reinsurers || []).some(r => r?.name && !/\(Facility\)\s*$/i.test(r.name))
export const propertyExtraFields = p => placingRulesEnabled(p) && p.classOfBusiness === 'Property' && ordinaryPlacement(p)
export const businessText = info => (info?.insuredBusinessSelections || []).map(x => x === 'Other' ? info.insuredBusinessOther || '' : x).join('\n')
const filled = x => x != null && String(x).trim() !== ''

export function placingExtraIssues(p) {
  if (!placingRulesEnabled(p)) return []
  const issues = []
  const add = (field, label) => issues.push({ field, label })
  if (p.classOfBusiness === 'Property' && !filled(p.basisOfValuation)) add('basisOfValuation', 'Basis of Valuation')
  if (newCgl(p)) {
    if (!filled(p.deductibles) && !filled(p.selfInsuredRetention)) add('deductibles', 'Complete Deductibles or Self-Insured Retention.')
    const info = p.cglInformation || {}
    if (!Array.isArray(info.insuredBusinessSelections) || !info.insuredBusinessSelections.length || info.insuredBusinessSelections.some(x => !BUSINESS_OPTIONS.includes(x))) add('cglInformation.insuredBusinessSelections', 'Insured’s Business — select at least one available option')
    if (info.insuredBusinessSelections?.includes('Other') && !filled(info.insuredBusinessOther)) add('cglInformation.insuredBusinessOther', 'Insured’s Business — Other')
    if (info.businessLegacyText && !info.businessLegacyConfirmed) add('cglInformation.businessLegacyConfirmed', 'Confirm the inherited Insured’s Business text.')
    ;(info.estimatedTurnover || []).forEach((r, i) => {
      if (!REGION_OPTIONS.includes(r.region)) add(`cglInformation.estimatedTurnover.${i}.region`, 'Turnover Region must use an available option.')
      if (r.region === 'Other' && !filled(r.regionOther)) add(`cglInformation.estimatedTurnover.${i}.regionOther`, 'Turnover Region — Other')
      if (r.legacyRegionText && !r.legacyRegionConfirmed) add(`cglInformation.estimatedTurnover.${i}.legacyRegionConfirmed`, 'Confirm the inherited Turnover Region text.')
    })
  }
  return issues
}

export function adjustClientIssues(p, issues, labels = false) {
  if (!placingRulesEnabled(p)) return issues
  const filtered = issues.filter(x => {
    const label = typeof x === 'string' ? x : x.label || ''
    if (/^Aggregate Limit/.test(label) && Number(p.aggregateLimit) === 0) return false
    if (/Reinsured[’']s Retention/i.test(label)) return false
    if (newCgl(p) && (/^Deductibles$/.test(label) || /^Interest$/.test(label) || /^Principal Address(?: \d+)?$/.test(label))) return false
    return true
  })
  return filtered.concat(placingExtraIssues(p).map(x => labels ? x.label : { ...x, section: 'information' }))
}

export function shareClientIssues(p, baseline = null) {
  const issues = []; let total = 0n
  const inherited = p.parentTwRef ? p.endorsementSource?.reinsurers : null
  ;(p.reinsurers || []).forEach((row, i) => {
    if (!filled(row.sharePct)) return
    const input = String(row.sharePct), n = Number(input)
    const raw = /e/i.test(input) && Number.isFinite(n) && Number(n.toFixed(8)) === n ? n.toFixed(8) : input
    const fixed = inherited?.[i] || baseline?.reinsurers?.[i]
    const historical = fixed && (inherited || !placingRulesEnabled(baseline)) && fixed.name === row.name && Number(fixed.sharePct) === n
    const match = raw.match(/^(\d+)(?:\.(\d{1,8}))?$/)
    if (!historical && (!match || !Number.isFinite(n) || n <= 0 || n > 100)) issues.push({ field: `reinsurers.${i}.sharePct`, label: 'Order Hereon must be greater than 0, at most 100%, with at most 8 decimal places.' })
    if (match) total += BigInt(match[1]) * 100000000n + BigInt((match[2] || '').padEnd(8, '0'))
  })
  if (total > 10000000000n) issues.push({ field: 'reinsurers', label: 'Total Order Hereon must not exceed 100%.' })
  return issues
}
