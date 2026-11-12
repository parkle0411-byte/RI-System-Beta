export const propertyQsCurrencyScope = p =>
  String(p?.classOfBusiness || '').trim().toLowerCase() === 'property' &&
  ['QS', 'FACULTATIVE'].includes(String(p?.reinsuranceStructure || '').trim().toUpperCase())

export const propertyQsCurrencyIssues = p => propertyQsCurrencyScope(p) &&
  !['TWD', 'USD'].includes(String(p?.currency || '').trim().toUpperCase())
  ? [{ field: 'currency', label: 'Property QS Currency must be TWD or USD.' }] : []
