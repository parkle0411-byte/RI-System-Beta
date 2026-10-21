function numberOrZero(value) {
  const number = Number(String(value ?? '').replace(/,/g, ''));
  return Number.isFinite(number) ? number : 0;
}

// Bugfix (#3): none of the amount math in this file was ever rounded to
// cents, unlike lib/payment-terms.js's own money() helper. Chaining several
// percentage multiply/divides (e.g. 33.33%) leaves a floating-point residue
// that got written straight into permanent accounting entries, and could
// drift out of sync with payment-terms.js's rounded presentation figures.
// Same rounding formula as lib/payment-terms.js's money(), for consistency.
function money(value) {
  return Math.round((Number(value) + Number.EPSILON) * 100) / 100;
}

export function premiumMoney(value, caseData) {
  return String(caseData?.currency || '').trim().toUpperCase() === 'TWD' && caseData?.premiumRounding !== 'legacy-cents'
    ? Math.round(Number(value) + Number.EPSILON) : money(value);
}

export function premiumInputErrors(payload, existing = null) {
  if (String(payload?.currency || '').trim().toUpperCase() !== 'TWD') return [];
  const fields = c => [['originalPremium', '100% Premium', c?.originalPremium],
    ...['reinsurers', 'performanceInstallments'].flatMap(key => (c?.[key] || []).map((r, i) =>
      [`${key}.${i}.premium`, `${key === 'reinsurers' ? 'Reinsurer' : 'Installment'} ${i + 1} Premium`, r?.premium]))];
  const old = new Map(existing?.premiumRounding === 'legacy-cents' ? fields(existing).map(([path, , value]) => [path, value]) : []);
  return fields(payload).filter(([path, , value]) => value != null && String(value).trim() !== ''
    && Number.isFinite(Number(String(value).replace(/,/g, ''))) && !Number.isInteger(Number(String(value).replace(/,/g, '')))
    && !(old.has(path) && old.get(path) === value)).map(([, label]) => `${label} must be a whole number for TWD; decimals are not allowed.`);
}

export function stripFacilityTag(value) {
  return String(value || '').replace(/\s*[[(]Facility[\])]\s*$/i, '').trim();
}

export function calcLegsForReinsurer(caseData, reinsurer) {
  const roundMoney = value => premiumMoney(value, caseData);
  const source = value => ['TWD', 'USD'].includes(String(caseData?.currency || '').toUpperCase()) && caseData?.premiumRounding !== 'legacy-cents' ? roundMoney(value) : value;
  const orderPct = numberOrZero(reinsurer?.sharePct);
  const caseCp = roundMoney(source(numberOrZero(caseData?.originalPremium)) * orderPct / 100);
  const caseRi = roundMoney(caseCp * numberOrZero(caseData?.riCommPct) / 100);
  const caseTax = roundMoney(caseCp * numberOrZero(caseData?.taxPct) / 100);
  const leg1 = roundMoney(caseCp - caseRi - caseTax);

  const reinsurerCp = roundMoney(source(numberOrZero(reinsurer?.premium)) * orderPct / 100);
  const reinsurerRi = roundMoney(reinsurerCp * numberOrZero(reinsurer?.riCommPct) / 100);
  const reinsurerTax = roundMoney(reinsurerCp * numberOrZero(reinsurer?.taxPct) / 100);
  const leg2 = roundMoney(reinsurerCp - reinsurerRi - reinsurerTax);
  const leg3 = roundMoney(leg1 - leg2);
  return { cp: caseCp, ri: caseRi, tax: caseTax, leg1, reinsurerCp, reinsurerRi, reinsurerTax, leg2, leg3, brokerage: leg3 };
}

export function buildPremiumTransactions(caseData) {
  const roundMoney = value => premiumMoney(value, caseData);
  const transactions = [];
  const reinsurers = Array.isArray(caseData?.reinsurers) ? caseData.reinsurers : [];
  reinsurers.forEach((reinsurer, reinsurerIdx) => {
    const legs = calcLegsForReinsurer(caseData, reinsurer);
    const reinsurerLabel = stripFacilityTag(reinsurer?.name) || `Reinsurer ${reinsurerIdx + 1}`;
    const settlementLabel = String(reinsurer?.foreignBroker || '').trim() || reinsurerLabel;
    const base = [
      { legType: 'Leg 1', label: `Receivable — cedant unit owes reinsurance dept (${reinsurerLabel})`, amount: legs.leg1 },
      { legType: 'Leg 2', label: `Payable — reinsurance dept owes ${settlementLabel}`, amount: legs.leg2 },
      { legType: 'Leg 3', label: 'Payable — reinsurance dept owes broker', amount: legs.leg3 }
    ];
    if (caseData?.parentTwRef && numberOrZero(caseData?.originalPremium) < 0) {
      const refundLabels = [
        `Payable — reinsurance dept owes cedant unit (return premium; ${reinsurerLabel})`,
        `Receivable — ${settlementLabel} owes reinsurance dept (return premium)`,
        'Receivable — broker owes reinsurance dept (return brokerage)'
      ];
      base.forEach((leg, index) => { if (leg.amount < 0) leg.label = refundLabels[index]; });
    }
    const split = caseData?.splitEnabled === true && Array.isArray(caseData?.splitParties) && caseData.splitParties.length === 2;
    if (split) {
      caseData.splitParties.forEach((party, partyIdx) => {
        const suffix = partyIdx === 0 ? 'a' : 'b';
        const pct = numberOrZero(party?.pct);
        base.forEach((leg, legIdx) => transactions.push({
          txNo: `${caseData.twRef}-R${reinsurerIdx + 1}-T${legIdx + 1}${suffix}`,
          legType: `${leg.legType}${suffix}`,
          label: `${leg.label} (${party?.name || 'Unassigned'}, ${pct}%)`,
          amount: partyIdx === 1 && Math.abs(caseData.splitParties.reduce((n, p) => n + numberOrZero(p.pct), 0) - 100) < 1e-9
            ? roundMoney(leg.amount - roundMoney(leg.amount * numberOrZero(caseData.splitParties[0].pct) / 100))
            : roundMoney(leg.amount * pct / 100),
          splitParty: party?.name || `Party ${suffix.toUpperCase()}`,
          reinsurer: settlementLabel,
          viaForeignBroker: settlementLabel !== reinsurerLabel,
          settlement: 'open',
          reinsurerIdx
        }));
      });
    } else {
      base.forEach((leg, legIdx) => transactions.push({
        txNo: `${caseData.twRef}-R${reinsurerIdx + 1}-T${legIdx + 1}`,
        legType: leg.legType,
        label: leg.label,
        amount: leg.amount,
        splitParty: null,
        reinsurer: settlementLabel,
        viaForeignBroker: settlementLabel !== reinsurerLabel,
        settlement: 'open',
        reinsurerIdx
      }));
    }
  });
  return transactions;
}

function normalizedName(value) {
  return stripFacilityTag(value).toLowerCase().replace(/\s+/g, ' ').trim();
}

export function buildClaimPaymentTransactions(rootCase, splitSource, claim, payment) {
  const transactions = [];
  const lossLabel = claim?.lossNo || `Claim #${claim?.id}`;
  const rootReinsurers = Array.isArray(rootCase?.reinsurers) ? rootCase.reinsurers : [];
  const splitReinsurers = Array.isArray(splitSource?.reinsurers) ? splitSource.reinsurers : [];
  splitReinsurers.forEach((reinsurer, splitIdx) => {
    const shareAmount = money(numberOrZero(payment?.amount) * numberOrZero(reinsurer?.sharePct) / 100);
    const reinsurerLabel = stripFacilityTag(reinsurer?.name) || `Reinsurer ${splitIdx + 1}`;
    const settlementLabel = String(reinsurer?.foreignBroker || '').trim() || reinsurerLabel;
    const rootIdx = rootReinsurers.findIndex((row) => normalizedName(row?.name) === normalizedName(reinsurer?.name));
    const txBase = `${rootCase?.twRef}-C${claim?.id}-P${payment?.id}-R${splitIdx + 1}`;
    const common = {
      amount: shareAmount,
      splitParty: null,
      reinsurer: settlementLabel,
      viaForeignBroker: settlementLabel !== reinsurerLabel,
      settlement: 'open',
      reinsurerIdx: rootIdx >= 0 ? rootIdx : null,
      source: 'claim',
      claimId: claim?.id,
      paymentId: payment?.id,
      lossNo: claim?.lossNo || ''
    };
    transactions.push({
      ...common,
      txNo: `${txBase}-T1`,
      legType: 'Claim Leg 1',
      label: `Receivable — ${settlementLabel} owes reinsurance dept (claim ${lossLabel})`
    });
    transactions.push({
      ...common,
      txNo: `${txBase}-T2`,
      legType: 'Claim Leg 2',
      label: `Payable — reinsurance dept owes cedant unit (claim ${lossLabel})`
    });
  });
  return transactions;
}

export function reconciliationRefFor(caseData, transaction) {
  const leg = String(transaction?.legType || '');
  const isClaim = leg.startsWith('Claim');
  const cedantFacing = isClaim ? leg.startsWith('Claim Leg 2') : leg.startsWith('Leg 1');
  const reinsurerFacing = isClaim ? leg.startsWith('Claim Leg 1') : leg.startsWith('Leg 2');
  if (cedantFacing) return String(caseData?.statementNo || '');
  if (reinsurerFacing) {
    const index = Number.isInteger(transaction?.reinsurerIdx) ? transaction.reinsurerIdx : -1;
    return index >= 0 ? String(caseData?.reinsurers?.[index]?.settlementRef || '') : '';
  }
  return '';
}


// Premium period amounts use the same per-RI allocation as accounting T1/T2.
export function premiumPeriodAmounts(caseData) {
  const rows = caseData?.performanceInstallments || [];
  if (!rows.length) return [];
  let weights = rows.map(row => Math.max(0, Number(row.premium != null && row.premium !== '' ? row.premium : row.ratio) || 0));
  let sum = weights.reduce((a, b) => a + b, 0);
  if (sum <= 0) { weights = rows.map(() => 1); sum = rows.length; }
  const round = value => premiumMoney(value, caseData);
  const allocate = total => {
    const amounts = weights.map(w => round(total * w / sum));
    amounts[0] = round(amounts[0] + round(total - amounts.reduce((a, b) => a + b, 0)));
    if (total > 0 && amounts[0] < 0 && caseData?.premiumRounding !== 'legacy-cents') {
      let remainder = round(-amounts[0]); amounts[0] = 0;
      for (let i = 1; i < amounts.length && remainder > 0; i += 1) {
        const deduction = Math.min(amounts[i], remainder);
        amounts[i] = round(amounts[i] - deduction); remainder = round(remainder - deduction);
      }
    }
    return amounts;
  };
  const sums = rows.map(() => ({ leg1: 0, leg2: 0, leg3: 0 }));
  (caseData?.reinsurers || []).forEach(row => {
    const legs = calcLegsForReinsurer(caseData, row), a = allocate(legs.leg1), b = allocate(legs.leg2);
    sums.forEach((total, i) => { total.leg1 = round(total.leg1 + a[i]); total.leg2 = round(total.leg2 + b[i]); });
  });
  return sums.map(row => ({ ...row, leg3: round(row.leg1 - row.leg2) }));
}
