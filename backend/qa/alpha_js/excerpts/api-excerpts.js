// Alpha 原始碼的「節錄」（差異測試用）：來自 api/case-announce.js（雜湊 af6d6ed9…）與 api/case-workflow.js（雜湊 a74a399b…，v53）。
// 這兩個檔案 import 了 'hatchable'，無法直接在 Node 執行，所以把其中「不碰資料庫」的函式逐字複製到這裡。
//   - 標示「逐字」的函式與 Alpha 檔案內容完全相同（含縮排與註解）。
//   - 標示「包裝」的函式：函式本身是為了測試而加的外殼，裡面的敘述逐字取自 Alpha 的 createEndorsement /
//     createRenewal / reverseCase / notifyAccounting（Alpha 把這些敘述直接寫在含資料庫存取的 async 函式裡）。
// 不可以為了讓測試通過而修改這裡；Alpha 改了就重新節錄，再讓 Python 版跟上。

// ---- 逐字：api/case-announce.js ----
function reinsurerKey(value) {
  return String(value || '').replace(/\s*\(Facility\)\s*$/i, '').trim().toLowerCase().replace(/\s+/g, ' ');
}

function requiredReinsurers(payload) {
  return [...new Set((Array.isArray(payload?.reinsurers) ? payload.reinsurers : []).map((row) => reinsurerKey(row?.name)).filter(Boolean))];
}

function coverageFor(payload, files) {
  const selected = files.filter((file) => file.is_selected);
  const required = requiredReinsurers(payload);
  const offer = selected.some((file) => file.kind === 'offer');
  const evidence = new Set();
  selected.filter((file) => file.kind === 'signed' || file.kind === 'confirmation')
    .forEach((file) => (Array.isArray(file.reinsurers) ? file.reinsurers : []).forEach((name) => evidence.add(reinsurerKey(name))));
  const missing = required.filter((name) => !evidence.has(name));
  return { offer, required, missing, ready: offer && required.length > 0 && missing.length === 0, selected: selected.map((file) => String(file.id)).sort() };
}

function sameIds(left, right) {
  const a = (Array.isArray(left) ? left : []).map(String).sort();
  const b = (Array.isArray(right) ? right : []).map(String).sort();
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

function referencePrefix(payload) {
  const classCode = String(payload?.classCode || '').trim().toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 12) || 'XX';
  const match = /^(\d{4})-(\d{2})-\d{2}$/.exec(String(payload?.policyFrom || ''));
  if (!match) return null;
  return `TW${classCode}${match[1].slice(-2)}${match[2]}`;
}

// ---- 逐字：api/case-workflow.js ----
function shiftYear(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ''))) return '';
  const [year, month, day] = String(value).split('-').map(Number);
  const shifted = new Date(Date.UTC(year + 1, month - 1, day));
  if (shifted.getUTCMonth() !== month - 1) shifted.setUTCDate(0);
  return shifted.toISOString().slice(0, 10);
}

function resetSharedPayload(payload) {
  return {
    ...payload,
    status: 'draft',
    postedAt: '',
    confirmedProductionKeys: [],
    productionExclusions: {},
    productionPartiallyConfirmed: false,
    endorsements: [],
    transactions: [],
    claims: [],
    statementNo: '',
    reversalCycle: 0,
    pendingReversalOffset: null,
    accountingNotifications: [],
    // Bugfix: the actual collect/pay ledger (who has actually paid or been paid,
    // on which installment) was being carried over verbatim from the source
    // case, so a brand-new Endorsement/Renewal Draft -- which has had no real
    // payment activity of its own yet -- could show the old case's payments as
    // if they already happened. This is exactly the "financial fields that
    // must be re-entered" reset the Endorsement/Renewal workflow requires.
    paymentEntries: [],
    paymentScheduleReviewRequired: false
  };
}

// ---- 包裝（敘述逐字取自 Alpha）----
function buildEndorsementPayload(sourcePayload, rootTwRef, count) {
  const root = { tw_ref: rootTwRef };
  const source = { payload: sourcePayload };
  const payload = resetSharedPayload(JSON.parse(JSON.stringify(source.payload || {})));
  payload.parentTwRef = root.tw_ref;
  payload.endorsementSeq = count + 1;
  payload.endoEffectiveDate = '';
  payload.endoTypes = [];
  payload.endoText = '';
  payload.originalPremium = null;
  payload.exchRate = null;
  payload.statementNo = '';
  payload.claims = [];
  payload.reinsurers = (Array.isArray(payload.reinsurers) ? payload.reinsurers : []).map((row) => ({ ...row, premium: null, settlementRef: '' }));
  return payload;
}

function buildRenewalPayload(sourcePayload, sourceTwRef) {
  const source = { payload: sourcePayload, tw_ref: sourceTwRef };
  const payload = resetSharedPayload(JSON.parse(JSON.stringify(source.payload || {})));
  payload.parentTwRef = '';
  payload.endorsementSeq = null;
  payload.renewedFromTwRef = source.tw_ref || '';
  payload.newOrRenew = 'Renew';
  payload.policyFrom = shiftYear(payload.policyFrom);
  payload.policyTo = shiftYear(payload.policyTo);
  payload.endoEffectiveDate = '';
  payload.endoTypes = [];
  payload.endoText = '';
  payload.statementNo = '';
  payload.claims = [];
  payload.reinsurers = (Array.isArray(payload.reinsurers) ? payload.reinsurers : []).map((row) => ({ ...row, settlementRef: '' }));
  return payload;
}

function buildReversedPayload(sourcePayload) {
  const source = { payload: sourcePayload };
  const payload = JSON.parse(JSON.stringify(source.payload || {}));
  payload.reversalCycle = Number(payload.reversalCycle || 0) + 1;
  payload.transactions = (Array.isArray(payload.transactions) ? payload.transactions : [])
    .map((transaction) => transaction.isReversalEntry === true ? transaction : { ...transaction, reversed: true });
  payload.pendingReversalOffset = true;
  payload.confirmedProductionKeys = [];
  payload.productionPartiallyConfirmed = false;
  return payload;
}

function appendNotification(sourcePayload, notification) {
  const source = { payload: sourcePayload };
  const payload = JSON.parse(JSON.stringify(source.payload || {}));
  payload.accountingNotifications = [...(Array.isArray(payload.accountingNotifications) ? payload.accountingNotifications : []), notification];
  return payload;
}

export {
  reinsurerKey, requiredReinsurers, coverageFor, sameIds, referencePrefix, shiftYear, resetSharedPayload,
  buildEndorsementPayload, buildRenewalPayload, buildReversedPayload, appendNotification
};
