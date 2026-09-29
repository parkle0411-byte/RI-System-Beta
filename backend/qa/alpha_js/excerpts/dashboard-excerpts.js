// Alpha 原始碼的「節錄」（差異測試用）：來自 api/dashboard.js（v57，雜湊 496539893d6f1c20…）。
// 這個檔案 import 了 'hatchable'，無法直接在 Node 執行，所以把不碰資料庫的部分原樣切出來：
//   - 第 9–92 行：numberOrZero、stripFacility、TAIPEI_PARTS、taipeiParts、taipeiText、month、buildRateLookup、reinsurerLegs、topRows（逐字）
//   - 第 125–222 行：handler 在三個查詢之後的全部敘述（逐字），外面加上測試用的外殼函式 dashboardSummary：
//     外殼提供 caseResult／targetResult／fxResult（查詢結果）與 res.json（直接回傳內容），這幾行是測試加的。
// 這個檔案是由程式從「雜湊與 Alpha 相同」的原檔切出的（見 MANIFEST.md），不可手動修改。

import { buildPaymentSchedule } from '../lib/payment-terms.js';
import { installmentAllocations } from '../lib/production-report.js';

function numberOrZero(value) {
  const number = Number(String(value ?? '').replace(/,/g, ''));
  return Number.isFinite(number) ? number : 0;
}

// Company-VM rules synced 2026-09-29: "today / this month / this year" and the Announce month use
// Taipei time, and the monthly brokerage trend and reinsurer mix follow the Production Report rules
// (per-installment rounding with the remainder on the first installment, Endorsements counted in
// their creation month, and both "(Facility)" and "[Facility]" removed from reinsurer names).
function stripFacility(value) {
  return String(value || '').replace(/\s*[[(]Facility[\])]\s*$/i, '').trim();
}

const TAIPEI_PARTS = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'
});

function taipeiParts(value) {
  const parts = Object.fromEntries(TAIPEI_PARTS.formatToParts(value).map((part) => [part.type, part.value]));
  return { date: `${parts.year}-${parts.month}-${parts.day}`, time: `${parts.hour}:${parts.minute}:${parts.second}` };
}

// Timestamp -> Taipei local text ("YYYY-MM-DDTHH:MM:SS+08:00"); month() then reads the Taipei month.
function taipeiText(value) {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const parts = taipeiParts(date);
  return `${parts.date}T${parts.time}+08:00`;
}

function month(value) {
  const result = String(value || '').slice(0, 7);
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(result) ? result : '';
}

// Dashboard is a live snapshot (not a locked accounting period like Production
// Report), so case-level premium/outstanding figures are converted using the
// FX Rates table rather than a per-case static field: per currency, prefer the
// latest rate at or before the current month, falling back to the latest rate
// on file for that currency if none exists yet for/before this month.
function buildRateLookup(fxRows, currentMonth) {
  const atOrBefore = {};
  const anyLatest = {};
  (Array.isArray(fxRows) ? fxRows : []).forEach((row) => {
    const currency = String(row.currency || '').toUpperCase();
    const yearMonth = String(row.year_month || '');
    const rate = Number(row.rate);
    if (!currency || !Number.isFinite(rate) || rate <= 0) return;
    if (!anyLatest[currency] || yearMonth > anyLatest[currency].yearMonth) anyLatest[currency] = { yearMonth, rate };
    if (yearMonth <= currentMonth && (!atOrBefore[currency] || yearMonth > atOrBefore[currency].yearMonth)) {
      atOrBefore[currency] = { yearMonth, rate };
    }
  });
  return function caseRate(payload) {
    const currency = String(payload?.currency || '').toUpperCase();
    if (currency === 'TWD') return 1;
    const match = atOrBefore[currency] || anyLatest[currency];
    return match ? match.rate : 0;
  };
}

function reinsurerLegs(payload, reinsurer) {
  const order = numberOrZero(reinsurer?.sharePct) / 100;
  const cedantPremium = numberOrZero(payload?.originalPremium) * order;
  const leg1 = cedantPremium
    - cedantPremium * numberOrZero(payload?.riCommPct) / 100
    - cedantPremium * numberOrZero(payload?.taxPct) / 100;
  const reinsurerPremium = numberOrZero(reinsurer?.premium) * order;
  const leg2 = reinsurerPremium
    - reinsurerPremium * numberOrZero(reinsurer?.riCommPct) / 100
    - reinsurerPremium * numberOrZero(reinsurer?.taxPct) / 100;
  return { cedantPremium, brokerage: leg1 - leg2 };
}

function topRows(source, limit) {
  const entries = Object.entries(source).sort((a, b) => b[1] - a[1]);
  const selected = entries.slice(0, limit);
  const other = entries.slice(limit).reduce((sum, row) => sum + row[1], 0);
  if (other > 0) selected.push(['Other', other]);
  const total = selected.reduce((sum, row) => sum + row[1], 0);
  return selected.map(([name, amount]) => ({ name, amount, pct: total > 0 ? amount / total * 100 : 0 }));
}

export function dashboardSummary(caseRows, targetRows, fxRows) {
  const caseResult = { rows: caseRows }, targetResult = { rows: targetRows }, fxResult = { rows: fxRows };
  const res = { json: (body) => body };
  const now = new Date();
  const today = taipeiParts(now).date;
  const year = Number(today.slice(0, 4));
  const monthNumber = Number(today.slice(5, 7));
  const currentMonth = `${year}-${String(monthNumber).padStart(2, '0')}`;
  const caseRate = buildRateLookup(fxResult.rows, currentMonth);
  const live = (row) => row.status === 'posted' || row.status === 'closed';
  const rows = caseResult.rows.map((row) => {
    const announcedAt = taipeiText(row.announced_at);
    const createdAt = taipeiText(row.created_at);
    return {
      ...row,
      announced_at: announcedAt,
      created_at: createdAt,
      payload: { ...(row.payload || {}), announcedAt: announcedAt || row.payload?.announcedAt, createdAt: createdAt || row.payload?.createdAt }
    };
  });
  const roots = rows.filter((row) => !row.parent_case_id);
  const activeEndorsements = rows.filter((row) => row.parent_case_id && live(row)
    && Array.isArray(row.payload?.endoTypes) && row.payload.endoTypes.length
    && row.payload?.policyTo && row.payload.policyTo >= today);
  const inForce = roots.filter((row) => live(row) && row.payload?.policyTo && row.payload.policyTo >= today);

  const ytd = (targetYear, predicate) => roots.filter((row) => {
    const postedMonth = month(row.payload?.postedAt || row.announced_at);
    return live(row) && postedMonth >= `${targetYear}-01`
      && postedMonth <= `${targetYear}-${String(monthNumber).padStart(2, '0')}`
      && (!predicate || predicate(row.payload));
  }).length;
  const ytdCurrent = ytd(year);
  const ytdPrior = ytd(year - 1);
  const renewalsYtd = ytd(year, (payload) => payload.newOrRenew === 'Renew');
  const renewalsMtd = roots.filter((row) => live(row) && row.payload?.newOrRenew === 'Renew'
    && month(row.payload?.postedAt || row.announced_at) === currentMonth).length;
  const expectedRenewalsMtd = roots.filter((row) => live(row) && month(row.payload?.policyTo) === currentMonth).length;
  const newBusinessMtd = roots.filter((row) => live(row) && row.payload?.newOrRenew === 'New'
    && month(row.payload?.postedAt || row.announced_at) === currentMonth).length;

  let grossPremiumNtd = 0;
  let outstandingLeg1Ntd = 0;
  let outstandingLeg2Ntd = 0;
  const classTotals = {};
  const reinsurerTotals = {};
  inForce.forEach((row) => {
    const payload = row.payload;
    const rate = caseRate(payload);
    (Array.isArray(payload.reinsurers) ? payload.reinsurers : []).forEach((reinsurer) => {
      const amount = reinsurerLegs(payload, reinsurer).cedantPremium * rate;
      grossPremiumNtd += amount;
      const className = payload.classOfBusiness || 'Unclassified';
      classTotals[className] = (classTotals[className] || 0) + amount;
      const reinsurerName = stripFacility(reinsurer?.name) || 'Unnamed';
      reinsurerTotals[reinsurerName] = (reinsurerTotals[reinsurerName] || 0) + amount;
    });
  });
  inForce.concat(activeEndorsements).forEach((row) => {
    const rate = caseRate(row.payload);
    const schedule = buildPaymentSchedule(row.payload);
    outstandingLeg1Ntd += schedule.totals.cedantOutstanding * rate;
    outstandingLeg2Ntd += schedule.totals.reinsurerOutstanding * rate;
  });

  const monthly = {};
  for (let y = year - 1; y <= year; y += 1) {
    for (let m = 1; m <= 12; m += 1) monthly[`${y}-${String(m).padStart(2, '0')}`] = 0;
  }
  rows.filter(live).forEach((row) => {
    const rate = caseRate(row.payload);
    installmentAllocations(row.payload).forEach((entry) => {
      if (Object.prototype.hasOwnProperty.call(monthly, entry.performanceMonth)) monthly[entry.performanceMonth] += entry.income * rate;
    });
  });
  const targets = { annual: null, monthly: {} };
  targetResult.rows.forEach((row) => {
    if (row.period_type === 'annual' && row.period_key === String(year)) targets.annual = Number(row.amount);
    if (row.period_type === 'monthly') targets.monthly[row.period_key] = Number(row.amount);
  });

  return res.json({
    ok: true,
    period: { year, currentMonth, monthNumber },
    metrics: {
      ytdCurrent, ytdPrior, renewalsMtd, expectedRenewalsMtd, newBusinessMtd,
      inForcePolicies: inForce.length, activeEndorsements: activeEndorsements.length,
      openQuotes: roots.filter((row) => row.status === 'draft').length,
      retentionRatio: ytdPrior > 0 ? renewalsYtd / ytdPrior * 100 : null,
      grossPremiumNtd, outstandingLeg1Ntd, outstandingLeg2Ntd
    },
    brokerage: {
      labels: Array.from({ length: monthNumber }, (_, index) => String(index + 1).padStart(2, '0')),
      current: Array.from({ length: monthNumber }, (_, index) => monthly[`${year}-${String(index + 1).padStart(2, '0')}`]),
      prior: Array.from({ length: monthNumber }, (_, index) => monthly[`${year - 1}-${String(index + 1).padStart(2, '0')}`]),
      target: Array.from({ length: monthNumber }, (_, index) => targets.monthly[`${year}-${String(index + 1).padStart(2, '0')}`] || 0),
      annualTarget: targets.annual
    },
    classMix: topRows(classTotals, 5),
    reinsurers: topRows(reinsurerTotals, 6)
  });
}
