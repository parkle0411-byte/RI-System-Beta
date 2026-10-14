import { transactionLabel } from './transactionNumber'

// reinsurer associates a claim split with its security line, even on the cedant leg.
// Resolve the displayed party without changing the stored transaction or split association.
export function transactionParty(transaction, caseData = transaction) {
  const leg = String(transaction?.legType || '')
  if (leg.startsWith('Claim Leg 2') || leg.startsWith('Leg 1') || transaction?.partyType === 'cedant') {
    return String(caseData?.reinsured || '').trim() || 'Cedant'
  }
  if (leg.startsWith('Leg 3')) return 'Broker'
  return transaction?.partyName || transaction?.reinsurer || '—'
}

export function transactionRecipient(transaction, caseData = transaction) {
  if (transaction?.cashTracking === 'derived') return transaction.cashDescription || 'Brokerage retained from premium receipts and payments'
  const label = transactionLabel(transaction?.label)
  if (String(transaction?.legType || '').startsWith('Claim Leg 2')) {
    return label.replace(/^(Payable — reinsurance dept owes )cedant unit(?= \(claim )/,
      (_, prefix) => prefix + transactionParty(transaction, caseData))
  }
  if (String(transaction?.legType || '').startsWith('Leg 1')) {
    return label.replace(/cedant unit/, () => transactionParty(transaction, caseData))
  }
  return label
}

export function paymentDirection(transaction) {
  if (transaction?.paymentDirection === 'retained') return 'Retained brokerage'
  if (transaction?.paymentDirection) return transaction.paymentDirection === 'payable' ? 'Payable' : 'Receivable'
  const leg = String(transaction?.legType || '')
  const normallyReceivable = transaction?.partyType === 'cedant' || leg.startsWith('Leg 1') || leg.startsWith('Claim Leg 1')
  const negative = Number(transaction?.amount || 0) < 0
  return normallyReceivable !== negative ? 'Receivable' : 'Payable'
}
