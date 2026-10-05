// Alpha 原始碼的「節錄」（差異測試用）：來自 api/production-report.js（v63，雜湊 ad033c0da163ba9f…）。
// 這個檔案 import 了 'hatchable'，無法直接在 Node 執行。closeReport() 裡「整理一個案件」的敘述
// （第 261–333 行：確認 key、判斷這次要產生哪些保費交易（沒有分期＝整案一次；有分期＝每期確認就產生該期）、
// 交易有空項目時回 409、沖銷與保費交易）原樣切出，外面加上測試用的外殼函式
// productionConfirmCase（外殼的宣告、res、closedCases 的初值與 return 是測試加的；res.json 會拋錯，
// 讓「回 409」在差異測試裡與 VM 的 TransactionsCorrupt 一樣算「出錯」）。
// 這個檔案是由程式從「雜湊與 Alpha 相同」的原檔切出的（見 MANIFEST.md），不可手動修改。

import { productionKeysForCase, productionKeyGroupsForCase } from '../lib/production-report.js';
import { buildPremiumTransactions } from '../lib/accounting.js';
import { premiumInstallmentPlan } from '../lib/payment-terms.js';

export function productionConfirmCase(source, reportRows) {
  const res = { status: () => ({ json: (body) => { throw new Error(body.error); } }) };
  let closedCases = 0;
    const payload = JSON.parse(JSON.stringify(source.payload || {}));
    const wasClosed = source.status === 'closed';
    const confirmed = new Set(Array.isArray(payload.confirmedProductionKeys) ? payload.confirmedProductionKeys : []);
    reportRows.forEach((row) => confirmed.add(String(row.reinsurerKey)));
    payload.confirmedProductionKeys = Array.from(confirmed);
    const remaining = productionKeysForCase(source).some((key) => !confirmed.has(key));
    payload.productionPartiallyConfirmed = remaining;
    const nextStatus = remaining ? 'posted' : 'closed';
    const cycle = Number(payload.reversalCycle || 0);
    const transactionCase = { ...payload, twRef: source.tw_ref || payload.twRef || '' };
    let baseTransactions = Array.isArray(payload.transactions) ? payload.transactions : [];
    if (!wasClosed && !remaining) closedCases += 1;
    // Company-VM rule synced 2026-09-29: which premium transactions to create in this close.
    // No installments = the whole case once every Production key is confirmed (as before).
    // Installments = each installment's transactions as soon as ALL of that installment's keys
    // are confirmed (once per installment), so the SoA fills up as the months close.
    let batches = [];
    const plan = premiumInstallmentPlan(transactionCase);
    if (plan.length === 0) {
      if (!wasClosed && !remaining) batches = [null];
    } else {
      const isLive = (transaction) => transaction != null && transaction.source !== 'claim'
        && transaction.reversed !== true && transaction.isReversalEntry !== true;
      // Older data: whole-case transactions (no installmentId) already cover every installment.
      if (!baseTransactions.some((transaction) => isLive(transaction) && !transaction.installmentId)) {
        const groups = productionKeyGroupsForCase(source);
        batches = plan.filter((entry, index) => {
          if (baseTransactions.some((transaction) => isLive(transaction) && transaction.installmentId === entry.id)) return false;
          const keys = groups[index] ? groups[index].keys : [];
          return keys.length > 0 ? keys.every((key) => confirmed.has(key)) : !remaining;
        });
      }
    }
    if (batches.length > 0) {
      let appended = [];
      if (payload.pendingReversalOffset && baseTransactions.some((transaction) => transaction == null)) {
        return res.status(409).json({ error: 'transactions_corrupt', message: 'The transaction records of a case in this report are damaged (an empty entry was found). Contact the system administrator.' });
      }
      if (payload.pendingReversalOffset) {
        // Bugfix: `reversed === true` alone does not distinguish "reversed this
        // cycle, needs an offset now" from "already offset by a -RVS entry in a
        // prior close cycle" -- that flag is never cleared, so on a second
        // Reverse/close round every earlier-offset entry was being caught again
        // and offset a second time (double-reversal). reversalOffsetApplied is
        // a one-way marker set the moment an entry receives its -RVS offset, so
        // it can never be offset again in a later cycle.
        const eligible = (transaction) => transaction.reversed === true
          && transaction.isReversalEntry !== true
          && transaction.reversalOffsetApplied !== true;
        const reversalEntries = baseTransactions
          .filter(eligible)
          .map((transaction) => ({
            ...transaction,
            txNo: `${transaction.txNo}-RVS${cycle}`,
            amount: -Number(transaction.amount || 0),
            label: `Reversal of ${transaction.txNo}`,
            isReversalEntry: true,
            settlement: 'open',
            reversed: false,
            settledAt: null,
            settledBy: null
          }));
        appended = appended.concat(reversalEntries);
        baseTransactions = baseTransactions.map((transaction) =>
          eligible(transaction) ? { ...transaction, reversalOffsetApplied: true } : transaction
        );
        payload.pendingReversalOffset = false;
      }
      const newTransactions = batches
        .flatMap((entry) => buildPremiumTransactions(transactionCase, entry))
        .map((transaction) => cycle > 0 ? { ...transaction, txNo: `${transaction.txNo}-C${cycle}` } : transaction);
      payload.transactions = baseTransactions.concat(appended, newTransactions);
    }
  return { payload, nextStatus, remaining, closedCases };
}
