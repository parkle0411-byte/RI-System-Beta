export function claimLossSnapshotIssues(payload) {
  if (!payload?.renewedFromTwRef) return []
  const result = []
  for (const [index, row] of (payload.claimLossSnapshots || []).entries()) {
    const label = `Claim loss ${index + 1}`
    const raw = row?.date || ''
    const date = /^\d{4}-\d{2}-\d{2}$/.test(raw) ? new Date(raw + 'T00:00:00Z') : null
    if (!date || Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== raw) result.push(`${label} Date of Loss`)
    if (!String(row?.cause || '').trim()) result.push(`${label} Cause`)
    const amount = row?.lossPaid
    if (amount === null || amount === undefined || String(amount).trim() === '' || !Number.isFinite(Number(amount)) || Number(amount) < 0 || row?.snapshotModified === true && Number(amount) <= 0) result.push(`${label} Loss Amount`)
  }
  return result
}
