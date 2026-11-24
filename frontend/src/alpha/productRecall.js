const nameKey = value => value.replace(/[A-Z]/g, c => c.toLowerCase())
export const RECALL_CURRENCIES = ['TWD', 'USD', 'EUR', 'JPY', 'GBP', 'HKD', 'MYR']
export const RECALL_EVENTS = ['Defect', 'Malicious Product Tampering', 'Product Extortion', 'Government Recall']
export const RECALL_LOSSES = ['First Party Recall Costs', 'Third Party Recall Costs', 'Consultant and Advisor Costs', 'Extortion Costs']
export const recallScope = p => String(p?.classOfBusiness || '').trim().toLowerCase() === 'product recall' && ['QS', 'FACULTATIVE'].includes(String(p?.reinsuranceStructure || '').toUpperCase())
export const claimCurrencyScope = p => recallScope(p) || String(p?.classOfBusiness || '').trim().toLowerCase() === 'stock throughput' || String(p?.classOfBusiness || '').trim().toLowerCase() === 'commercial general liability' && ['QS', 'FACULTATIVE'].includes(String(p?.reinsuranceStructure || '').toUpperCase()) && !(p?.reinsurers || []).some(row => /\bfacility\b/i.test(String(row?.name || '')) && !/swiss re asia/i.test(String(row?.name || '')))
export function initialRecall() {
  return {
    choiceOfLaw: 'This (re)insurance shall be governed by and construed in according with the law of Republic of China, Taiwan and the each party agrees to submit to the exclusive jurisdiction of the Courts of the Republic of China, Taiwan.',
    events: RECALL_EVENTS.map((name, i) => ({ id: `event-${i + 1}`, name, selected: true, fixed: true })),
    losses: RECALL_LOSSES.map((name, i) => ({ id: `loss-${i + 1}`, name, selected: true, fixed: true, amount: null })),
    eventsOtherSelected: false, lossesOtherSelected: false
  }
}

export function orderedRecallRows(rows, group) {
  const prefix = group === 'events' ? 'event' : 'loss'
  const rank = row => { const i = [1, 2, 3, 4].findIndex(n => row?.id === `${prefix}-${n}`); return i < 0 ? 4 : i }
  return [...(rows || [])].sort((a, b) => rank(a) - rank(b))
}

export function productRecallDraftIssues(p) {
  if (!recallScope(p)) return []
  const risk = p.productRecall || {}, issues = []
  for (const [key, label] of [['events', 'Covered Event'], ['losses', 'Covered Loss']]) {
    const rows = Array.isArray(risk[key]) ? risk[key] : [], names = new Set()
    const other = risk[key === 'events' ? 'eventsOtherSelected' : 'lossesOtherSelected'] ?? rows.some(row => !row.fixed && row.selected)
    rows.forEach((row, i) => {
      if (!row.fixed && !other) return
      const name = String(row.name || '').trim(), normalized = nameKey(name)
      if (name && (names.has(normalized) || name.length > 240 || /[\r\n]/.test(name))) issues.push({ field: `productRecall.${key}.${i}.name`, label: `${label} names must be unique and single-line` })
      if (name) names.add(normalized)
      if (key === 'losses' && (row.fixed ? row.selected : other)) {
        const currency = row.currency || p.currency, raw = row.amount
        if (currency && !RECALL_CURRENCIES.includes(currency)) issues.push({ field: `productRecall.${key}.${i}.currency`, label: 'Select a valid sub-limit currency' })
        if (raw !== null && raw !== undefined && String(raw).trim() !== '') {
          const n = Number(raw), digits = currency === 'TWD' ? 1 : 100
          if (!Number.isFinite(n) || n <= 0 || Math.abs(n * digits - Math.round(n * digits)) > 1e-7) issues.push({ field: `productRecall.${key}.${i}.amount`, label: 'Sub-limit amount must be positive and use the currency precision' })
        }
      }
    })
  }
  return issues
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
  for (const [key, label] of [['events','Covered Event'], ['losses','Covered Loss']]) {
    const rows = Array.isArray(risk[key]) ? risk[key] : [], names = new Set()
    const other = risk[key === 'events' ? 'eventsOtherSelected' : 'lossesOtherSelected'] ?? rows.some(row => !row.fixed && row.selected)
    const custom = rows.filter(row => !row.fixed)
    if (other && !custom.length) add(`productRecall.${key}`, `${label} Other requires an item`)
    if (!rows.some(row => (row.fixed ? row.selected : other) && filled(row.name))) add(`productRecall.${key}`, `Select at least one ${label}`)
    rows.forEach((row, i) => {
      const active = row.fixed ? row.selected : other
      if (!row.fixed && !other) return
      const name = nameKey(String(row.name || '').trim())
      if ((!name && active) || name && names.has(name)) add(`productRecall.${key}.${i}.name`, `${label} name is required and must be unique`)
      if (name) names.add(name)
      if (key === 'losses' && active) {
        const amount = number(row.amount), currency = row.currency || p.currency
        if (!RECALL_CURRENCIES.includes(currency)) add(`productRecall.${key}.${i}.currency`, 'Select a valid currency')
        if (amount == null || amount <= 0) add(`productRecall.${key}.${i}.amount`, `${label} amount must be positive`)
        if (amount != null && (currency === 'TWD' && !Number.isInteger(amount) || currency !== 'TWD' && Math.abs(amount * 100 - Math.round(amount * 100)) > 1e-7)) add(`productRecall.${key}.${i}.amount`, `${label} amount has too many decimal places`)
      }
    })
  }
  if (!filled(p.deductibles) && !filled(p.selfInsuredRetention)) add('deductibles', 'Enter Deductibles or Self-Insured Retention')
  if (filled(p.deductibles)) {
    const value = number(p.deductibles)
    if (value == null || value <= 0 || limit != null && value > limit || p.currency === 'TWD' && !Number.isInteger(value) || p.currency === 'USD' && Math.abs(value * 100 - Math.round(value * 100)) > 1e-7) add('deductibles', 'Deductibles must be positive, use the currency precision and not exceed the Limit of Indemnity')
  }
  return issues
}
