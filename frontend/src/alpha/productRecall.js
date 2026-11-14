export const RECALL_EVENTS = ['Defect', 'Malicious Product Tampering', 'Product Extortion', 'Government Recall']
export const RECALL_LOSSES = ['First Party Recall Costs', 'Third Party Recall Costs', 'Consultant and Advisor Costs', 'Extortion Costs']
export const recallScope = p => String(p?.classOfBusiness || '').trim().toLowerCase() === 'product recall' && ['QS', 'FACULTATIVE'].includes(String(p?.reinsuranceStructure || '').toUpperCase())
export const claimCurrencyScope = p => recallScope(p) || String(p?.classOfBusiness || '').trim().toLowerCase() === 'stock throughput' || String(p?.classOfBusiness || '').trim().toLowerCase() === 'commercial general liability' && ['QS', 'FACULTATIVE'].includes(String(p?.reinsuranceStructure || '').toUpperCase()) && !(p?.reinsurers || []).some(row => /\bfacility\b/i.test(String(row?.name || '')) && !/swiss re asia/i.test(String(row?.name || '')))
export function initialRecall() {
  return {
    choiceOfLaw: 'This (re)insurance shall be governed by and construed in according with the law of Republic of China, Taiwan and the each party agrees to submit to the exclusive jurisdiction of the Courts of the Republic of China, Taiwan.',
    events: RECALL_EVENTS.map((name, i) => ({ id: `event-${i + 1}`, name, selected: true, fixed: true })),
    losses: RECALL_LOSSES.map((name, i) => ({ id: `loss-${i + 1}`, name, selected: true, fixed: true, amount: null })),
    additionalSublimits: []
  }
}

export function productRecallIssues(p) {
  if (!recallScope(p)) return []
  const issues = [], risk = p.productRecall || {}, add = (field, label) => issues.push({ field, label })
  const filled = value => value != null && String(value).trim() !== ''
  const number = value => filled(value) && Number.isFinite(Number(value)) ? Number(value) : null
  const limit = number(p.limitOfLiability)
  if (!['USD', 'TWD'].includes(p.currency)) add('currency', 'Product Recall currency must be TWD or USD')
  if (limit == null || limit <= 0) add('limitOfLiability', 'Limit of Indemnity must be greater than 0')
  for (const [field, label] of [['originalExclusions','Original Exclusions'], ['originalConditions','Original Conditions'], ['reinsuredRetention','Reinsured’s Retention'], ['expressWarranties','Express Warranties'], ['conditionsPrecedent','Conditions Precedent'], ['subjectivities','Subjectivities']]) if (!filled(p[field])) add(field, label)
  if (!filled(risk.choiceOfLaw)) add('productRecall.choiceOfLaw', 'Choice of Law and Jurisdiction')
  for (const [key, label] of [['events','Covered Event'], ['losses','Covered Loss'], ['additionalSublimits','Additional Sub-limit']]) {
    const rows = Array.isArray(risk[key]) ? risk[key] : [], names = new Set()
    if (key !== 'additionalSublimits' && !rows.some(row => row.selected && filled(row.name))) add(`productRecall.${key}`, `Select at least one ${label}`)
    rows.forEach((row, i) => {
      const name = String(row.name || '').trim().toLowerCase()
      if (!name || names.has(name)) add(`productRecall.${key}.${i}.name`, `${label} name is required and must be unique`)
      if (name) names.add(name)
      if (key !== 'events' && (key !== 'losses' || row.selected)) {
        const amount = number(row.amount)
        if (amount == null || amount <= 0 || limit != null && amount > limit) add(`productRecall.${key}.${i}.amount`, `${label} amount must be positive and not exceed the Limit of Indemnity`)
        if (amount != null && (p.currency === 'TWD' && !Number.isInteger(amount) || p.currency === 'USD' && Math.abs(amount * 100 - Math.round(amount * 100)) > 1e-7)) add(`productRecall.${key}.${i}.amount`, `${label} amount has too many decimal places`)
      }
    })
  }
  const lossNames = new Set((risk.losses || []).map(row => String(row.name || '').trim().toLowerCase()).filter(Boolean))
  ;(risk.additionalSublimits || []).forEach((row, i) => { if (lossNames.has(String(row.name || '').trim().toLowerCase())) add(`productRecall.additionalSublimits.${i}.name`, 'Use the existing Covered Loss sub-limit') })
  if (!filled(p.deductibles) && !filled(p.selfInsuredRetention)) add('deductibles', 'Enter Deductibles or Self-Insured Retention')
  if (filled(p.deductibles)) {
    const value = number(p.deductibles)
    if (value == null || value <= 0 || limit != null && value > limit || p.currency === 'TWD' && !Number.isInteger(value) || p.currency === 'USD' && Math.abs(value * 100 - Math.round(value * 100)) > 1e-7) add('deductibles', 'Deductibles must be positive, use the currency precision and not exceed the Limit of Indemnity')
  }
  return issues
}
