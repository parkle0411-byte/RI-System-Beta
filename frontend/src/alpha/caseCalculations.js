// 案件畫面的計算。來源：Alpha public/case-calculations.js（RICaseCalculations）。
//
// VM 刻意與 Alpha 不同（2026-09-25 的決定，見 MIGRATION-STATUS.md「案件合計」）：
// 金額合計（totals）改用 Alpha lib/accounting.js 的逐步進位算法（每家再保人各項進位到分，合計再進位），
// 與後端 cases/calc/totals.py 完全相同，所以列表、畫面、記帳三處的數字一致。
// 非金額的合計（Order hereon、Sum Insured、Avg. Rate）仍照 case-calculations.js。
import { calcLegsForReinsurer } from './lib/accounting.js';

function numberOrZero(value) {
  const number = Number.parseFloat(value);
  return Number.isFinite(number) ? number : 0;
}

function totalOrderHereon(caseData) {
  return (Array.isArray(caseData?.reinsurers) ? caseData.reinsurers : [])
    .reduce((sum, row) => sum + numberOrZero(row?.sharePct), 0);
}

function totalSumInsured(caseData) {
  return (Array.isArray(caseData?.sumInsured) ? caseData.sumInsured : [])
    .reduce((sum, row) => sum + numberOrZero(row?.amount), 0);
}

function avgRateText(caseData) {
  const rawPremium = caseData?.originalPremium;
  const premium = Number(rawPremium);
  const hasPremium = rawPremium !== null && rawPremium !== undefined
    && String(rawPremium).trim() !== '' && Number.isFinite(premium);
  const total = totalSumInsured(caseData);
  if (!hasPremium || !Number.isFinite(total) || total <= 0) return 'N/A';
  const rate = premium / total * 100;
  return Number.isFinite(rate) ? `${rate.toFixed(6)}%` : 'N/A';
}

// 與 lib/accounting.js 的 money() 相同
function money(value) {
  return Math.round((Number(value) + Number.EPSILON) * 100) / 100;
}

// 畫面欄位名稱 <- calcLegsForReinsurer 的欄位名稱（與 totals.py 的 _FIELDS 相同）
const FIELDS = {
  cedantPremium: 'cp', cedantCommission: 'ri', cedantTax: 'tax', leg1: 'leg1',
  reinsurerPremium: 'reinsurerCp', reinsurerDeductions: 'reinsurerRi', reinsurerTax: 'reinsurerTax', leg2: 'leg2',
  leg3: 'leg3', brokerage: 'brokerage'
};

function forReinsurer(caseData, reinsurer) {
  const legs = calcLegsForReinsurer(caseData, reinsurer);
  return Object.fromEntries(Object.entries(FIELDS).map(([name, source]) => [name, legs[source]]));
}

function totals(caseData) {
  const sums = Object.fromEntries(Object.keys(FIELDS).map((name) => [name, 0]));
  (Array.isArray(caseData?.reinsurers) ? caseData.reinsurers : []).forEach((row) => {
    const line = forReinsurer(caseData, row);
    Object.keys(sums).forEach((name) => { sums[name] += line[name]; });
  });
  return Object.fromEntries(Object.entries(sums).map(([name, value]) => [name, money(value)]));
}

export const RICaseCalculations = { numberOrZero, totalOrderHereon, totalSumInsured, avgRateText, forReinsurer, totals };
