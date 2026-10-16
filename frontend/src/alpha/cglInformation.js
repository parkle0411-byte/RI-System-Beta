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
  return String(payload?.classOfBusiness || '').trim().toLowerCase() === 'commercial general liability'
    && ['', 'QS', 'XOL', 'FACULTATIVE'].includes(String(payload?.reinsuranceStructure || '').trim().toUpperCase())
    && !(payload?.reinsurers || []).some(row => /\(Facility\)\s*$/i.test(String(row?.name || '').trim())
      || String(row?.name || '').toLowerCase().includes('swiss re asia')
      || String(row?.foreignBroker || '').toLowerCase().includes('pws'))
}
export function cglInformationIssues(payload) {
  if (!isStandardCgl(payload)) return []
  const info = payload?.cglInformation || {}
  const issues = []
  const add = (key, label) => issues.push({ field: 'cglInformation.' + key, label })
  const filled = value => value != null && String(value).trim() !== ''
  if (!CGL_POLICY_FORMS.includes(info.policyForm)) add('policyForm', 'Policy Form')
  if (info.policyForm === 'Claims-Made Form') {
    const value = info.retroactiveDate
    const date = /^\d{4}-\d{2}-\d{2}$/.test(value || '') ? new Date(value + 'T00:00:00Z') : null
    if (!date || Number.isNaN(date.getTime()) || date.getUTCFullYear() < 100 || date.toISOString().slice(0, 10) !== value) add('retroactiveDate', 'Retroactive Date')
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
  return issues
}

export function cglInformationRows(payload) {
  const info = payload?.cglInformation || {}
  const rows = [{ label: 'Policy Form', value: info.policyForm || '—' }]
  if (info.policyForm === 'Claims-Made Form') {
    rows.push({ label: 'Retroactive Date', value: info.retroactiveDate || '—' })
    rows.push({ label: 'Extended Reporting Period', value: info.extendedReportingApplies === 'applicable' ? info.extendedReportingPeriod || '—' : info.extendedReportingApplies === 'notApplicable' ? 'Not applicable' : '—' })
  }
  rows.push({ label: 'Territorial / Jurisdiction Limits', value: info.territorialLimits === 'Other' ? info.territorialOther || '—' : info.territorialLimits || '—' },
    { label: 'Insured’s Business', value: info.insuredBusiness || '—' }, { label: 'Insured’s Products', value: info.insuredProducts || '—' },
    { label: 'Estimated Turnover', value: (info.estimatedTurnover || []).map(row => `${row.region || '—'} · ${row.currency || '—'} ${row.amount == null ? '—' : Number(row.amount).toLocaleString('en-US', { maximumFractionDigits: 20 })}`).join('\n') || '—' },
    { label: 'Insured’s Website', value: info.insuredWebsite || '—' })
  return rows
}
