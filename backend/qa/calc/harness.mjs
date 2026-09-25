// 以 Alpha 的原始 JavaScript 執行每一組向量，輸出結果（JSON）。
// 用法：node harness.mjs <vectors.json> ；Alpha 的檔案由執行環境放在 ./lib/（見 scripts/run_calc_diff.sh）
import { readFileSync } from 'node:fs'
import * as accounting from './lib/accounting.js'
import * as paymentTerms from './lib/payment-terms.js'
import * as caseDraft from './lib/case-draft.js'

const fns = {
  stripFacilityTag: accounting.stripFacilityTag,
  calcLegsForReinsurer: accounting.calcLegsForReinsurer,
  buildPremiumTransactions: accounting.buildPremiumTransactions,
  buildClaimPaymentTransactions: accounting.buildClaimPaymentTransactions,
  reconciliationRefFor: accounting.reconciliationRefFor,
  addCalendarDays: paymentTerms.addCalendarDays,
  taipeiDate: paymentTerms.taipeiDate,
  daysBetweenDates: paymentTerms.daysBetweenDates,
  paymentInstallments: paymentTerms.paymentInstallments,
  buildPaymentSchedule: paymentTerms.buildPaymentSchedule,
  deriveLedgerSettlement: paymentTerms.deriveLedgerSettlement,
  reminderKind: paymentTerms.reminderKind,
  normalizeDraft: caseDraft.normalizeDraft,
  validateAnnounceReady: caseDraft.validateAnnounceReady,
}

// 讓「new Date()」（不帶參數）回傳固定時間，其餘行為不變；只在需要時暫時替換。
const RealDate = Date
function withFixedNow(iso, fn) {
  const fixed = new RealDate(iso).getTime()
  globalThis.Date = class extends RealDate {
    constructor(...args) { if (args.length === 0) super(fixed); else super(...args) }
    static now() { return fixed }
  }
  try { return fn() } finally { globalThis.Date = RealDate }
}

const vectors = JSON.parse(readFileSync(process.argv[2], 'utf8'))
const out = []
for (const v of vectors) {
  const args = v.now !== undefined && ['buildPaymentSchedule', 'taipeiDate'].includes(v.fn)
    ? [...v.args, new RealDate(v.now)] : v.args
  try {
    const value = v.now !== undefined ? withFixedNow(v.now, () => fns[v.fn](...args)) : fns[v.fn](...args)
    out.push(value === undefined ? { undef: true } : { ok: JSON.parse(JSON.stringify(value, (k, x) => (typeof x === 'number' && !Number.isFinite(x) ? { __nonfinite: String(x) } : x))) })
  } catch (e) {
    out.push({ error: e && e.constructor ? e.constructor.name : 'Error' })
  }
}
process.stdout.write(JSON.stringify(out))
