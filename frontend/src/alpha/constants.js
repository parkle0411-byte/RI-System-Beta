// 移植自 Alpha public/app.js 第 1–158 行（常數與共用小工具），內容逐項相同；只改成 ES module 的 export。
export const FIXED_TEXT = {
  interest: "The Reinsured's Insurance Interest in the Real and Personal Property of the Insured including Property whilst in their Care, Custody or Control.",
  reinsuredRetention: "Advice of Reinsured's retention waived.",
  standardNone: 'None - other than as may exist in this document or in the wording that forms part of this contract.'
};

export const STRUCTURE_SUFFIX = {
  QS: 'Facultative Reinsurance',
  XOL: 'Excess of Loss Facultative Reinsurance',
  TREATY: 'Reinsurance Treaty'
};

export const STRUCTURE_LABEL = { QS: 'Quota Share', XOL: 'Excess of Loss', TREATY: 'Treaty' };
export const UNIVERSAL_CLAUSES = [
  { code: 'LMA3333', title: 'Reinsurers Liability Clause' },
  { code: 'INTERMEDIARY', title: 'Intermediary Clause (TW Insurance Brokers Ltd.)' }
];
export const FX_CURRENCIES = ['USD', 'EUR', 'JPY', 'GBP', 'HKD', 'MYR'];
export const PERSONNEL_DEPARTMENTS = [
  { value: 'reinsurance', label: 'Reinsurance Dept.' },
  { value: 'finance', label: 'Finance Dept.' },
  { value: 'admin', label: 'Admin Dept.' },
  { value: 'business_1', label: 'Business Dept. 1' },
  { value: 'business_2', label: 'Business Dept. 2' },
  { value: 'special_risk', label: 'Special Risk Dept.' },
  { value: 'business_development', label: 'Business Development Dept.' }
];
export const PERSONNEL_ROLES = [
  { value: 'general_manager', label: 'General Manager' },
  { value: 'sales', label: 'Reinsurance Staff' },
  { value: 'accounting_manager', label: 'Finance Manager' },
  { value: 'accounting', label: 'Finance Staff' },
  { value: 'admin', label: 'System Administrator' },
  { value: 'viewer', label: 'Case Viewer' }
];
export const PERSONNEL_DEPARTMENT_ORDER = PERSONNEL_DEPARTMENTS.map((item) => item.value);
export const PERSONNEL_ROLE_ORDER = PERSONNEL_ROLES.map((item) => item.value);
export const DEFAULT_ROLE_BY_DEPARTMENT = {
  business_1: 'viewer', business_2: 'viewer', special_risk: 'viewer',
  business_development: 'viewer', reinsurance: 'sales',
  finance: 'accounting', admin: 'admin'
};
export function defaultSplitEligibility(department, roleCode) {
  return department !== 'finance' && department !== 'admin'
    && !(department === 'reinsurance' && roleCode === 'general_manager');
}

const navSvg = (body) => "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%23AF2D41' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>" + body + "</svg>";
export const NAV_ICONS = {
  dashboard: navSvg("<rect x='3' y='3' width='7' height='9' rx='1.5'/><rect x='14' y='3' width='7' height='5' rx='1.5'/><rect x='14' y='12' width='7' height='9' rx='1.5'/><rect x='3' y='16' width='7' height='5' rx='1.5'/>"),
  cases: navSvg("<path d='M4 4h16v16H4z'/><path d='M8 8h8M8 12h8M8 16h5'/>"),
  mdm: navSvg("<ellipse cx='12' cy='5' rx='8' ry='3'/><path d='M20 5v14c0 1.66-3.58 3-8 3s-8-1.34-8-3V5'/><path d='M20 12c0 1.66-3.58 3-8 3s-8-1.34-8-3'/>"),
  personnel: navSvg("<path d='M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2'/><circle cx='9' cy='7' r='4'/><path d='M23 21v-2a4 4 0 0 0-3-3.87'/>"),
  production: navSvg("<path d='M4 19V9M10 19V5M16 19v-7M22 19V3'/><path d='M2 19h21'/>"),
  accounting: navSvg("<rect x='4' y='2' width='16' height='20' rx='1.5'/><line x1='8' y1='7' x2='16' y2='7'/><line x1='8' y1='11' x2='16' y2='11'/><line x1='8' y1='15' x2='13' y2='15'/>"),
  fxrates: navSvg("<path d='M17 2l4 4-4 4'/><path d='M3 11V9a4 4 0 0 1 4-4h14'/><path d='M7 22l-4-4 4-4'/><path d='M21 13v2a4 4 0 0 1-4 4H3'/>"),
  recycle: navSvg("<path d='M3 6h18M8 6V4h8v2M6 6l1 15h10l1-15'/><path d='M10 10v7M14 10v7'/>"),
  reconciliation: navSvg("<path d='M4 12l5 5L20 6'/><path d='M4 4h10M4 20h16'/>"),
  audit: navSvg("<path d='M5 3h14v18H5z'/><path d='M9 8h6M9 12h6M9 16h4'/>")
};

export function normalizeClauseCode(value) { return String(value || '').trim().toUpperCase().replace(/\s+/g, '_').slice(0, 80); }
export function normalizeClauseList(value) {
  const seen = new Set();
  return (Array.isArray(value) ? value : [])
    .map((row) => ({ code: normalizeClauseCode(row?.code), title: String(row?.title || '').trim().slice(0, 300) }))
    .filter((row) => row.code && row.title && !seen.has(row.code) && seen.add(row.code));
}
export function compareClauses(a, b) {
  const codeA = normalizeClauseCode(a?.code);
  const codeB = normalizeClauseCode(b?.code);
  // Alpha #17：先 universal，再 LMA、NMA、LPO，其餘依字母（與 lib/case-draft.js 的順序相同）
  const rank = (code) => code === 'LMA3333' ? 0 : code === 'INTERMEDIARY' ? 1 : code.startsWith('LMA') ? 2 : code.startsWith('NMA') ? 3 : code.startsWith('LPO') ? 4 : 5;
  return rank(codeA) - rank(codeB) || codeA.localeCompare(codeB, 'en', { numeric: true, sensitivity: 'base' });
}
export function normalizeRatingList(value) {
  return (Array.isArray(value) ? value : []).map((row) => ({
    agency: String(row?.agency || '').trim().slice(0, 120),
    grade: String(row?.grade || '').trim().slice(0, 80),
    outlook: String(row?.outlook || '').trim().slice(0, 80),
    ratingType: String(row?.ratingType || '').trim().slice(0, 120),
    asOfDate: String(row?.asOfDate || '').trim().slice(0, 40),
    legalEntity: String(row?.legalEntity || '').trim().slice(0, 240),
    sourceUrl: String(row?.sourceUrl || '').trim().slice(0, 1000),
    checkedAt: String(row?.checkedAt || '').trim().slice(0, 80),
    status: String(row?.status || '').trim().slice(0, 80)
  })).filter((row) => row.agency && row.grade).slice(0, 50);
}

export function clientKey() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function currentMonth() {
  return new Date().toISOString().slice(0, 7);
}

export function emptyDraft() {
  return {
    ownerPersonnelId: null, ownerPersonnelName: '', parentTwRef: '', endorsementSeq: null,
    renewedFromTwRef: '', endoEffectiveDate: '', endoTypes: [], endoText: '',
    type: '', typePrefix: '', originalInsured: '', originalInsuredCn: '', reinsured: '',
    situations: [{ clientKey: clientKey(), address: '', postcode: '' }],
    classOfBusiness: '', classCode: '', reinsuranceStructure: '', policyFrom: '', policyFromTime: '12:00', policyTo: '', policyToTime: '12:00', currency: '',
    originalPremium: null, riCommPct: null, taxPct: null, paymentTermsDays: null,
    installmentEnabled: false, performanceInstallments: [], paymentScheduleReviewRequired: false, paymentEntries: [],
    splitEnabled: false,
    splitParties: [
      { clientKey: clientKey(), personnelId: null, name: '', pct: null },
      { clientKey: clientKey(), personnelId: null, name: '', pct: null }
    ],
    reinsurers: [{ clientKey: clientKey(), name: '', sharePct: null, premium: null, riCommPct: null, taxPct: null, paymentTermsDays: null, foreignBroker: '', settlementRef: '' }],
    sumInsured: [{ clientKey: clientKey(), category: '', amount: null, locationIndex: 0 }],
    lossAdvisedDate: '', lossRecordYears: null, lossRecord: [], lossRecordText: '',
    clauses: UNIVERSAL_CLAUSES.map((row) => row.code),
    clauseDetails: UNIVERSAL_CLAUSES.map((row) => ({ ...row })),
    autoClauses: [], manualClauses: [],
    status: 'draft',
    interest: FIXED_TEXT.interest,
    limitOfLiability: null,
    aggregateLimit: null,
    underlyingLimits: '',
    subLimits: '',
    deductibles: '',
    reinsuredRetention: FIXED_TEXT.reinsuredRetention,
    reinstatementProvisions: '',
    indemnityPeriod: '',
    originalExclusions: '',
    basisOfValuation: '',
    basisOfValuationOther: '',
    originalConditions: '',
    expressWarranties: FIXED_TEXT.standardNone,
    conditionsPrecedent: FIXED_TEXT.standardNone,
    subjectivities: FIXED_TEXT.standardNone,
    occupation: '', construction: '', lossPayee: '', notices: '', specialAgreement: '',
    ae: '', newOrRenew: '', exchRate: null, remark: '', postedAt: '',
    confirmedProductionKeys: [], productionExclusions: {}, endorsements: [], transactions: [], claims: [],
    statementNo: '', reversalCycle: 0, pendingReversalOffset: false, accountingNotifications: []
  };
}
