// Alpha 原始碼的「節錄」（差異測試用）：來自 api/production-report.js（v53，雜湊 669afb28d56692b9…）。
// 這個檔案 import 了 'hatchable'，無法直接在 Node 執行。closeReport() 裡「整理一個案件」的敘述
// （第 241–288 行：確認 key、判斷是否全部確認、產生沖銷與保費交易）原樣切出，外面加上測試用的外殼函式
// productionConfirmCase（外殼的宣告、closedCases 的初值與 return 是測試加的）。
// 這個檔案是由程式從「雜湊與 Alpha 相同」的原檔切出的（見 MANIFEST.md），不可手動修改。

import { productionKeysForCase } from '../lib/production-report.js';
import { buildPremiumTransactions } from '../lib/accounting.js';

export function productionConfirmCase(source, reportRows) {
  let closedCases = 0;
    const payload = JSON.parse(JSON.stringify(source.payload || {}));
    const wasClosed = source.status === 'closed';
    const confirmed = new Set(Array.isArray(payload.confirmedProductionKeys) ? payload.confirmedProductionKeys : []);
    reportRows.forEach((row) => confirmed.add(String(row.reinsurerKey)));
    payload.confirmedProductionKeys = Array.from(confirmed);
    const remaining = productionKeysForCase(source).some((key) => !confirmed.has(key));
    payload.productionPartiallyConfirmed = remaining;
    const nextStatus = remaining ? 'posted' : 'closed';
    if (!wasClosed && !remaining) {
      const cycle = Number(payload.reversalCycle || 0);
      let appended = [];
      let baseTransactions = Array.isArray(payload.transactions) ? payload.transactions : [];
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
      const transactionCase = { ...payload, twRef: source.tw_ref || payload.twRef || '' };
      const newTransactions = buildPremiumTransactions(transactionCase)
        .map((transaction) => cycle > 0 ? { ...transaction, txNo: `${transaction.txNo}-C${cycle}` } : transaction);
      payload.transactions = baseTransactions.concat(appended, newTransactions);
      closedCases += 1;
    }
  return { payload, nextStatus, remaining, closedCases };
}
