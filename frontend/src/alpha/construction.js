export const CONSTRUCTION_OPTIONS = ['A2 Class', 'A1 Class', 'B Class', 'C Class', 'D Class']
export const constructionScope = p => String(p?.classOfBusiness || '').trim().toLowerCase() === 'property' && ['QS','XOL','FACULTATIVE'].includes(String(p?.reinsuranceStructure || '').toUpperCase())
export function constructionLegacyText(p) {
  return Object.hasOwn(p || {}, 'constructionLegacyText') ? String(p.constructionLegacyText || '') : !Array.isArray(p?.constructionSelections) ? String(p?.construction || '') : ''
}
export function initializeConstruction(p) {
  if (constructionScope(p) && !Array.isArray(p.constructionSelections)) {
    p.constructionLegacyText = constructionLegacyText(p)
    p.constructionSelections = []
    p.constructionLegacyConfirmed = !p.constructionLegacyText.trim()
  }
  return p
}
export function constructionText(p) {
  if (!constructionScope(p)) return p.construction || ''
  const old = constructionLegacyText(p)
  if (old.trim() && p.constructionLegacyConfirmed !== true) return old
  return CONSTRUCTION_OPTIONS.filter(x => (p.constructionSelections || []).includes(x)).join('\n')
}
export function constructionIssues(p) {
  if (!constructionScope(p)) return []
  const issues = [], selected=p.constructionSelections
  if (!Array.isArray(selected) || !selected.length || selected.some(x => !CONSTRUCTION_OPTIONS.includes(x))) issues.push({field:'constructionSelections',label:'Construction — select at least one available class.'})
  if (constructionLegacyText(p).trim() && p.constructionLegacyConfirmed !== true) issues.push({field:'constructionLegacyConfirmed',label:'Confirm the new Construction selections before replacing the historical text.'})
  return issues
}
