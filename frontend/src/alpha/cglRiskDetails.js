import { isStandardCgl } from './cglInformation'

export const CGL_COVERAGES = [
  'Premises-Operations Liability',
  'Products & Completed-Operation Liability',
  'Personal & Advertising Injury Liability',
  'Medical Payment',
  'Other'
]

export function cglRiskDetailsIssues(payload) {
  if (!isStandardCgl(payload)) return []
  const selected = payload?.coverages
  if (!Array.isArray(selected) || !selected.length || selected.some(item => !CGL_COVERAGES.includes(item))) {
    return [{ field: 'coverages', label: 'Coverages — select at least one available option' }]
  }
  if (selected.includes('Other') && !String(payload?.coveragesOther || '').trim()) {
    return [{ field: 'coveragesOther', label: 'Coverages — Other' }]
  }
  return []
}

export function cglCoveragesText(payload) {
  const selected = Array.isArray(payload?.coverages) ? payload.coverages : []
  return CGL_COVERAGES.filter(item => selected.includes(item))
    .map(item => item === 'Other' ? 'Other: ' + String(payload?.coveragesOther || '').trim() : item).join('\n')
}


export const CGL_TYPE_PREFIXES = ['Products Liability', 'Commercial General Liability']
export const CGL_INTEREST = 'Reinsurance of the Reinsured’s liability under the original policy.'
const CGL_SUFFIXES = { QS: 'Facultative Reinsurance', FACULTATIVE: 'Facultative Reinsurance', XOL: 'Excess of Loss Facultative Reinsurance' }

export function cglTypePrefix(payload) {
  const explicit = String(payload?.typePrefix || '').trim()
  if (explicit) return explicit
  const stored = String(payload?.type || '').trim().replace(/\s+as original$/i, '')
  for (const suffix of [CGL_SUFFIXES.XOL, CGL_SUFFIXES.QS]) {
    if (stored.endsWith(suffix)) return stored.slice(0, -suffix.length).trim()
  }
  return stored
}

export function cglTypeSuffix(payload) {
  return (CGL_SUFFIXES[String(payload?.reinsuranceStructure || '').trim().toUpperCase()] || CGL_SUFFIXES.QS) + ' as original'
}

export function cglType(payload) {
  const prefix = cglTypePrefix(payload)
  return prefix ? prefix + ' ' + cglTypeSuffix(payload) : ''
}

export function cglTypeIssues(payload) {
  return isStandardCgl(payload) && !CGL_TYPE_PREFIXES.includes(cglTypePrefix(payload))
    ? [{ field: 'typePrefix', label: 'Type — select Products Liability or Commercial General Liability' }] : []
}

export function liabilityLimitLabel(payload) {
  return isStandardCgl(payload) ? 'Limit of Indemnity' : 'Limit of Liability'
}


export function cglUnderlyingIssues(payload) {
  return isStandardCgl(payload) && String(payload?.reinsuranceStructure || '').trim().toUpperCase() === 'XOL'
    && !String(payload?.underlyingLimits ?? '').trim()
    ? [{ field: 'underlyingLimits', label: 'Underlying Limits' }] : []
}


export const CGL_CLAUSE_PRESETS = [
  { code: 'LMA3100', title: 'LMA3100 Sanctions Limitations and Exclusion Clause' },
  { code: 'LMA5396', title: 'LMA5396 Communicable Disease Exclusion' },
  { code: 'EXGRATIA', title: 'Excluding Ex-Gratia and without prejudice payment' }
]

// Missing values in new and legacy cases use the owner's checked default.
export function cglAnnual(payload) { return payload?.cglAnnual !== false }
