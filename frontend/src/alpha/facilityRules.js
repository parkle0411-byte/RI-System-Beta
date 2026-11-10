import { allSumInsuredFacility } from './sumInsured.js'
import { FIXED_TEXT } from './constants.js'
import { CGL_INTEREST } from './cglRiskDetails.js'

export function fixedFacilityInterest(payload) {
  if (!allSumInsuredFacility(payload)) return ''
  const klass = String(payload?.classOfBusiness || '').trim().toLowerCase()
  return klass === 'property' ? FIXED_TEXT.interest : klass === 'commercial general liability' ? CGL_INTEREST : ''
}

export function propertyQsFacility(payload) {
  return allSumInsuredFacility(payload)
    && String(payload?.classOfBusiness || '').trim().toLowerCase() === 'property'
    && String(payload?.reinsuranceStructure || '').trim().toUpperCase() === 'QS'
}
