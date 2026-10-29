const swissName = 'swiss re asia pte. ltd., hong kong branch (facility)'
export const swissCglScope = (p, name = null) => String(p?.reinsuranceStructure || '').trim().toUpperCase() === 'QS'
  && String(p?.classOfBusiness || '').trim().toLowerCase() === 'commercial general liability'
  && (name === null ? (p?.reinsurers || []).map(r => r?.name) : [name])
    .some(n => String(n || '').trim().replace(/\s+/g, ' ').toLowerCase() === swissName)
