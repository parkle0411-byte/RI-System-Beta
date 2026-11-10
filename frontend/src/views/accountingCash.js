import { transactionParty } from '../alpha/transactionParty'

export const partyKey = row => String(transactionParty(row) || '').trim().replace(/\s+/g, ' ').toLowerCase()
export const isOverseaCash = row => !!row.overseaBusiness && row.cashTracking !== 'derived'
export const isDerivedBrokerage = row => row.cashTracking === 'derived' || (!row.overseaBusiness && String(row.legType || '').startsWith('Leg 3'))
export const activeAccount = row => !!row.txNo && !row.scheduleOnly && !row.reversed && !row.isReversalEntry
export const isCedantAccount = row => row.partyType === 'cedant' || /^(Leg 1|Claim Leg 2)(?:\b|$)/.test(String(row.legType || ''))
export const accountSource = row => isOverseaCash(row) ? 'brokerage' : row.source

export function visibleAccount(row, tab) {
  if (isDerivedBrokerage(row)) return tab === 'brokerage'
  if (isOverseaCash(row)) {
    if (tab === 'all') return true
    if (!activeAccount(row)) return false
    if (tab === 'brokerage') return row.settlement === 'settled'
    if (tab === 'settled' || row.settlement === 'settled') return false
  } else if (tab === 'brokerage') return false
  if (tab === 'settled') return activeAccount(row) && row.settlement === 'settled'
  if (tab === 'unreconciled') return !row.financeReviewed
  if (tab === 'reconciled') return !!row.financeReviewed
  return true
}

export function cashTotals(allocations, include = () => true) {
  const totals = new Map()
  for (const allocation of allocations.filter(include)) {
    const row = allocation.row
    const currency = String(row.currency || '').toUpperCase()
    const total = totals.get(currency) || {currency, receivable: 0, payable: 0, net: 0}
    const value = Number(allocation.cashAmount)
    if (Number.isFinite(value) && value > 0) {
      const side = row.paymentDirection === 'payable' ? 'payable' : 'receivable'
      total[side] += Math.round(value * 100)
    }
    totals.set(currency, total)
  }
  return [...totals.values()].sort((a, b) => a.currency.localeCompare(b.currency)).map(total => ({
    currency: total.currency, receivable: total.receivable / 100,
    payable: total.payable / 100, net: (total.receivable - total.payable) / 100,
  }))
}

export function cashUuid() {
  const bytes = new Uint8Array(16)
  globalThis.crypto.getRandomValues(bytes)
  bytes[6] = (bytes[6] & 15) | 64
  bytes[8] = (bytes[8] & 63) | 128
  const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`
}
