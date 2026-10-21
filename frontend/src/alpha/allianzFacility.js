export const ALLIANZ_FACILITY_NAME = 'Allianz Global Corporate & Specialty SE, Hong Kong Branch (Facility)'
export function isAllianzReinsurer(name) {
  return String(name || '').trim().replace(/\s+/g, ' ').toLowerCase() === ALLIANZ_FACILITY_NAME.toLowerCase()
}
export function hasAllianz(payload) {
  return (Array.isArray(payload?.reinsurers) ? payload.reinsurers : []).some(row => isAllianzReinsurer(row?.name))
}
