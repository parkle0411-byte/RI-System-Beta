// 2026-11-17：Accounting 清單的篩選與排序（原本寫在 Accounting.vue 內，邏輯不變）。
// Unreconciled／Reconciled 在瀏覽器用本檔；All Accounts／Settled/Closed／Brokerage 改由伺服器分頁，
// 伺服器 backend/cases/accounting_pages.py 依本檔實作，scripts/run_qa.sh pages 以本檔為基準逐頁比對。修改時兩邊要一起改。
import { activeAccount, isCedantAccount, accountSource, visibleAccount, isDerivedBrokerage } from './accountingCash'
import { displayTwRef } from '../alpha/manualTwRef'
import { transactionNumber } from '../alpha/transactionNumber'
import { transactionParty } from '../alpha/transactionParty'

export const SERVER_TABS = ['all', 'settled', 'brokerage']
export const SERVER_PAGE_SIZE = 100
export const rowTitle = r => r.scheduleOnly ? 'Historical schedule · ' + r.installmentLabel : transactionNumber(r.txNo)
export const actualDue = r => r.contractDueDate || r.schedules?.find(x => x.contractDueDate)?.contractDueDate || r.dueDate || ''
export const normalizedSettlement = r => r.settlement === 'partial' ? 'open' : r.settlement
export const matches = (values, q) => !q || values.some(v => String(v || '').toLowerCase().includes(q.trim().toLowerCase()))

// filters：cedant／reinsurer／currency／direction／settlement（陣列）／source／origin／due；text：{reference, insured}
export function filterRows(rows, tab, filters, text) {
  return rows.filter(r => {
    if (!visibleAccount(r, tab)) return false
    if (filters.settlement.length && (r.reversed || r.isReversalEntry || !filters.settlement.includes(normalizedSettlement(r)))) return false
    return matches([r.twRef, r.manualTwRef, displayTwRef(r)], text.reference) && matches([r.originalInsured, r.originalInsuredCn], text.insured)
      && (!filters.cedant || isCedantAccount(r) && transactionParty(r) === filters.cedant)
      && (!filters.reinsurer || !isCedantAccount(r) && transactionParty(r) === filters.reinsurer)
      && (!filters.currency || filters.currency === r.currency) && (!filters.direction || r.paymentDirection === filters.direction)
      && (!filters.source || accountSource(r) === filters.source) && (!filters.origin || (r.origin || 'native') === filters.origin)
      && (!filters.due || !!actualDue(r) && actualDue(r) <= filters.due)
  })
}

// 排序用的比較值每列只算一次（2026-11-13）；Intl.Collator 與 localeCompare 的預設比較相同。
export function sortRows(list, tab, now, collator) {
  if (tab === 'brokerage') {
    const keyed = list.map(r => ({r, settled: Number(r.settlement === 'settled'), tw: displayTwRef(r)}))
    keyed.sort((a, b) => a.settled - b.settled || collator.compare(a.tw, b.tw))
    return keyed.map(x => x.r)
  }
  if (tab === 'all') {
    // 2026-11-18 owner: overdue unsettled accounts stay on top (overdue = past the actual due date), oldest
    // Accounting date first; every other account by Accounting date newest first; accounts without a date last.
    const keyed = list.map(r => {
      const due = actualDue(r), overdue = r.settlement !== 'settled' && due && due < now
      const date = r.dueDate || r.schedules?.find(x => x.dueDate)?.dueDate || due || ''
      return {r, group: overdue ? 0 : date ? 1 : 2, date, tw: displayTwRef(r), title: rowTitle(r)}
    })
    keyed.sort((a, b) => a.group - b.group || (a.group === 1 ? collator.compare(b.date, a.date) : collator.compare(a.date, b.date))
      || collator.compare(a.tw, b.tw) || collator.compare(a.title, b.title))
    return keyed.map(x => x.r)
  }
  const keyed = list.map(r => {
    const due = actualDue(r), overdue = r.settlement !== 'settled' && due && due < now
    return {r, overdue: Number(!!overdue), date: overdue ? due : (r.dueDate || r.schedules?.find(x => x.dueDate)?.dueDate || due || '9999-12-31'), tw: displayTwRef(r), title: rowTitle(r)}
  })
  keyed.sort((a, b) => b.overdue - a.overdue || collator.compare(a.date, b.date) || collator.compare(a.tw, b.tw) || collator.compare(a.title, b.title))
  return keyed.map(x => x.r)
}

export function listRows(rows, tab, filters, text, now, collator) {
  return sortRows(filterRows(rows, tab, filters, text), tab, now, collator)
}

export function partyOptions(rows) {
  return {
    cedants: [...new Set(rows.filter(r => isCedantAccount(r) && !isDerivedBrokerage(r)).map(row => transactionParty(row)).filter(Boolean))].sort(),
    reinsurers: [...new Set(rows.filter(r => !isCedantAccount(r) && !isDerivedBrokerage(r)).map(row => transactionParty(row)).filter(Boolean))].sort(),
  }
}
