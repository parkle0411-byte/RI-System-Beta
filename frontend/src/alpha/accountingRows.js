// One Accounting list: posted transactions own their schedules; unposted schedules
// remain actionable without inventing a transaction or counting the same entry twice.
export function accountingRows(body) {
  const transactions = body.transactionRows || []
  const schedules = (body.swissRows || []).filter(row => row.partyType === 'cedant' || row.swissFacility || row.requiresCollectionConfirmation)
  const byKey = new Map(schedules.map(row => [row.key, row]))
  const ledger = new Map((body.rows || []).map(row => [row.key, row]))
  const covered = new Set()
  const rows = transactions.map(row => {
    const current = row.source !== 'claim' && !row.reversed && !row.isReversalEntry
    const associated = current ? [...new Set((row.cashParts || []).map(part => row.caseUid + ':' + part.scheduleKey))]
      .map(key => byKey.get(key)).filter(Boolean) : []
    associated.forEach(item => covered.add(item.key))
    return {...row, schedules: associated}
  })
  for (const item of schedules) {
    if (covered.has(item.key) || !(item.partyType === 'cedant' || item.swissFacility || item.requiresCollectionConfirmation)) continue
    const entries = (item.entries || []).map(entry => ({...entry,
      appliedAmount: Number(entry.amount || 0) * (entry.entryType === 'reversal' ? -1 : 1)}))
    const nonCashPaid = entries.reduce((sum, entry) => sum + (entry.nonCash ? entry.appliedAmount : 0), 0)
    const cedant = schedules.find(row => row.caseUid === item.caseUid && row.partyType === 'cedant')
    const incoming = (item.partyType === 'cedant') === (item.amount > 0)
    rows.push({...ledger.get(item.key), ...item, scheduleOnly: true, schedules: [item], source: 'premium',
      txNo: '', legType: item.partyType === 'cedant' ? 'Leg 1' : 'Leg 2',
      reinsured: cedant?.partyName || '', cashTracking: 'cash',
      paymentDirection: incoming ? 'receivable' : 'payable',
      cashPaid: item.paid - nonCashPaid, nonCashPaid, entries,
      paymentStatus: item.status, settlement: item.settlement || (Math.abs(item.outstanding) < .005 ? 'settled' : Math.abs(item.paid) > .004 ? 'partial' : 'open'),
      canRecord: !!item.dueDate && Math.abs(item.outstanding) > .004})
  }
  return rows
}
