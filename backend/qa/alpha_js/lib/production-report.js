export const PRODUCTION_REPORT_HEADERS = [
  'Original Insured', 'Reinsured', 'Reinsurer / RI Broker', 'Class', 'Type',
  'Currency', 'Exch. Rate', 'A/E', 'Eff Date', 'Exp Date', 'Comm (%)',
  'Premium (NTD)', 'Income (NTD)', 'Policy No', 'Endorse No', 'Remark', 'Tranx Date'
];

function numberOrZero(value) {
  const number = Number(String(value ?? '').replace(/,/g, ''));
  return Number.isFinite(number) ? number : 0;
}
function round2(value) { return Math.round((numberOrZero(value) + Number.EPSILON) * 100) / 100; }
function yearMonth(value) {
  const result = String(value || '').slice(0, 7);
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(result) ? result : '';
}
function monthEnd(month) {
  const match = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(month || '');
  if (!match) return '';
  return new Date(Date.UTC(Number(match[1]), Number(match[2]), 0)).toISOString().slice(0, 10);
}
export function nextProductionMonth(month) {
  const match = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(month || '');
  if (!match) return '';
  return new Date(Date.UTC(Number(match[1]), Number(match[2]), 1)).toISOString().slice(0, 7);
}
function baseMonth(caseData) {
  const effective = yearMonth(caseData.policyFrom);
  const activity = yearMonth(caseData.parentTwRef ? caseData.createdAt : (caseData.announcedAt || caseData.postedAt));
  return effective > activity ? effective : activity;
}
function reinsurerLegs(caseData, reinsurer) {
  const order = numberOrZero(reinsurer?.sharePct) / 100;
  const cedantPremium = numberOrZero(caseData?.originalPremium) * order;
  const cedantCommission = cedantPremium * numberOrZero(caseData?.riCommPct) / 100;
  const cedantTax = cedantPremium * numberOrZero(caseData?.taxPct) / 100;
  const leg1 = cedantPremium - cedantCommission - cedantTax;
  const reinsurerPremium = numberOrZero(reinsurer?.premium) * order;
  const reinsurerDeductions = reinsurerPremium * numberOrZero(reinsurer?.riCommPct) / 100;
  const reinsurerTax = reinsurerPremium * numberOrZero(reinsurer?.taxPct) / 100;
  const leg2 = reinsurerPremium - reinsurerDeductions - reinsurerTax;
  return { cedantPremium, brokerage: leg1 - leg2 };
}
function totalIncome(caseData) {
  return (Array.isArray(caseData?.reinsurers) ? caseData.reinsurers : [])
    .reduce((sum, reinsurer) => sum + reinsurerLegs(caseData, reinsurer).brokerage, 0);
}
function installmentAllocations(caseData) {
  const totalPremium = numberOrZero(caseData?.originalPremium);
  const income = totalIncome(caseData);
  if (!caseData?.installmentEnabled) return [{ id: 'FULL', performanceMonth: baseMonth(caseData), ratio: 1, income }];
  const source = Array.isArray(caseData.performanceInstallments) ? caseData.performanceInstallments : [];
  const rows = source.map((row, index) => {
    const ratio = totalPremium === 0 ? numberOrZero(row?.ratio) / 100 : numberOrZero(row?.premium) / totalPremium;
    return { id: String(row?.id || `I${index + 1}`), performanceMonth: yearMonth(row?.performanceMonth), ratio, income: round2(income * ratio) };
  });
  if (rows.length) {
    const tail = round2(income - rows.reduce((sum, row) => sum + row.income, 0));
    rows[0].income = round2(rows[0].income + tail);
  }
  return rows;
}
function performancePeople(caseData) {
  if (caseData?.splitEnabled && Array.isArray(caseData.splitParties) && caseData.splitParties.length) {
    return caseData.splitParties.map((person, index) => ({ name: String(person?.name || caseData.ae || `Party ${index + 1}`), pct: numberOrZero(person?.pct) }));
  }
  return [{ name: String(caseData?.ae || ''), pct: 100 }];
}
function roundedShares(total, people, aeName) {
  const rounded = people.map((person) => Math.round(numberOrZero(total) * person.pct / 100));
  const delta = Math.round(numberOrZero(total)) - rounded.reduce((sum, value) => sum + value, 0);
  if (delta && people.length) {
    let winner = 0;
    people.forEach((person, index) => {
      const current = people[winner];
      if (person.pct > current.pct || (person.pct === current.pct && person.name === aeName)) winner = index;
    });
    rounded[winner] += delta;
  }
  return rounded;
}
function rateFor(caseData, month, fxRates) {
  const currency = String(caseData?.currency || 'TWD').toUpperCase();
  if (currency === 'TWD') return 1;
  const direct = Number(fxRates?.[currency]);
  const monthly = Number(fxRates?.[month]?.[currency]);
  const rate = Number.isFinite(monthly) && monthly > 0 ? monthly : direct;
  return Number.isFinite(rate) && rate > 0 ? rate : null;
}
function rowSort(a, b) {
  return a.originalInsured.localeCompare(b.originalInsured) || a.policyNo.localeCompare(b.policyNo)
    || a.effDate.localeCompare(b.effDate) || a.reinsurer.localeCompare(b.reinsurer) || a.ae.localeCompare(b.ae);
}
function normalizeSource(source) {
  const caseData = { ...(source?.payload || source || {}) };
  caseData.id = Number(source?.id || caseData.id);
  caseData.status = source?.status || caseData.status;
  caseData.twRef = source?.twRef || source?.tw_ref || caseData.twRef;
  caseData.announcedAt = source?.announcedAt || source?.announced_at || caseData.announcedAt;
  caseData.createdAt = source?.createdAt || source?.created_at || caseData.createdAt;
  caseData.caseUid = source?.caseUid || source?.case_uid || caseData.caseUid;
  caseData.rowVersion = Number(source?.rowVersion || source?.row_version || caseData.rowVersion || 0);
  return caseData;
}
function exclusionMatches(exclusion, caseId, key, reinsurerKey, field, value) {
  if (Number(exclusion.case_id ?? exclusion.caseId) !== Number(caseId)) return false;
  const alternative = field === 'year_month' ? 'yearMonth' : 'deferredTo';
  if (String((exclusion[field] ?? exclusion[alternative]) || '') !== value) return false;
  if (exclusion.scope === 'case') return String((exclusion.installment_key ?? exclusion.installmentKey) || '') === key;
  return exclusion.scope === 'reinsurer' && String((exclusion.reinsurer_key ?? exclusion.reinsurerKey) || '') === reinsurerKey;
}
function exclusionFor(exclusions, caseId, key, reinsurerKey, month) {
  return exclusions.find((row) => exclusionMatches(row, caseId, key, reinsurerKey, 'year_month', month)) || null;
}
function deferredFrom(exclusions, caseId, key, reinsurerKey, month) {
  return exclusions.some((row) => exclusionMatches(row, caseId, key, reinsurerKey, 'deferred_to', month));
}
function confirmed(caseData, key) {
  return Array.isArray(caseData.confirmedProductionKeys) && caseData.confirmedProductionKeys.includes(key);
}

export function productionKeysForCase(source) {
  const caseData = normalizeSource(source);
  const keys = [];
  const reinsurers = Array.isArray(caseData.reinsurers) ? caseData.reinsurers : [];
  installmentAllocations(caseData).forEach((installment) => {
    if (installment.income === 0) return;
    const key = `${caseData.id}:${installment.id}`;
    const rawIncomes = reinsurers.map((reinsurer) => reinsurerLegs(caseData, reinsurer).brokerage * installment.ratio);
    const incomeTail = installment.income - rawIncomes.reduce((sum, value) => sum + value, 0);
    reinsurers.forEach((reinsurer, index) => {
      const sourceIncome = rawIncomes[index] + (index === 0 ? incomeTail : 0);
      if (sourceIncome !== 0) keys.push(`${key}:R${index}`);
    });
  });
  return keys;
}

export function productionSourceSignature(rows) {
  return JSON.stringify((Array.isArray(rows) ? rows : []).map((row) => [
    row.id, row.originalInsured, row.reinsured, row.reinsurer, row.classCode, row.type,
    row.currency, row.rate, row.ae, row.effDate, row.expDate, round2(row.comm),
    row.premium, row.income, row.policyNo, row.endorseNo, row.remark, row.tranxDate
  ]));
}

export function buildProductionPreview(caseRows, month, fxRates = {}, exclusions = []) {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(String(month || ''))) {
    return { errors: ['Report month must use YYYY-MM.'], rows: [], excluded: [], missingRateCurrencies: [] };
  }
  const rows = [], excludedRows = [], missingRates = new Set();
  for (const source of Array.isArray(caseRows) ? caseRows : []) {
    const caseData = normalizeSource(source);
    if (!['posted', 'closed', 'reversed'].includes(caseData.status)) continue;
    const reinsurers = Array.isArray(caseData.reinsurers) ? caseData.reinsurers : [];
    const people = performancePeople(caseData);
    installmentAllocations(caseData).forEach((installment, installmentIndex) => {
      const key = `${caseData.id}:${installment.id}`;
      const belongs = installment.performanceMonth === month;
      const rawIncomes = reinsurers.map((reinsurer) => reinsurerLegs(caseData, reinsurer).brokerage * installment.ratio);
      const incomeTail = installment.income - rawIncomes.reduce((sum, value) => sum + value, 0);
      reinsurers.forEach((reinsurer, reinsurerIndex) => {
        const reinsurerKey = `${key}:R${reinsurerIndex}`;
        if (confirmed(caseData, reinsurerKey)) return;
        if (!belongs && !deferredFrom(exclusions, caseData.id, key, reinsurerKey, month)) return;
        const exclusion = exclusionFor(exclusions, caseData.id, key, reinsurerKey, month);
        const legs = reinsurerLegs(caseData, reinsurer);
        const sourcePremium = legs.cedantPremium * installment.ratio;
        const sourceIncome = rawIncomes[reinsurerIndex] + (reinsurerIndex === 0 ? incomeTail : 0);
        if (sourceIncome === 0) return;
        const rate = rateFor(caseData, month, fxRates);
        const currency = String(caseData.currency || 'TWD').toUpperCase();
        if (rate === null) missingRates.add(currency);
        const premiums = rate === null ? people.map(() => null) : roundedShares(sourcePremium * rate, people, caseData.ae);
        const incomes = rate === null ? people.map(() => null) : roundedShares(sourceIncome * rate, people, caseData.ae);
        const endorsementMatch = caseData.parentTwRef && String(caseData.twRef || '').match(/-([Ee]\d+)$/);
        people.forEach((person, personIndex) => {
          const reinsurerName = String(reinsurer?.name || '').replace(/\s*[[(]Facility[\])]\s*$/i, '').trim();
          const row = {
            id: `${reinsurerKey}:P${personIndex}`, key, reinsurerKey,
            caseId: caseData.id, caseUid: caseData.caseUid, caseRowVersion: caseData.rowVersion,
            installmentId: installment.id, month,
            originalInsured: String(caseData.originalInsured || ''), reinsured: String(caseData.reinsured || ''),
            reinsurer: String(reinsurer?.foreignBroker || '').trim() || reinsurerName,
            classCode: String(caseData.classCode || caseData.classOfBusiness || ''),
            type: caseData.newOrRenew === 'Renew' ? 'R' : 'N', currency, rate, missingRate: rate === null,
            ae: person.name || String(caseData.ae || ''), effDate: String(caseData.policyFrom || ''),
            expDate: String(caseData.policyTo || ''),
            comm: sourcePremium === 0 && sourceIncome !== 0 ? 100 : (sourcePremium ? sourceIncome / sourcePremium * 100 : 0),
            premium: premiums[personIndex], income: incomes[personIndex],
            policyNo: String(caseData.parentTwRef || caseData.twRef || ''),
            endorseNo: endorsementMatch ? endorsementMatch[1] : '',
            remark: caseData.reinsuranceStructure === 'TREATY' ? 'Ty' : 'Fac',
            tranxDate: monthEnd(month), installment: installmentIndex + 1,
            exclusion: exclusion ? {
              id: exclusion.id, scope: exclusion.scope, reason: exclusion.reason,
              deferredTo: exclusion.deferred_to ?? exclusion.deferredTo,
              createdAt: exclusion.created_at ?? exclusion.createdAt
            } : null
          };
          (exclusion ? excludedRows : rows).push(row);
        });
      });
    });
  }
  rows.sort(rowSort); excludedRows.sort(rowSort);
  return {
    errors: [], rows, excluded: excludedRows,
    missingRateCurrencies: Array.from(missingRates).sort(),
    sourceSignature: productionSourceSignature(rows)
  };
}