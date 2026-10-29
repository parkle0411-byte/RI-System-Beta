export const QBE_FACILITY_NAME = 'QBE Hongkong & Shanghai Insurance Limited (Facility)'
export function isQbeReinsurer(name) {
  return String(name || '').trim().replace(/\s+/g, ' ').toLowerCase() === QBE_FACILITY_NAME.toLowerCase()
}
export function isQbeTarget(payload,name) {
  return String(payload?.classOfBusiness||'').trim().toLowerCase()==='property' && isQbeReinsurer(name)
}
export function hasQbe(payload) {
  return (Array.isArray(payload?.reinsurers)?payload.reinsurers:[]).some(row=>isQbeTarget(payload,row?.name))
}
