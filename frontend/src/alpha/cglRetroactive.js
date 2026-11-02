// Canonical rows retain incomplete input; ordering uses full ISO dates.
export function retroactiveRows(info = {}) {
  return Array.isArray(info.retroactiveDates) ? info.retroactiveDates : info.retroactiveDate ? [{ date: info.retroactiveDate, description: '' }] : []
}
export function validRetroactiveDate(value) {
  const d = /^\d{4}-\d{2}-\d{2}$/.test(value || '') ? new Date(value + 'T00:00:00Z') : null
  return !!d && !Number.isNaN(d.getTime()) && d.getUTCFullYear() >= 100 && d.toISOString().slice(0, 10) === value
}
export function sortedRetroactiveRows(info) {
  return [...retroactiveRows(info)].sort((a,b) => (validRetroactiveDate(a.date) ? a.date : '~~~~').localeCompare(validRetroactiveDate(b.date) ? b.date : '~~~~'))
}
export function retroactiveIssues(info) {
  const rows = retroactiveRows(info), issues = []
  const add = (key,label) => issues.push({ field: 'cglInformation.' + key, label })
  if (!rows.length) add('retroactiveDates', 'Retroactive Date — at least one entry')
  const seen = new Set()
  rows.forEach((r,i) => {
    if (!validRetroactiveDate(r?.date)) add(`retroactiveDates.${i}.date`, `Retroactive Date ${i+1} must use a valid YYYY-MM-DD date`)
    else if (seen.has(r.date)) add(`retroactiveDates.${i}.date`, 'Duplicate Retroactive Date — combine the descriptions for the same date.')
    seen.add(r?.date)
    if (rows.length > 1 && !String(r?.description || '').trim()) add(`retroactiveDates.${i}.description`, `Retroactive Date ${i+1} description is required when there are multiple dates`)
  })
  return issues
}
export function retroactiveText(info) {
  if (info?.policyForm !== 'Claims-Made Form') return ''
  return sortedRetroactiveRows(info).map(r => {
    const date = validRetroactiveDate(r.date) ? new Date(r.date + 'T00:00:00Z').toLocaleDateString('en-US', { timeZone:'UTC', month:'long', day:'2-digit', year:'numeric' }) : String(r.date || '')
    const description = String(r.description || '').trim()
    return description ? `(${date} in respect of ${description})` : date
  }).join('\n')
}
