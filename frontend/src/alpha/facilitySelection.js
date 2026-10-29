// Case selection scope is independent of each Facility's accounting rules.
const rules = [
  {
    "name": "Lloyd's Underwriter Syndicate No. 0609 AUW (Facility)",
    "label": "AUW Facility",
    "classes": [
      "Property"
    ]
  },
  {
    "name": "Allianz Global Corporate & Specialty SE, Hong Kong Branch (Facility)",
    "label": "Allianz Facility",
    "classes": [
      "Property"
    ]
  },
  {
    "name": "Great American Insurance Company, Singapore Branch (Facility)",
    "label": "Great American Facility",
    "classes": [
      "Property"
    ]
  },
  {
    "name": "QBE Hongkong & Shanghai Insurance Limited (Facility)",
    "label": "QBE Facility",
    "classes": [
      "Property"
    ]
  },
  {
    "name": "Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)",
    "label": "Swiss Re Asia Facility",
    "classes": [
      "Property",
      "Commercial General Liability"
    ]
  }
]
const normalizedName = name => String(name || '').trim().replace(/\s+/g, ' ').toLowerCase()
const swissCglSelection = (payload, name) => String(payload?.classOfBusiness || '').trim().toLowerCase() === 'commercial general liability'
  && normalizedName(name) === 'swiss re asia pte. ltd., hong kong branch (facility)'
export function facilityStructureAllowed(payload, structure) {
  return !(Array.isArray(payload?.reinsurers) ? payload.reinsurers : []).some(row => swissCglSelection(payload, row?.name))
    || String(structure || '').trim().toUpperCase() === 'QS'
}
export function facilitySelectionAllowed(payload, name) {
  const rule = rules.find(rule => normalizedName(rule.name) === normalizedName(name))
  return (!rule || rule.classes.some(klass => klass.toLowerCase() === String(payload?.classOfBusiness || '').trim().toLowerCase()))
    && (!swissCglSelection(payload, name) || String(payload?.reinsuranceStructure || '').trim().toUpperCase() === 'QS')
}
export function facilitySelectionIssues(payload) {
  return (Array.isArray(payload?.reinsurers) ? payload.reinsurers : []).flatMap((row, index) => {
    const rule = rules.find(rule => normalizedName(rule.name) === normalizedName(row?.name))
    if (swissCglSelection(payload, row?.name) && String(payload?.reinsuranceStructure || '').trim().toUpperCase() !== 'QS') {
      return [{ field: 'reinsuranceStructure', label: `Reinsurer ${index + 1}: Swiss Re CGL Facility is available only for Quota Share (QS).` }]
    }
    return rule && !facilitySelectionAllowed(payload, row?.name)
      ? [{ field: `reinsurers.${index}.name`, label: `Reinsurer ${index + 1}: ${rule.label} is available only for ${rule.classes.join(' or ')}.` }]
      : []
  })
}
