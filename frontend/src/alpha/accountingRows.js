// One Accounting list: posted transactions own their schedules; unposted schedules
// remain visible for reference before Production close.
export function accountingRows(body) {
  const transactions = body.transactionRows || []
  const schedules = [...new Map([...(body.scheduleRows || []), ...(body.rows || []).filter(row => row.source === 'premium'), ...(body.swissRows || [])].map(row => [row.key, row])).values()]
  const byKey = new Map(schedules.map(row => [row.key, row]))
  const ledger = new Map((body.rows || []).map(row => [row.key, row]))
  const covered = new Set()
  const rows = transactions.map(row => {
    const current = row.source !== 'claim' && !row.reversed && !row.isReversalEntry
    const associated = current ? [...new Set((row.cashParts || []).map(part => row.caseUid + ':' + part.scheduleKey))]
      .map(key => byKey.get(key)).filter(Boolean).map(item => {
        if (!row.swissCgl || row.settlement !== 'settled') return item
        const dates = Object.fromEntries(['baseDate','dueDate','contractDueDate','termsDays','reminderDate','paymentRule']
          .filter(key => row[key] !== undefined && row[key] !== null).map(key => [key,row[key]]))
        return {...item,...dates,status:row.paymentStatus}
      }) : []
    associated.forEach(item => covered.add(item.key))
    return {...row, schedules: associated}
  })
  for (const item of schedules) {
    if (covered.has(item.key) || !(item.swissCase || item.swissFacility || item.requiresCollectionConfirmation || item.greatAmericanCase || item.qbeCase)) continue
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
      canRecord: false, canConfirmSettlement: false})
  }
  return rows
}
