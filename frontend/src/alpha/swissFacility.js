export const SWISS_FACILITY_NAME='Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)'
export function isSwissFacility(name){return String(name||'').trim().replace(/\s+/g,' ').toLowerCase()===SWISS_FACILITY_NAME.toLowerCase()}
export function isSwissPropertyCase(payload){return String(payload?.classOfBusiness||'').trim().toLowerCase()==='property'&&payload?.reinsurers?.some(row=>isSwissFacility(row.name))===true}
