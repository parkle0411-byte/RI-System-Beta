import { newCgl, businessText, placingExtraIssues } from './placingRules'
import { swissCglScope } from './swissCgl'
import { retroactiveIssues, retroactiveText } from './cglRetroactive'
import { recallScope } from './productRecall'

export const CGL_POLICY_FORMS = ['Occurrence Form', 'Claims-Made Form']
export const CGL_TERRITORIES = ['Worldwide including USA/Canada', 'Worldwide excluding USA/Canada', 'USA/Canada Only', 'Other']
export const CGL_CURRENCIES = ['TWD', 'USD', 'EUR', 'JPY', 'GBP', 'HKD', 'MYR']
const APPLICABILITY = ['notApplicable', 'applicable']
export function emptyCglInformation() {
  return { policyForm: '', retroactiveDate: '', extendedReportingApplies: '', extendedReportingPeriod: '',
    territorialLimits: '', territorialOther: '', insuredBusiness: '', insuredProducts: '', estimatedTurnover: [],
    insuredWebsite: '', specialAgreementApplies: '' }
}
export function isStandardCgl(payload) {
  if (swissCglScope(payload)) return true
  return String(payload?.classOfBusiness || '').trim().toLowerCase() === 'commercial general liability'
    && ['', 'QS', 'XOL', 'FACULTATIVE'].includes(String(payload?.reinsuranceStructure || '').trim().toUpperCase())
    && !(payload?.reinsurers || []).some(row => /\(Facility\)\s*$/i.test(String(row?.name || '').trim())
      || String(row?.name || '').toLowerCase().includes('swiss re asia')
      || (String(row?.foreignBroker || '').toLowerCase().includes('pws') && !['QS', 'FACULTATIVE'].includes(String(payload?.reinsuranceStructure || '').trim().toUpperCase())))
}
export function cglInformationIssues(payload) {
  if (!isStandardCgl(payload) && !recallScope(payload)) return []
  const info = payload?.cglInformation || {}
  const issues = []
  const add = (key, label) => issues.push({ field: 'cglInformation.' + key, label })
  const filled = value => value != null && String(value).trim() !== ''
  if (!CGL_POLICY_FORMS.includes(info.policyForm)) add('policyForm', 'Policy Form')
  if (info.policyForm === 'Claims-Made Form') {
    issues.push(...retroactiveIssues(info))
    if (!APPLICABILITY.includes(info.extendedReportingApplies)) add('extendedReportingApplies', 'Extended Reporting Period applicability')
    if (info.extendedReportingApplies === 'applicable' && !filled(info.extendedReportingPeriod)) add('extendedReportingPeriod', 'Extended Reporting Period — period and description')
  }
  if (!CGL_TERRITORIES.includes(info.territorialLimits)) add('territorialLimits', 'Territorial / Jurisdiction Limits')
  else if (info.territorialLimits === 'Other' && !filled(info.territorialOther)) add('territorialOther', 'Territorial / Jurisdiction Limits — Other')
  for (const [key, label] of [['insuredBusiness', 'Insured’s Business'], ['insuredProducts', 'Insured’s Products']]) {
    if (!filled(info[key])) add(key, label)
  }
  if (!Array.isArray(info.estimatedTurnover) || !info.estimatedTurnover.length) add('estimatedTurnover', 'Estimated Turnover — at least one entry')
  else info.estimatedTurnover.forEach((row, index) => {
    const prefix = `estimatedTurnover.${index}.`
    if (!filled(row?.region)) add(prefix + 'region', `Estimated Turnover ${index + 1} Region`)
    if (!CGL_CURRENCIES.includes(row?.currency)) add(prefix + 'currency', `Estimated Turnover ${index + 1} Currency`)
    if (!filled(row?.amount) || !Number.isFinite(Number(row.amount)) || Number(row.amount) < 0) add(prefix + 'amount', `Estimated Turnover ${index + 1} Amount`)
  })
  if (!APPLICABILITY.includes(info.specialAgreementApplies)) add('specialAgreementApplies', 'Special Agreement applicability')
  else if (info.specialAgreementApplies === 'applicable' && !filled(payload.specialAgreement)) issues.push({ field: 'specialAgreement', label: 'Special Agreement' })
  if (recallScope(payload)) {
    const selected = info.insuredBusinessSelections || []
    if (!selected.length) add('insuredBusinessSelections', 'Insured’s Business — select at least one available option')
    if (selected.includes('Other') && !filled(info.insuredBusinessOther)) add('insuredBusinessOther', 'Insured’s Business — Other')
    ;(info.estimatedTurnover || []).forEach((row, i) => {
      if (!['USA/Canada', 'Rest of World', 'Other'].includes(row.region)) add(`estimatedTurnover.${i}.region`, 'Turnover Region must use an available option')
      if (row.region === 'Other' && !filled(row.regionOther)) add(`estimatedTurnover.${i}.regionOther`, 'Turnover Region — Other')
    })
  }
  return issues.filter(i => !((newCgl(payload) || recallScope(payload)) && i.field === 'cglInformation.insuredBusiness')).concat(newCgl(payload) ? placingExtraIssues(payload).filter(i => i.field.startsWith('cglInformation.')) : [])
}

export function cglInformationRows(payload) {
  const info = payload?.cglInformation || {}
  const rows = [{ label: 'Policy Form', value: info.policyForm || '—' }]
  if (info.policyForm === 'Claims-Made Form') {
    rows.push({ label: 'Retroactive Date', value: retroactiveText(info) || '—' })
    rows.push({ label: 'Extended Reporting Period', value: info.extendedReportingApplies === 'applicable' ? info.extendedReportingPeriod || '—' : info.extendedReportingApplies === 'notApplicable' ? 'Not applicable' : '—' })
  }
  rows.push({ label: 'Territorial / Jurisdiction Limits', value: info.territorialLimits === 'Other' ? info.territorialOther || '—' : info.territorialLimits || '—' },
    { label: 'Insured’s Business', value: (newCgl(payload) || recallScope(payload) ? businessText(info) : info.insuredBusiness) || '—' }, { label: 'Insured’s Products', value: info.insuredProducts || '—' },
    { label: 'Estimated Turnover', value: (info.estimatedTurnover || []).map(row => `${((newCgl(payload) || recallScope(payload)) && row.region === 'Other' ? row.regionOther : row.region) || '—'} · ${row.currency || '—'} ${row.amount == null ? '—' : Number(row.amount).toLocaleString('en-US', { maximumFractionDigits: 20 })}`).join('\n') || '—' },
    { label: 'Insured’s Website', value: info.insuredWebsite || '—' })
  return rows
}

// Cover notes group turnover by its original currency; never convert it using FX.
// This formatter is deliberately separate from the information summary on screen.
export function cglTurnoverDocumentText(payload) {
  const entries = Array.isArray(payload?.cglInformation?.estimatedTurnover) ? payload.cglInformation.estimatedTurnover : []
  const groups = new Map()
  for (const row of entries) {
    const currency = String(row?.currency || '').trim().toUpperCase()
    if (!currency) continue
    if (!groups.has(currency)) groups.set(currency, [])
    groups.get(currency).push(row)
  }
  const preferred = String(payload?.currency || '').trim().toUpperCase()
  const currencies = [...groups.keys()].sort((a, b) => a === preferred ? -1 : b === preferred ? 1 : a.localeCompare(b, 'en'))
  const format = value => Number(value).toLocaleString('en-US', { maximumFractionDigits: 20 })
  const detail = row => `${((newCgl(payload) || recallScope(payload)) && row.region === 'Other' ? row.regionOther : row.region) || '—'} · ${String(row.currency).toUpperCase()} ${row.amount == null ? '—' : format(row.amount)}`
  if (entries.length === 1 && currencies.length === 1) return detail(entries[0])
  return currencies.flatMap(currency => {
    const rows = groups.get(currency)
    // Turnover uses at most the input's decimal precision, not floating point noise.
    const total = rows.reduce((sum, row) => sum + Number(row.amount || 0), 0)
    const precision = Math.min(20, Math.max(0, ...rows.map(row => (String(row.amount ?? '').split('.')[1] || '').length)))
    const rounded = Number(total.toFixed(precision))
    return [`Total · ${currency} ${format(rounded)}`, ...rows.map(detail)]
  }).join('\n') || '—'
}

export function initializeCglAggregate(p) {
  if (!isStandardCgl(p)) return
  if (!['auto','manual'].includes(p.cglAggregateMode)) p.cglAggregateMode = p.aggregateLimit == null || p.aggregateLimit === '' || Number(p.aggregateLimit) === 0 ? 'auto' : 'manual'
  if (p.cglAggregateMode === 'auto') p.aggregateLimit = p.limitOfLiability ?? null
}
export function cglAggregateIssues(p) {
  return isStandardCgl(p) && (p.aggregateLimit == null || String(p.aggregateLimit).trim() === '' || !Number.isFinite(Number(p.aggregateLimit)) || Number(p.aggregateLimit) <= 0)
    ? [{field:'aggregateLimit', label:'Aggregate Limit must be greater than 0'}] : []
}
