const MAX_ROWS = 50;
const STRUCTURE_SUFFIX = {
  QS: 'Facultative Reinsurance',
  XOL: 'Excess of Loss Facultative Reinsurance',
  TREATY: 'Reinsurance Treaty'
};
const UNIVERSAL_CLAUSES = [
  { code: 'LMA3333', title: 'Reinsurers Liability Clause' },
  { code: 'INTERMEDIARY', title: 'Intermediary Clause (TW Insurance Brokers Ltd.)' }
];

function text(value, max = 5000) {
  if (value === null || value === undefined) return '';
  return String(value).trim().slice(0, max);
}

function nullableNumber(value, label, errors, options = {}) {
  if (value === '' || value === null || value === undefined) return null;
  const number = Number(value);
  if (!Number.isFinite(number)) { errors.push(`${label} must be a valid number.`); return null; }
  if (options.min !== undefined && number < options.min) errors.push(`${label} must be at least ${options.min}.`);
  if (options.max !== undefined && number > options.max) errors.push(`${label} must not exceed ${options.max}.`);
  if (options.integer && !Number.isInteger(number)) errors.push(`${label} must be a whole number.`);
  return number;
}

function nullableDate(value, label, errors) {
  const result = text(value, 10);
  if (!result) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(result);
  const parsed = match ? new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))) : null;
  const exact = parsed && parsed.getUTCFullYear() === Number(match[1])
    && parsed.getUTCMonth() === Number(match[2]) - 1
    && parsed.getUTCDate() === Number(match[3]);
  if (!exact) {
    errors.push(`${label} must use YYYY-MM-DD.`);
    return null;
  }
  return result;
}

function rows(value, label, errors) {
  if (!Array.isArray(value)) return [];
  if (value.length > MAX_ROWS) errors.push(`${label} cannot contain more than ${MAX_ROWS} rows.`);
  return value.slice(0, MAX_ROWS);
}

function compatibleJson(value, fallback, label, errors, maxLength = 250000) {
  if (value === undefined || value === null) return fallback;
  try {
    const encoded = JSON.stringify(value);
    if (encoded.length > maxLength) {
      errors.push(`${label} is too large.`);
      return fallback;
    }
    return JSON.parse(encoded);
  } catch {
    errors.push(`${label} must contain valid JSON-compatible data.`);
    return fallback;
  }
}

function compatibleRows(value, label, errors, maxRows = 500) {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) {
    errors.push(`${label} must be a list.`);
    return [];
  }
  if (value.length > maxRows) errors.push(`${label} cannot contain more than ${maxRows} rows.`);
  return compatibleJson(value.slice(0, maxRows), [], label, errors);
}

function clauseCode(value) {
  return text(value, 80).toUpperCase().replace(/\s+/g, '_');
}

function clauseRows(value, label, errors) {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) { errors.push(`${label} must be a list.`); return []; }
  if (value.length > 100) errors.push(`${label} cannot contain more than 100 rows.`);
  const seen = new Set();
  const result = [];
  for (const row of value.slice(0, 100)) {
    const code = clauseCode(row?.code);
    const title = text(row?.title, 300);
    if (!code || !title) { errors.push(`Every ${label.toLowerCase()} row requires both a code and full name.`); continue; }
    if (seen.has(code)) { errors.push(`${label} contains duplicate code ${code}.`); continue; }
    seen.add(code);
    result.push({ code, title });
  }
  return result;
}

function compareClauses(a, b) {
  const rank = (code) => code === 'LMA3333' ? 0 : code === 'INTERMEDIARY' ? 1 : code.startsWith('LMA') ? 2 : code.startsWith('NMA') ? 3 : code.startsWith('LPO') ? 4 : 5;
  return rank(a.code) - rank(b.code) || a.code.localeCompare(b.code, 'en');
}

export function normalizeDraft(input) {
  const errors = [];
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    return { errors: ['case must be an object.'], value: null };
  }

  const situations = rows(input.situations, 'Situation', errors).map((row, index) => {
    const address = text(row?.address, 500);
    const postcode = text(row?.postcode, 6);
    if (postcode && !/^\d{3,6}$/.test(postcode)) errors.push(`Situation ${index + 1} postcode must be 3–6 digits.`);
    return { address, postcode };
  });

  const reinsurers = rows(input.reinsurers, 'Schedule of Security', errors).map((row, index) => ({
    name: text(row?.name, 240),
    sharePct: nullableNumber(row?.sharePct, `Reinsurer ${index + 1} Order hereon`, errors, { min: 0, max: 100 }),
    premium: nullableNumber(row?.premium, `Reinsurer ${index + 1} Premium`, errors, { min: 0 }),
    riCommPct: nullableNumber(row?.riCommPct, `Reinsurer ${index + 1} Deductions`, errors, { min: 0, max: 100 }),
    taxPct: nullableNumber(row?.taxPct, `Reinsurer ${index + 1} Tax`, errors, { min: 0, max: 100 }),
    paymentTermsDays: nullableNumber(row?.paymentTermsDays, `Reinsurer ${index + 1} Payment terms`, errors, { min: 15, integer: true }),
    foreignBroker: text(row?.foreignBroker, 240),
    settlementRef: text(row?.settlementRef, 160)
  }));

  const sumInsured = rows(input.sumInsured, 'Breakdown of Sum Insured', errors).map((row, index) => ({
    category: text(row?.category, 240),
    amount: nullableNumber(row?.amount, `Sum insured row ${index + 1} Amount`, errors, { min: 0 }),
    locationIndex: nullableNumber(row?.locationIndex, `Sum insured row ${index + 1} location`, errors, { min: 0, integer: true }) ?? 0
  }));

  const performanceInstallments = rows(input.performanceInstallments, 'Premium Installments', errors).map((row, index) => {
    const performanceMonth = text(row?.performanceMonth, 7);
    if (performanceMonth && !/^\d{4}-\d{2}$/.test(performanceMonth)) errors.push(`Installment ${index + 1} performance month must use YYYY-MM.`);
    return {
      id: text(row?.id, 100) || `I${index + 1}`,
      performanceMonth,
      paymentBaseDate: nullableDate(row?.paymentBaseDate, `Installment ${index + 1} payment base date`, errors) || '',
      paymentTermsDays: nullableNumber(row?.paymentTermsDays, `Installment ${index + 1} Payment terms`, errors, { min: 15, integer: true }),
      reinsurerPaymentTerms: compatibleJson(row?.reinsurerPaymentTerms, {}, `Installment ${index + 1} Reinsurer Payment terms`, errors),
      premium: nullableNumber(row?.premium, `Installment ${index + 1} Premium`, errors, { min: 0 }),
      ratio: nullableNumber(row?.ratio, `Installment ${index + 1} ratio`, errors, { min: 0, max: 100 })
    };
  });

  const rawSplitParties = rows(input.splitParties, 'Performance Split', errors);
  if (rawSplitParties.length > 2) errors.push('Performance Split cannot contain more than two people.');
  const splitParties = rawSplitParties.slice(0, 2).map((row, index) => ({
    personnelId: nullableNumber(row?.personnelId, `Performance Split person ${index + 1} ID`, errors, { min: 1, integer: true }),
    name: text(row?.name, 160),
    pct: nullableNumber(row?.pct, `Performance Split person ${index + 1} percentage`, errors, { min: 0, max: 100 })
  }));

  const lossRecord = rows(input.lossRecord, 'Loss Record', errors).map((row, index) => ({
    date: nullableDate(row?.date, `Loss ${index + 1} Date of Loss`, errors) || '',
    cause: text(row?.cause, 1000),
    lossPaid: nullableNumber(row?.lossPaid, `Loss ${index + 1} Loss Paid`, errors, { min: 0 })
  }));

  const effectiveDate = nullableDate(input.policyFrom, 'Effective date', errors);
  const expirationDate = nullableDate(input.policyTo, 'Expiration date', errors);
  const policyFromTime = text(input.policyFromTime, 5) || '12:00';
  const policyToTime = text(input.policyToTime, 5) || '12:00';
  if (!['00:00', '12:00'].includes(policyFromTime)) errors.push('Effective time must be 12:00 or 00:00.');
  if (!['00:00', '12:00'].includes(policyToTime)) errors.push('Expiration time must be 12:00 or 00:00.');
  if (effectiveDate && expirationDate && expirationDate < effectiveDate) errors.push('Expiration date cannot be earlier than Effective date.');

  const requestedStructure = text(input.reinsuranceStructure, 20).toUpperCase();
  const reinsuranceStructure = requestedStructure === 'FACULTATIVE' ? 'QS' : requestedStructure;
  if (reinsuranceStructure && !['QS', 'XOL', 'TREATY'].includes(reinsuranceStructure)) errors.push('Reinsurance structure must be Quota Share, Excess of Loss, or Treaty.');
  const suffix = STRUCTURE_SUFFIX[reinsuranceStructure] || '';
  const storedType = text(input.type, 200);
  let typePrefix = text(input.typePrefix, 120);
  if (!typePrefix && storedType) {
    typePrefix = suffix && storedType.endsWith(suffix)
      ? storedType.slice(0, -suffix.length).trim().slice(0, 120)
      : storedType.slice(0, 120);
  }
  const type = text(suffix ? (typePrefix ? `${typePrefix} ${suffix}` : suffix) : typePrefix, 200);

  const currency = text(input.currency, 3).toUpperCase();
  if (currency && !/^[A-Z]{3}$/.test(currency)) errors.push('Currency must be a three-letter code.');

  const basisOfValuation = text(input.basisOfValuation, 100);
  const manualClauses = clauseRows(input.manualClauses, 'Manual clauses', errors);
  const suppliedDetails = clauseRows(input.clauseDetails, 'Clause details', errors);
  const manualCodes = new Set(manualClauses.map((row) => row.code));
  for (const row of manualClauses) {
    if (UNIVERSAL_CLAUSES.some((base) => base.code === row.code)) errors.push(`${row.code} is universal and cannot be a manual clause.`);
  }
  const clauseMap = new Map(UNIVERSAL_CLAUSES.map((row) => [row.code, { ...row }]));
  suppliedDetails.forEach((row) => { if (!clauseMap.has(row.code)) clauseMap.set(row.code, row); });
  manualClauses.forEach((row) => { if (!clauseMap.has(row.code)) clauseMap.set(row.code, row); });
  const clauseDetails = Array.from(clauseMap.values()).sort(compareClauses);
  const universalCodes = new Set(UNIVERSAL_CLAUSES.map((row) => row.code));
  const autoClauses = clauseDetails
    .filter((row) => !universalCodes.has(row.code) && !manualCodes.has(row.code))
    .map((row) => row.code);
  const value = {
    ownerPersonnelId: nullableNumber(input.ownerPersonnelId, 'Case owner Personnel ID', errors, { min: 1, integer: true }),
    ownerPersonnelName: text(input.ownerPersonnelName, 160),
    parentTwRef: text(input.parentTwRef, 120),
    endorsementSeq: nullableNumber(input.endorsementSeq, 'Endorsement sequence', errors, { min: 0, integer: true }),
    renewedFromTwRef: text(input.renewedFromTwRef, 120),
    endoEffectiveDate: nullableDate(input.endoEffectiveDate, 'Endorsement effective date', errors) || '',
    endoTypes: compatibleRows(input.endoTypes, 'Endorsement types', errors, 20).map((item) => text(item, 120)).filter(Boolean),
    endoText: text(input.endoText, 5000),
    type,
    typePrefix,
    originalInsured: text(input.originalInsured, 240),
    originalInsuredCn: text(input.originalInsuredCn, 240),
    reinsured: text(input.reinsured, 240),
    situations: situations.length ? situations : [{ address: '', postcode: '' }],
    classOfBusiness: text(input.classOfBusiness, 160),
    classCode: text(input.classCode, 80),
    reinsuranceStructure,
    policyFrom: effectiveDate || '',
    policyFromTime: ['00:00', '12:00'].includes(policyFromTime) ? policyFromTime : '12:00',
    policyTo: expirationDate || '',
    policyToTime: ['00:00', '12:00'].includes(policyToTime) ? policyToTime : '12:00',
    currency,
    originalPremium: nullableNumber(input.originalPremium, '100% Premium', errors, { min: 0 }),
    riCommPct: nullableNumber(input.riCommPct, 'Ceding commission', errors, { min: 0, max: 100 }),
    taxPct: nullableNumber(input.taxPct, 'Cedant tax', errors, { min: 0, max: 100 }),
    paymentTermsDays: nullableNumber(input.paymentTermsDays, 'Payment terms', errors, { min: 15, integer: true }),
    installmentEnabled: input.installmentEnabled === true,
    performanceInstallments,
    splitEnabled: input.splitEnabled === true,
    splitParties,
    reinsurers: reinsurers.length ? reinsurers : [{ name: '', sharePct: null, premium: null, riCommPct: null, taxPct: null, paymentTermsDays: null, foreignBroker: '', settlementRef: '' }],
    sumInsured: sumInsured.length ? sumInsured : [{ category: '', amount: null, locationIndex: 0 }],
    lossAdvisedDate: nullableDate(input.lossAdvisedDate, 'Loss record advised date', errors) || '',
    lossRecordYears: nullableNumber(input.lossRecordYears, 'Loss record years', errors, { min: 0, integer: true }),
    lossRecord,
    lossRecordText: text(input.lossRecordText, 5000),
    clauses: clauseDetails.map((row) => row.code),
    clauseDetails,
    autoClauses,
    manualClauses,
    status: 'draft',
    interest: text(input.interest, 3000),
    limitOfLiability: nullableNumber(input.limitOfLiability, 'Limit of Liability', errors, { min: 0 }),
    aggregateLimit: nullableNumber(input.aggregateLimit, 'Aggregate Limit', errors, { min: 0 }),
    underlyingLimits: reinsuranceStructure === 'QS' ? '' : text(input.underlyingLimits, 3000),
    subLimits: text(input.subLimits, 3000),
    deductibles: text(input.deductibles, 3000),
    reinsuredRetention: text(input.reinsuredRetention, 3000),
    reinstatementProvisions: text(input.reinstatementProvisions, 3000),
    indemnityPeriod: text(input.indemnityPeriod, 1000),
    originalExclusions: text(input.originalExclusions, 5000),
    basisOfValuation,
    basisOfValuationOther: basisOfValuation === 'Other' ? text(input.basisOfValuationOther, 1000) : '',
    originalConditions: text(input.originalConditions, 5000),
    expressWarranties: text(input.expressWarranties, 3000),
    conditionsPrecedent: text(input.conditionsPrecedent, 3000),
    subjectivities: text(input.subjectivities, 3000),
    occupation: text(input.occupation, 3000),
    construction: text(input.construction, 3000),
    lossPayee: text(input.lossPayee, 3000),
    notices: text(input.notices, 5000),
    specialAgreement: text(input.specialAgreement, 5000),
    ae: text(input.ae, 160),
    newOrRenew: text(input.newOrRenew, 20),
    exchRate: nullableNumber(input.exchRate, 'Exchange rate', errors, { min: 0 }),
    remark: text(input.remark, 5000),
    postedAt: text(input.postedAt, 80),
    confirmedProductionKeys: compatibleRows(input.confirmedProductionKeys, 'Confirmed production keys', errors, 200)
      .map((key) => text(key, 240)).filter(Boolean),
    productionExclusions: compatibleJson(input.productionExclusions, {}, 'Production exclusions', errors),
    endorsements: compatibleRows(input.endorsements, 'Endorsements', errors),
    transactions: compatibleRows(input.transactions, 'Transactions', errors),
    claims: compatibleRows(input.claims, 'Claims', errors),
    statementNo: text(input.statementNo, 160),
    reversalCycle: nullableNumber(input.reversalCycle, 'Reversal cycle', errors, { min: 0, integer: true }) ?? 0,
    pendingReversalOffset: input.pendingReversalOffset === true || Number(input.pendingReversalOffset) === 1,
    accountingNotifications: compatibleRows(input.accountingNotifications, 'Accounting notifications', errors),
    paymentEntries: compatibleRows(input.paymentEntries, 'Payment entries', errors),
    paymentScheduleReviewRequired: input.paymentScheduleReviewRequired === true
  };

  return { errors, value, columns: { reinsuranceStructure: reinsuranceStructure || null, currency: currency || null, effectiveDate, expirationDate } };
}

function filled(value) {
  if (value === null || value === undefined) return false;
  if (typeof value === 'string') return value.trim() !== '';
  return true;
}

export function validateAnnounceReady(payload) {
  const issues = [];
  const add = (field, label) => issues.push({ field, label });
  const value = payload && typeof payload === 'object' ? payload : {};
  if (!Number.isInteger(Number(value.ownerPersonnelId)) || Number(value.ownerPersonnelId) < 1) add('ownerPersonnelId', 'Case Owner');
  [
    ['reinsuranceStructure', 'Reinsurance structure'], ['ae', 'AE'], ['currency', 'Currency'],
    ['classOfBusiness', 'Class'], ['newOrRenew', 'New / Renew'], ['type', 'Type'],
    ['reinsured', 'Reinsured'], ['originalInsured', 'Original insured (EN)'],
    ['policyFrom', 'Effective date'], ['policyTo', 'Expiration date'], ['interest', 'Interest']
  ].forEach(([field, label]) => { if (!filled(value[field])) add(field, label); });

  if (filled(value.parentTwRef)) {
    if (!filled(value.endoEffectiveDate)) add('endoEffectiveDate', 'Endorsement effective date');
    if (!Array.isArray(value.endoTypes) || !value.endoTypes.length) add('endoTypes', 'At least one endorsement type');
    if (!filled(value.endoText)) add('endoText', 'Endorsement wording');
  }

  const situations = Array.isArray(value.situations) ? value.situations : [];
  if (!situations.length) add('situations', 'Situation');
  situations.forEach((row, index) => {
    if (!filled(row?.address)) add(`situations.${index}.address`, `Situation ${index + 1} Risk Address`);
    if (!/^\d{3,6}$/.test(String(row?.postcode || '').trim())) add(`situations.${index}.postcode`, `Situation ${index + 1} Postcode`);
  });

  const reinsurers = Array.isArray(value.reinsurers) ? value.reinsurers : [];
  if (!reinsurers.length) add('reinsurers', 'Schedule of Security');
  reinsurers.forEach((row, index) => {
    if (!filled(row?.name)) add(`reinsurers.${index}.name`, `Reinsurer ${index + 1}`);
    if (!filled(row?.sharePct)) add(`reinsurers.${index}.sharePct`, `Reinsurer ${index + 1} Order hereon`);
    if (!filled(row?.premium)) add(`reinsurers.${index}.premium`, `Reinsurer ${index + 1} Premium`);
    if (!filled(row?.riCommPct)) add(`reinsurers.${index}.riCommPct`, `Reinsurer ${index + 1} Deductions`);
    if (!filled(row?.taxPct)) add(`reinsurers.${index}.taxPct`, `Reinsurer ${index + 1} Tax`);
  });

  if (!filled(value.limitOfLiability)) add('limitOfLiability', 'Limit of Liability');
  if (!filled(value.deductibles)) add('deductibles', 'Deductibles');
  if (!filled(value.originalConditions)) add('originalConditions', 'Original Conditions');
  if (value.basisOfValuation === 'Other' && !filled(value.basisOfValuationOther)) add('basisOfValuationOther', 'Basis of Valuation — Other');
  if (!filled(value.occupation)) add('occupation', 'Occupation');
  if (!filled(value.construction)) add('construction', 'Construction');

  const sumInsured = Array.isArray(value.sumInsured) ? value.sumInsured : [];
  if (!sumInsured.length) add('sumInsured', 'Breakdown of Sum Insured');
  sumInsured.forEach((row, index) => {
    if (!filled(row?.category)) add(`sumInsured.${index}.category`, `Sum insured ${index + 1} Interest insured`);
    if (!filled(row?.amount)) add(`sumInsured.${index}.amount`, `Sum insured ${index + 1} Amount`);
  });
  if (!filled(value.lossAdvisedDate)) add('lossAdvisedDate', 'Loss record advised by broker on');
  if (!Number.isInteger(Number(value.lossRecordYears)) || Number(value.lossRecordYears) <= 0) add('lossRecordYears', 'Loss history years');
  const lossRecord = Array.isArray(value.lossRecord) ? value.lossRecord : [];
  lossRecord.forEach((row, index) => {
    if (!filled(row?.date)) add(`lossRecord.${index}.date`, `Loss ${index + 1} Date of Loss`);
    if (!filled(row?.cause)) add(`lossRecord.${index}.cause`, `Loss ${index + 1} Cause`);
    if (!filled(row?.lossPaid)) add(`lossRecord.${index}.lossPaid`, `Loss ${index + 1} Loss Paid`);
  });

  [
    ['originalPremium', '100% Premium'], ['paymentTermsDays', 'Payment terms'],
    ['riCommPct', 'Ceding commission'], ['taxPct', 'Cedant tax']
  ].forEach(([field, label]) => { if (!filled(value[field])) add(field, label); });
  if (filled(value.paymentTermsDays) && Number(value.paymentTermsDays) < 15) add('paymentTermsDays', 'Payment terms of at least 15 calendar days');
  if (value.installmentEnabled) {
    const installmentRows = Array.isArray(value.performanceInstallments) ? value.performanceInstallments : [];
    if (!installmentRows.length) {
      add('performanceInstallments', 'At least one Premium Installment');
    } else {
      installmentRows.forEach((row, index) => {
        if (!/^\d{4}-\d{2}$/.test(String(row?.performanceMonth || ''))) add(`performanceInstallments.${index}.performanceMonth`, `Installment ${index + 1} performance month`);
        if (!/^\d{4}-\d{2}-\d{2}$/.test(String(row?.paymentBaseDate || ''))) add(`performanceInstallments.${index}.paymentBaseDate`, `Installment ${index + 1} payment base date`);
      });
      const totalPremium = Number(value.originalPremium || 0);
      if (totalPremium === 0) {
        const ratioTotal = installmentRows.reduce((sum, row) => sum + Number(row?.ratio || 0), 0);
        if (installmentRows.some((row) => Number(row?.ratio || 0) <= 0) || Math.abs(ratioTotal - 100) > 0.0001) add('performanceInstallments', 'Installment ratios greater than 0 totaling 100%');
      } else {
        const missingPremium = installmentRows.some((row) => row?.premium === null || row?.premium === undefined || !Number.isFinite(Number(row.premium)));
        const installmentTotal = installmentRows.reduce((sum, row) => sum + Number(row?.premium || 0), 0);
        if (missingPremium || Math.abs(installmentTotal - totalPremium) > 0.01) add('performanceInstallments', 'Installment Premium total equal to 100% Premium');
      }
    }
  }
  if (value.splitEnabled) {
    const parties = Array.isArray(value.splitParties) ? value.splitParties : [];
    if (parties.length !== 2) {
      add('splitParties', 'Exactly two Performance Split people');
    } else {
      const names = parties.map((row) => String(row?.name || '').trim().toLowerCase());
      if (names.some((name) => !name) || new Set(names).size !== 2) add('splitParties', 'Two different Performance Split people');
      const personnelIds = parties.map((row) => Number(row?.personnelId));
      if (personnelIds.some((id) => !Number.isInteger(id) || id < 1) || new Set(personnelIds).size !== 2) add('splitParties', 'Two different Personnel records for Performance Split');
      const percentages = parties.map((row) => Number(row?.pct));
      if (percentages.some((pct) => !Number.isFinite(pct) || pct <= 0)) add('splitParties', 'Performance Split percentages greater than 0');
      const total = percentages.reduce((sum, pct) => sum + (Number.isFinite(pct) ? pct : 0), 0);
      if (Math.abs(total - 100) > 0.0001) add('splitParties', 'Performance Split percentages totaling 100%');
    }
  }
  return issues;
}