export const MANUAL_TW_REF_REINSURER = "Lloyd's Underwriter Syndicate No. 0609 AUW (Facility)"
export const AUW_FOREIGN_BROKER = "Howden Specialty Limited"

export function isAuwReinsurer(name) {
  return typeof name === 'string' && name.trim().replace(/\s+/g, ' ').toLowerCase() === MANUAL_TW_REF_REINSURER.toLowerCase()
}

export function requiresManualTwRef(payload) {
  return (Array.isArray(payload?.reinsurers) ? payload.reinsurers : []).some(row => isAuwReinsurer(row?.name))
}

// Display only: persisted automatic and AUW references remain separate.
export function displayTwRef(caseData, fallback = '—') {
  const automatic = String(caseData?.twRef || '').trim()
  const auw = String(caseData?.manualTwRef || caseData?.payload?.manualTwRef || '').trim()
  return [...new Set([automatic, auw].filter(Boolean))].join(' & ') || fallback
}


export function isPureAuwCase(payload) {
  const rows = (Array.isArray(payload?.reinsurers) ? payload.reinsurers : []).filter(row => String(row?.name || '').trim())
  return rows.length > 0 && rows.every(row => isAuwReinsurer(row.name))
}
