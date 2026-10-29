export const ALLIANZ_FACILITY_NAME = 'Allianz Global Corporate & Specialty SE, Hong Kong Branch (Facility)'
export function isAllianzReinsurer(name) {
  return String(name || '').trim().replace(/\s+/g, ' ').toLowerCase() === ALLIANZ_FACILITY_NAME.toLowerCase()
}
export function isAllianzTarget(payload, name) {
  return String(payload?.classOfBusiness || '').trim().toLowerCase() === 'property' && isAllianzReinsurer(name)
}
export function allianzSelectionIssues(payload) {
  return (Array.isArray(payload?.reinsurers) ? payload.reinsurers : []).flatMap((row, index) =>
    isAllianzReinsurer(row?.name) && !isAllianzTarget(payload, row?.name)
      ? [{ field: `reinsurers.${index}.name`, label: `Reinsurer ${index + 1}: Allianz Facility is available only for Property.` }] : [])
}
export function hasAllianz(payload) {
  return (Array.isArray(payload?.reinsurers) ? payload.reinsurers : []).some(row => isAllianzTarget(payload, row?.name))
}
