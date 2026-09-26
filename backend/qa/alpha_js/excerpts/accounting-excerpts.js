// Alpha 原始碼的「節錄」（差異測試用）：來自 api/accounting.js（v53，雜湊 ddd2cc0a643038a4…）。
// 這個檔案 import 了 'hatchable'，無法直接在 Node 執行，所以把其中不碰資料庫的部分原樣切出來：
// 第 3–4 行（import reconciliationRefFor、buildPaymentSchedule）、第 37–85 行（ledgerRows）。
// 這個檔案是由程式從「雜湊與 Alpha 相同」的原檔切出的（見 MANIFEST.md），不可手動修改。

import { reconciliationRefFor } from "../lib/accounting.js";
import { buildPaymentSchedule } from "../lib/payment-terms.js";

function ledgerRows(cases) {
  const rows = [];
  const warnings = [];
  cases.forEach((caseData) => {
    const schedule = buildPaymentSchedule(caseData.payload);
    if (schedule.reviewRequired) warnings.push({ caseUid: caseData.caseUid, twRef: caseData.twRef, issues: schedule.issues });
    schedule.items.forEach((item) => rows.push({
      key: caseData.caseUid + ":" + item.scheduleKey,
      caseUid: caseData.caseUid, caseRowVersion: caseData.rowVersion,
      twRef: caseData.twRef, caseStatus: caseData.status, announcedAt: caseData.announcedAt,
      source: "premium", scheduleKey: item.scheduleKey,
      installmentId: item.installmentId, installmentLabel: item.installmentLabel,
      partyType: item.partyType, partyName: item.partyName,
      legType: item.partyType === "cedant" ? "Cedant" : "Reinsurer",
      reinsured: caseData.reinsured,
      reinsurer: item.partyType === "reinsurer" ? item.partyName : "",
      label: (item.partyType === "cedant" ? "Receivable from " : "Payable to ") + item.partyName,
      amount: item.amount, paid: item.paid, outstanding: item.outstanding,
      currency: item.currency, baseDate: item.baseDate, termsDays: item.termsDays,
      dueDate: item.dueDate, dueTime: item.dueTime, paymentStatus: item.status,
      partial: item.partial, settlement: item.status === "settled" ? "settled" : "open",
      reviewRequired: item.status === "pending_review",
      entries: (Array.isArray(caseData.payload?.paymentEntries) ? caseData.payload.paymentEntries : [])
        .filter((entry) => entry.scheduleKey === item.scheduleKey)
    }));

    const claims = (Array.isArray(caseData.payload?.transactions) ? caseData.payload.transactions : [])
      .filter((transaction) => transaction?.source === "claim");
    claims.forEach((transaction) => rows.push({
      key: caseData.caseUid + ":" + transaction.txNo,
      caseUid: caseData.caseUid, caseRowVersion: caseData.rowVersion,
      twRef: caseData.twRef, caseStatus: caseData.status, announcedAt: caseData.announcedAt,
      source: "claim", txNo: String(transaction.txNo || ""),
      legType: String(transaction.legType || ""), reinsured: caseData.reinsured,
      reinsurer: String(transaction.reinsurer || ""), label: String(transaction.label || ""),
      amount: Number(transaction.amount || 0), paid: transaction.settlement === "settled" ? Number(transaction.amount || 0) : 0,
      outstanding: transaction.settlement === "settled" ? 0 : Number(transaction.amount || 0),
      currency: caseData.currency, reconciliationRef: reconciliationRefFor(caseData.payload, transaction),
      settlement: transaction.settlement === "settled" ? "settled" : "open",
      paymentStatus: transaction.settlement === "settled" ? "settled" : "upcoming",
      settledAt: transaction.settledAt || null, settledBy: transaction.settledBy || null,
      reversed: transaction.reversed === true, isReversalEntry: transaction.isReversalEntry === true
    }));
  });
  return {
    rows: rows.sort((a, b) => a.twRef.localeCompare(b.twRef) || String(a.dueDate || "").localeCompare(String(b.dueDate || ""))),
    warnings
  };
}

export { ledgerRows as accountingLedgerRows };
