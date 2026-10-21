export const GREAT_AMERICAN_FACILITY_NAME = 'Great American Insurance Company, Singapore Branch (Facility)'
export function isGreatAmericanReinsurer(name) {
  return String(name || '').trim().replace(/\s+/g, ' ').toLowerCase() === GREAT_AMERICAN_FACILITY_NAME.toLowerCase()
}
export function isGreatAmericanTarget(payload,name) {
  return String(payload?.classOfBusiness||'').trim().toLowerCase()==='property' && isGreatAmericanReinsurer(name)
}
export function hasGreatAmerican(payload) {
  return (Array.isArray(payload?.reinsurers)?payload.reinsurers:[]).some(row=>isGreatAmericanTarget(payload,row?.name))
}
