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

export function stripFacilityTag(value) {
  return String(value || '').replace(/\s*[[(]Facility[\])]\s*$/i, '').trim();
}

export function calcLegsForReinsurer(caseData, reinsurer) {
  const orderPct = numberOrZero(reinsurer?.sharePct);
  const caseCp = money(numberOrZero(caseData?.originalPremium) * orderPct / 100);
  const caseRi = money(caseCp * numberOrZero(caseData?.riCommPct) / 100);
  const caseTax = money(caseCp * numberOrZero(caseData?.taxPct) / 100);
  const leg1 = money(caseCp - caseRi - caseTax);

  const reinsurerCp = money(numberOrZero(reinsurer?.premium) * orderPct / 100);
  const reinsurerRi = money(reinsurerCp * numberOrZero(reinsurer?.riCommPct) / 100);
  const reinsurerTax = money(reinsurerCp * numberOrZero(reinsurer?.taxPct) / 100);
  const leg2 = money(reinsurerCp - reinsurerRi - reinsurerTax);
  const leg3 = money(leg1 - leg2);
  return { cp: caseCp, ri: caseRi, tax: caseTax, leg1, reinsurerCp, reinsurerRi, reinsurerTax, leg2, leg3, brokerage: leg3 };
}

export function buildPremiumTransactions(caseData) {
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
    const split = caseData?.splitEnabled === true && Array.isArray(caseData?.splitParties) && caseData.splitParties.length === 2;
    if (split) {
      caseData.splitParties.forEach((party, partyIdx) => {
        const suffix = partyIdx === 0 ? 'a' : 'b';
        const pct = numberOrZero(party?.pct);
        base.forEach((leg, legIdx) => transactions.push({
          txNo: `${caseData.twRef}-R${reinsurerIdx + 1}-TX${legIdx + 1}${suffix}`,
          legType: `${leg.legType}${suffix}`,
          label: `${leg.label} (${party?.name || 'Unassigned'}, ${pct}%)`,
          amount: money(leg.amount * pct / 100),
          splitParty: party?.name || `Party ${suffix.toUpperCase()}`,
          reinsurer: settlementLabel,
          viaForeignBroker: settlementLabel !== reinsurerLabel,
          settlement: 'open',
          reinsurerIdx
        }));
      });
    } else {
      base.forEach((leg, legIdx) => transactions.push({
        txNo: `${caseData.twRef}-R${reinsurerIdx + 1}-TX${legIdx + 1}`,
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
    const txBase = `${rootCase?.twRef}-CLM${claim?.id}-P${payment?.id}-R${splitIdx + 1}`;
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
      txNo: `${txBase}-TX1`,
      legType: 'Claim Leg 1',
      label: `Receivable — ${settlementLabel} owes reinsurance dept (claim ${lossLabel})`
    });
    transactions.push({
      ...common,
      txNo: `${txBase}-TX2`,
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