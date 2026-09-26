const { createApp, ref, computed, reactive, onMounted, nextTick } = Vue;

const FIXED_TEXT = {
  interest: "The Reinsured's Insurance Interest in the Real and Personal Property of the Insured including Property whilst in their Care, Custody or Control.",
  reinsuredRetention: "Advice of Reinsured's retention waived.",
  standardNone: 'None - other than as may exist in this document or in the wording that forms part of this contract.'
};

const STRUCTURE_SUFFIX = {
  QS: 'Facultative Reinsurance',
  XOL: 'Excess of Loss Facultative Reinsurance',
  TREATY: 'Reinsurance Treaty'
};

const STRUCTURE_LABEL = { QS: 'Quota Share', XOL: 'Excess of Loss', TREATY: 'Treaty' };
const UNIVERSAL_CLAUSES = [
  { code: 'LMA3333', title: 'Reinsurers Liability Clause' },
  { code: 'INTERMEDIARY', title: 'Intermediary Clause (TW Insurance Brokers Ltd.)' }
];
const FX_CURRENCIES = ['USD', 'EUR', 'JPY', 'GBP', 'HKD', 'MYR'];
const PERSONNEL_DEPARTMENTS = [
  { value: 'reinsurance', label: 'Reinsurance Dept.' },
  { value: 'finance', label: 'Finance Dept.' },
  { value: 'admin', label: 'Admin Dept.' },
  { value: 'business_1', label: 'Business Dept. 1' },
  { value: 'business_2', label: 'Business Dept. 2' },
  { value: 'special_risk', label: 'Special Risk Dept.' },
  { value: 'business_development', label: 'Business Development Dept.' }
];
const PERSONNEL_ROLES = [
  { value: 'general_manager', label: 'General Manager' },
  { value: 'sales', label: 'Reinsurance Staff' },
  { value: 'accounting_manager', label: 'Finance Manager' },
  { value: 'accounting', label: 'Finance Staff' },
  { value: 'admin', label: 'System Administrator' },
  { value: 'viewer', label: 'Case Viewer' }
];
const PERSONNEL_DEPARTMENT_ORDER = PERSONNEL_DEPARTMENTS.map((item) => item.value);
const PERSONNEL_ROLE_ORDER = PERSONNEL_ROLES.map((item) => item.value);
const DEFAULT_ROLE_BY_DEPARTMENT = {
  business_1: 'viewer', business_2: 'viewer', special_risk: 'viewer',
  business_development: 'viewer', reinsurance: 'sales',
  finance: 'accounting', admin: 'admin'
};
function defaultSplitEligibility(department, roleCode) {
  return department !== 'finance' && department !== 'admin'
    && !(department === 'reinsurance' && roleCode === 'general_manager');
}

const navSvg = (body) => "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%23AF2D41' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>" + body + "</svg>";
const NAV_ICONS = {
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

function normalizeClauseCode(value) { return String(value || '').trim().toUpperCase().replace(/\s+/g, '_').slice(0, 80); }
function normalizeClauseList(value) {
  const seen = new Set();
  return (Array.isArray(value) ? value : [])
    .map((row) => ({ code: normalizeClauseCode(row?.code), title: String(row?.title || '').trim().slice(0, 300) }))
    .filter((row) => row.code && row.title && !seen.has(row.code) && seen.add(row.code));
}
function compareClauses(a, b) {
  const codeA = normalizeClauseCode(a?.code);
  const codeB = normalizeClauseCode(b?.code);
  // Bugfix (#17): this rank() collapsed LMA3333 into the generic "starts with
  // LMA" bucket and INTERMEDIARY into the A-Z catch-all, so the two universal
  // clauses (which must always sort first) could land anywhere among the LMA
  // clauses or alphabetically with everything else. Match the correct 5-tier
  // universal -> LMA -> NMA -> LPO -> A-Z ordering already implemented
  // correctly in lib/case-draft.js's compareClauses(), so Review/Overview
  // display order matches what the server actually computed and stored.
  const rank = (code) => code === 'LMA3333' ? 0 : code === 'INTERMEDIARY' ? 1 : code.startsWith('LMA') ? 2 : code.startsWith('NMA') ? 3 : code.startsWith('LPO') ? 4 : 5;
  return rank(codeA) - rank(codeB) || codeA.localeCompare(codeB, 'en', { numeric: true, sensitivity: 'base' });
}
function normalizeRatingList(value) {
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

function clientKey() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function previousMonth() {
  const date = new Date();
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() - 1, 1)).toISOString().slice(0, 7);
}

function currentMonth() {
  return new Date().toISOString().slice(0, 7);
}

function currentYear() {
  return new Date().toISOString().slice(0, 4);
}

function emptyDraft() {
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

createApp({
  setup() {
    const principal = ref(null);
    const authLoading = ref(true);
    const allNavigation = [
      { id: 'dashboard', label: 'Dashboard', icon: NAV_ICONS.dashboard, permission: 'dashboard.read' },
      { id: 'cases', label: 'Account List', icon: NAV_ICONS.cases, anyPermission: ['cases.read.all', 'cases.read.own'] },
      { id: 'mdm', label: 'Reinsurance MDM', icon: NAV_ICONS.mdm, permission: 'mdm.read' },
      { id: 'personnel', label: 'Personnel & Accounts', icon: NAV_ICONS.personnel, permission: 'personnel.read' },
      { id: 'production', label: 'Production Report', icon: NAV_ICONS.production, permission: 'production.read' },
      { id: 'accounting', label: 'Accounting', icon: NAV_ICONS.accounting, permission: 'accounting.read' },
      { id: 'fxrates', label: 'FX Rates', icon: NAV_ICONS.fxrates, permission: 'fx.read' },
      { id: 'recycle', label: 'Draft Recycle Bin', icon: NAV_ICONS.recycle, phase: '5 years', permission: 'recycle.read' },
      { id: 'audit', label: 'Audit Log', icon: NAV_ICONS.audit, phase: 'Read only', permission: 'audit.read' }
    ];
    const can = (permission) => Boolean(principal.value?.permissions?.includes(permission));
    const navigation = computed(() => allNavigation.filter((item) =>
      item.permission ? can(item.permission) : item.anyPermission?.some(can)
    ));

    const headers = {
      dashboard: { kicker: 'Operations', title: 'Dashboard', subtitle: 'Production & records overview' },
      cases: { kicker: 'Placement', title: 'Account List', subtitle: 'All facultative outward cases' },
      recycle: { kicker: 'Placement governance', title: 'Draft Recycle Bin', subtitle: 'Five-year restore window · permanent deletion prohibited', phase: 'Retained' },
      'case-create': { kicker: 'Placement · Draft', title: 'Account', subtitle: 'Draft — not yet saved' },
      'case-detail': { kicker: 'Placement · Case', title: 'Case overview', subtitle: 'Saved case snapshot and computed amounts' },
      mdm: { kicker: 'Master data', title: 'Reinsurance MDM', subtitle: 'Versioned master records, fixed clauses and lifecycle controls', phase: 'Milestone 11' },
      personnel: { kicker: 'Administration', title: 'Personnel & Accounts', subtitle: 'Unified personnel, future accounts and target settings', phase: 'Milestone 21' },
      production: { kicker: 'Reporting', title: 'Production Report', subtitle: 'Monthly read-only production preview', phase: 'Milestone 19' },
      accounting: { kicker: 'Accounting', title: 'Accounting', subtitle: 'Statement of account, transactions and settlement', phase: 'Milestone 22' },
      fxrates: { kicker: 'Master data', title: 'FX Rates', subtitle: 'Official monthly USD to TWD rates', phase: 'Milestone 20' },
      reconciliation: { kicker: 'Conversion control', title: 'Data reconciliation', subtitle: 'Source authority, control totals and cutover gates', phase: 'Import disabled' },
      audit: { kicker: 'Governance', title: 'Audit Log', subtitle: 'Append-only activity history with at least 10-year retention', phase: 'Read only' }
    };

    const pendingCopy = {
      mdm: 'Reinsurance MDM will become the source for reinsurers, reinsureds, classes, AE records and fixed clauses.',
      personnel: 'Personnel, user activation and role visibility will be migrated with the new authentication and audit design.',
      production: 'Production Report rules will be migrated after the case and endorsement data contracts are stable.',
      accounting: 'Confirmed cases generate Development-compatible transaction cycles; settlement is controlled from the consolidated ledger.',
      fxrates: 'Monthly exchange-rate management will be migrated as relational master data with role-based editing.'
    };

    const roadmap = [
      { name: 'Application shell', description: 'Vue 3 navigation, responsive layout and shared insurance visual tokens.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Account List', description: 'Original-placement list backed by the new ri_cases table.', state: 'ready', stateLabel: 'Ready' },
      { name: 'New case · draft', description: 'Property sections, repeatable rows, safe draft persistence and audit snapshot.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Review readiness', description: 'Required fields, immediate error clearing, section expansion and first-error focus.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Case review summary', description: 'A read-only confirmation step before a complete Property draft is saved.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Draft editing', description: 'Open an existing Draft, save a new version, and preserve snapshot and Audit Log history.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Reinsurance MDM', description: 'Central lists for AE, Reinsurer, Reinsured, Class, and Foreign RI Broker with audited creation.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Case MDM selectors', description: 'Case fields use active master records while preserving historical snapshot values.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Foreign RI Broker selector', description: 'Schedule of Security uses the broker master while older free-text values remain available.', state: 'ready', stateLabel: 'Ready' },
      { name: 'MDM lifecycle', description: 'Master records support versioned editing, deactivation, and reactivation without physical deletion.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Placement structures', description: 'Quota Share, Excess of Loss, and Treaty drive a locked Type suffix matching the reference workflow.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Fixed clauses', description: 'Reinsurer clauses flow into new case snapshots with universal and manual Reinsurance Conditions.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Case overview', description: 'Account List opens a Vue case-detail view with risk, security, clause, Avg. Rate and Leg 1–3 summaries.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Placement documents', description: 'Upload, select, download and remove placement evidence with per-reinsurer Announce readiness.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Review & Announce', description: 'Server-validated evidence attestation, atomic TW Reference assignment, status transition, snapshot and Audit Log.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Layered terms', description: 'Aggregate limit, underlying limits, sub-limits, reinstatement provisions and indemnity period persist in case snapshots.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Premium installments', description: 'Optional performance months allocate premium and calculated brokerage income with server-validated totals.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Performance Split', description: 'Two distinct internal people share production credit by validated percentages totaling 100%.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Per-loss records', description: 'Loss history stores one dated cause and paid amount per loss with automatic clean/loss wording.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Production Report lifecycle', description: 'Monthly preview, exclusion/defer, immutable versions, XLSX download, source validation, FX lock and automatic Confirmed status on close.', state: 'ready', stateLabel: 'Ready' },
      { name: 'FX Rates', description: 'Audited monthly USD to TWD rates feed Production Report previews; TWD remains fixed at 1.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Personnel & Accounts', description: 'Unified personnel records, account assignments, Performance Split identities and annual targets.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Endorsement, Renewal & Accounting notice', description: 'Latest-chain endorsement Drafts, Confirmed-case renewals, Announced edits and non-blocking Accounting notification records.', state: 'ready', stateLabel: 'Ready' },
      { name: 'SoA, Transactions & Reversal', description: 'Production close creates Leg 1–3 entries; Accounting settles open items; reversal preserves history and appends offset/corrected cycles.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Data conversion controls', description: 'Source classification, field mapping, target integrity, financial totals and cutover gates without importing reference data.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Draft Recycle Bin', description: 'Drafts can be recycled and restored for five years; no role or UI can permanently delete them.', state: 'ready', stateLabel: 'Ready' },
      { name: 'Role permissions', description: 'The approved permission matrix and account metadata are staged; RI login and account activation are deferred.', state: 'pending', stateLabel: 'Staged' }
    ];

    const activeView = ref('dashboard');
    const loading = ref(true);
    const saving = ref(false);
    const error = ref('');
    const saveMessage = ref('');
    const reviewAttempted = ref(false);
    const reviewDialogVisible = ref(false);
    const editingCaseUid = ref('');
    const editingRowVersion = ref(null);
    const editingOriginalStatus = ref('draft');
    const endorsementFieldsUnlocked = ref(false);
    const mdmLoading = ref(false);
    const mdmSaving = ref(false);
    const mdmDialogVisible = ref(false);
    const editingMasterId = ref(null);
    const editingMasterRowVersion = ref(null);
    const activeMdmType = ref('reinsurer');
    const mdmRecords = ref([]);
    const mdmCounts = ref({ ae: 0, reinsurer: 0, reinsured: 0, class: 0, foreign_broker: 0, clause: 0 });
    const mdmForm = reactive({ entityType: 'ae', code: '', name: '', abbreviation: '', address: '', fixedClauses: [], ratings: [] });
    const mdmClauseDraft = reactive({ code: '', title: '' });
    const mdmRatingDraft = reactive({ agency: '', grade: '', outlook: '', ratingType: '', asOfDate: '', legalEntity: '', sourceUrl: '', checkedAt: '', status: '' });
    const caseClauseDraft = reactive({ code: '', title: '' });
    const selectedCase = ref(null);
    const casePreviewVisible = ref(false);
    const casePreview = ref(null);
    const caseDetailLoading = ref(false);
    const caseDetailTab = ref('overview');
    const documentsLoading = ref(false);
    const documentsSaving = ref(false);
    const documentGenerating = ref('');
    const caseDocuments = ref([]);
    const documentCoverage = ref({ offer: false, required: [], covered: [], missing: [], ready: false, selected: [] });
    const signedSlipReminder = ref({ complete: false, missing: [], eligibleStatus: false, daysSinceEffective: null, firstReminderOn: '', due: false, today: '', cadenceDays: 7, outboundEnabled: false });
    const documentForm = reactive({ kind: 'offer', reinsurers: [], file: null });
    const documentFileList = ref([]);
    const caseWorkflow = ref(null);
    const workflowLoading = ref(false);
    const workflowSaving = ref(false);
    const accountingDialogVisible = ref(false);
    const accountingForm = reactive({ accountingPersonnelId: null, note: '' });
    const accountingLoading = ref(false);
    const accountingSaving = ref(false);
    const accountingRows = ref([]);
    const accountingCurrencies = ref([]);
    const accountingScope = ref({ canEdit: false });
    const accountingSelection = ref([]);
    const accountingFilters = reactive({ ref: '', reinsurer: '', currency: '', from: '', to: '', leg: '', settlement: '' });
    const accountingPaymentDialogVisible = ref(false);
    const accountingPaymentRow = ref(null);
    const schedulePaymentForm = reactive({ paymentDate: new Date().toISOString().slice(0, 10), amount: null, note: '' });
    const claimsLoading = ref(false);
    const claimsSaving = ref(false);
    const claimsState = ref({ rootCaseUid: '', rootTwRef: '', rootStatus: '', rootRowVersion: null, currency: '', claims: [], splitSource: { reinsurers: [] }, actions: { canWrite: false } });
    const claimForm = reactive({ lossNo: '', dateOfLoss: '', outstandingReserve: null, causeOfLoss: '' });
    const paymentDialogVisible = ref(false);
    const activeClaimId = ref(null);
    const paymentForm = reactive({ date: '', amount: null, note: '' });
    const announceDialogVisible = ref(false);
    const announceConfirmed = ref(false);
    const announcing = ref(false);
    const dashboardLoading = ref(false);
    const dashboard = ref({ period: { year: currentYear(), currentMonth: currentMonth(), monthNumber: 1 }, metrics: {}, brokerage: { labels: [], current: [], prior: [], target: [], annualTarget: null }, classMix: [], reinsurers: [] });
    const productionLoading = ref(false);
    const productionSaving = ref('');
    const productionMonth = ref(previousMonth());
    const productionPreview = ref({
      headers: [], rows: [], excluded: [], versions: [], sourceSignature: '',
      summary: { rowCount: 0, excludedRowCount: 0, premiumNtd: 0, incomeNtd: 0, missingRateCurrencies: [] },
      scope: { readOnly: false, canOperate: false, canClose: false, monthClosed: false, fxLocked: false, canGenerate: false, canCloseLatest: false }
    });
    const fxLoading = ref(false);
    const fxSaving = ref(false);
    const fxDialogVisible = ref(false);
    const fxRates = ref([]);
    const fxForm = reactive({
      yearMonth: currentMonth(),
      existingMonth: false,
      rates: FX_CURRENCIES.map((currency) => ({ currency, rate: null, rowVersion: null, isLocked: false }))
    });
    const auditLoading = ref(false);
    const auditEvents = ref([]);
    const reconciliationLoading = ref(false);
    const reconciliation = ref({
      sourceAuthority: {}, referenceSources: [], entityMap: [],
      target: { counts: {}, caseCounts: {}, masterCounts: {}, premiumControls: [], transactionControls: [], integrityIssues: [] },
      migration: { batches: 0, items: 0, reconciled: 0, errors: 0 }, gates: []
    });
    const personnelLoading = ref(false);
    const personnelSaving = ref(false);
    const personnelDialogVisible = ref(false);
    const personnelRecords = ref([]);
    const sortedPersonnelRecords = computed(() => {
      const deptRank = (dept) => {
        const idx = PERSONNEL_DEPARTMENT_ORDER.indexOf(dept);
        return idx === -1 ? PERSONNEL_DEPARTMENT_ORDER.length : idx;
      };
      const roleRank = (role) => {
        const idx = PERSONNEL_ROLE_ORDER.indexOf(role);
        return idx === -1 ? PERSONNEL_ROLE_ORDER.length : idx;
      };
      return personnelRecords.value.slice().sort((a, b) => {
        const deptDiff = deptRank(a.department) - deptRank(b.department);
        if (deptDiff !== 0) return deptDiff;
        const roleDiff = roleRank(a.roleCode) - roleRank(b.roleCode);
        if (roleDiff !== 0) return roleDiff;
        return String(a.name || '').localeCompare(String(b.name || ''));
      });
    });
    const personnelCounts = ref({ total: 0, active: 0, splitEligible: 0, accountsActive: 0 });
    const personnelTab = ref('roster');
    const editingPersonnelId = ref(null);
    const editingPersonnelRowVersion = ref(null);
    const personnelForm = reactive({
      name: '', email: '', department: 'reinsurance', roleCode: 'sales',
      isActive: false, isSplitEligible: false, supervisorName: '', supervisorEmail: ''
    });
    const supervisorOptions = computed(() => personnelRecords.value
      .filter((person) => person.isActive
        && (person.department === personnelForm.department || person.roleCode === 'general_manager')
        && Number(person.id) !== Number(editingPersonnelId.value))
      .slice()
      .sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''))));
    const targetLoading = ref(false);
    const targetSaving = ref(false);
    const targetDialogVisible = ref(false);
    const dashboardTargets = ref([]);
    const targetForm = reactive({
      id: null, periodType: 'annual', periodKey: currentYear(),
      amount: null, rowVersion: null, isActive: true
    });
    const masterTypes = [
      { value: 'reinsurer', label: 'Reinsurer', tabLabel: 'Reinsurers' },
      { value: 'clause', label: 'Clause', tabLabel: 'Clauses' },
      { value: 'reinsured', label: 'Cedant', tabLabel: 'Cedants' },
      { value: 'foreign_broker', label: 'Foreign RI Broker', tabLabel: 'Foreign RI Brokers' },
      { value: 'ae', label: 'Account Executive', tabLabel: 'Account Executive' },
      { value: 'class', label: 'Class', tabLabel: 'Classes' }
    ];
    const cases = ref([]);
    const recycleLoading = ref(false);
    const recycleSaving = ref(false);
    const recycleItems = ref([]);
    const recyclePolicy = ref({ retentionYears: 5, permanentDeleteAllowed: false });
    const summary = ref({ total: 0, draft: 0, posted: 0, closed: 0, reversed: 0 });
    const filters = reactive({ search: '', status: 'all', year: 'all', className: 'all', reinsurer: 'all', reinsured: 'all', aeName: 'all' });
    const draft = reactive(emptyDraft());
    const openSections = ref(['risk','security','terms','occupation','sumInsured','loss','specialAgreement','cedantPremium','reinsurerPremium','split','conditions']);
    const reviewReady = computed(() => reviewAttempted.value && collectRequiredIssues().length === 0);
    const validationMessage = computed(() => {
      if (!reviewAttempted.value) return '';
      const count = collectRequiredIssues().length;
      return count === 0
        ? 'All required fields are complete. This draft is ready for the confirmation workflow milestone.'
        : `Please complete ${count} required field${count === 1 ? '' : 's'} before Review & confirm.`;
    });
    const totalOrderHereon = computed(() => RICaseCalculations.totalOrderHereon(draft));
    const isFacilityName = (name) => /\(Facility\)\s*$/i.test(String(name || '').trim());
    const selectedDraftReinsurers = computed(() => draft.reinsurers.filter((row) => String(row.name || '').trim()));
    const allFacilityReinsurers = computed(() => selectedDraftReinsurers.value.length > 0 && selectedDraftReinsurers.value.every((row) => isFacilityName(row.name)));
    const hasNonFacilityReinsurer = computed(() => selectedDraftReinsurers.value.some((row) => !isFacilityName(row.name)));
    const totalSumInsured = computed(() => RICaseCalculations.totalSumInsured(draft));
    const lossRecordSummary = computed(() => lossRecordSummaryFor(draft));
    const installmentAllocations = computed(() => installmentAllocationsFor(draft));
    const installmentStatus = computed(() => installmentValidationFor(draft));
    const splitStatus = computed(() => splitValidationFor(draft));

    const isEditing = computed(() => Boolean(editingCaseUid.value));
    const isEndorsementDraft = computed(() => Boolean(draft.parentTwRef));
    const selectedPayload = computed(() => selectedCase.value?.payload || {});
    const selectedOverview = computed(() => {
      const payload = selectedPayload.value;
      const legs = RICaseCalculations.totals(payload);
      const flipped = legs.leg1 < 0;
      return {
        totalOrderHereon: RICaseCalculations.totalOrderHereon(payload),
        totalSumInsured: RICaseCalculations.totalSumInsured(payload),
        avgRate: RICaseCalculations.avgRateText(payload),
        legs,
        legLabels: flipped
          ? { leg1: 'Net Premium to Cedant', leg2: 'Net Premium from Reinsurer' }
          : { leg1: 'Net Premium from Cedant', leg2: 'Net Premium to Reinsurer' },
        displayLegs: {
          leg1: flipped ? Math.abs(legs.leg1) : legs.leg1,
          leg2: flipped ? Math.abs(legs.leg2) : legs.leg2,
          leg3: flipped ? Math.abs(legs.leg3) : legs.leg3
        },
        installments: installmentAllocationsFor(payload),
        lossRecordSummary: lossRecordSummaryFor(payload),
        clauseDetails: normalizeClauseList(payload.clauseDetails?.length ? payload.clauseDetails : UNIVERSAL_CLAUSES).sort(compareClauses)
      };
    });
    const generatedDocumentCase = computed(() => {
      const payload = selectedPayload.value || {};
      const normalizedReinsured = String(payload.reinsured || '').trim().toLowerCase();
      const reinsuredMaster = mdmRecords.value.find((row) =>
        row.entityType === 'reinsured' && String(row.name || '').trim().toLowerCase() === normalizedReinsured
      );
      const aeName = String(payload.ae || '').trim().toLowerCase();
      const aePerson = personnelRecords.value.find((row) => String(row.name || '').trim().toLowerCase() === aeName);
      return {
        ...payload,
        caseUid: selectedCase.value?.caseUid || '',
        twRef: selectedCase.value?.twRef || payload.twRef || '',
        status: selectedCase.value?.status || payload.status || 'draft',
        reinsuredAddress: payload.reinsuredAddress || reinsuredMaster?.payload?.address || '',
        aeEmail: payload.aeEmail || aePerson?.email || '',
        clauseDetails: selectedOverview.value.clauseDetails
      };
    });
    const selectedReinsurers = computed(() => {
      const seen = new Set();
      return (Array.isArray(selectedPayload.value.reinsurers) ? selectedPayload.value.reinsurers : [])
        .map((row) => ({ key: reinsurerKey(row?.name), label: String(row?.name || '').trim() }))
        .filter((row) => row.key && !seen.has(row.key) && seen.add(row.key));
    });
    const documentReadinessText = computed(() => {
      const coverage = documentCoverage.value;
      if (coverage.ready) return 'Documents complete. This case is ready for the Review & Announce confirmation step.';
      const needs = [];
      if (!coverage.offer) needs.push('Offer Slip');
      if ((coverage.missing || []).length) needs.push(`Signed Slip or Confirmation E-mail for ${coverage.missing.map(displayReinsurerName).join(', ')}`);
      if (!coverage.required?.length) needs.push('at least one named reinsurer in Schedule of Security');
      return `Not ready to Announce. Missing ${needs.join('; ')}.`;
    });
    const selectedAnnounceIssues = computed(() => collectPayloadAnnounceIssues(selectedPayload.value));
    const caseDetailTabLabel = computed(() => ({ documents: 'Cover & Debit Note', soa: 'SOA / Transactions', claims: 'Claim', endorsements: 'Endorsements' }[caseDetailTab.value] || 'Case detail'));
    function reconciliationRefFor(caseData, transaction) {
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
    const selectedCaseTransactions = computed(() => (Array.isArray(selectedPayload.value.transactions) ? selectedPayload.value.transactions : []).map((transaction, index) => ({
      ...transaction,
      key: `${transaction.txNo || 'transaction'}:${index}`,
      sourceLabel: transaction.source === 'claim' ? 'Claim' : 'Premium',
      reconciliationRef: reconciliationRefFor(selectedPayload.value, transaction),
      settlement: transaction.source === 'claim'
        ? (transaction.settlement === 'settled' ? 'settled' : 'open')
        : (transaction.paymentScheduleSettlement || 'not_tracked')
    })));
    const filteredAccountingRows = computed(() => accountingRows.value.filter((row) => {
      const filters = accountingFilters;
      if (filters.ref && !String(row.twRef || '').toLowerCase().includes(filters.ref.toLowerCase())) return false;
      if (filters.reinsurer && !String(row.reinsurer || '').toLowerCase().includes(filters.reinsurer.toLowerCase())) return false;
      if (filters.currency && row.currency !== filters.currency) return false;
      if (filters.leg && String(row.legType || '') !== filters.leg && !String(row.legType || '').startsWith(filters.leg)) return false;
      if (filters.settlement && row.settlement !== filters.settlement) return false;
      const announced = String(row.announcedAt || '').slice(0, 10);
      if (filters.from && announced && announced < filters.from) return false;
      if (filters.to && announced && announced > filters.to) return false;
      return true;
    }));
    const currentHeader = computed(() => {
      if (activeView.value === 'case-create' && isEditing.value) {
        return { ...headers['case-create'], kicker: 'Placement · Draft', title: draft.parentTwRef ? 'New endorsement' : 'Account', subtitle: draft.parentTwRef ? ('Endorsement to ' + draft.parentTwRef) : 'Draft — versioned update' };
      }
      if (activeView.value === 'case-detail' && selectedCase.value) {
        const payload = selectedPayload.value;
        return {
          ...headers['case-detail'],
          title: selectedCase.value.twRef || 'Draft · not assigned',
          subtitle: `${payload.originalInsured || 'Unnamed case'} · ${statusLabel(selectedCase.value.status)}`
        };
      }
      return headers[activeView.value] || headers.dashboard;
    });
    const pendingDescription = computed(() => pendingCopy[activeView.value] || 'This screen is queued for migration.');
    const caseSummary = computed(() => ({
      total: Number(summary.value.total || 0), draft: Number(summary.value.draft || 0),
      posted: Number(summary.value.posted || 0), closed: Number(summary.value.closed || 0), reversed: Number(summary.value.reversed || 0)
    }));
    function caseFilterOptions(field) {
      const values = field === 'reinsurer'
        ? cases.value.flatMap((row) => (Array.isArray(row.reinsurers) ? row.reinsurers : []).map((value) => String(value || '').trim()).filter(Boolean))
        : cases.value.map((row) => field === 'year'
          ? String(row.effectiveDate || row.updatedAt || '').slice(0, 4)
          : String(row[field] || '').trim()).filter(Boolean);
      return Array.from(new Set(values)).sort((a, b) => a.localeCompare(b, 'en'));
    }
    const filteredCases = computed(() => {
      const needle = filters.search.trim().toLowerCase();
      return cases.value.filter((row) => {
        if (filters.status !== 'all' && row.status !== filters.status) return false;
        if (filters.year !== 'all' && String(row.effectiveDate || row.updatedAt || '').slice(0, 4) !== filters.year) return false;
        if (filters.className !== 'all' && row.className !== filters.className) return false;
        if (filters.reinsured !== 'all' && row.reinsured !== filters.reinsured) return false;
        if (filters.aeName !== 'all' && row.aeName !== filters.aeName) return false;
        if (filters.reinsurer !== 'all' && !(Array.isArray(row.reinsurers) ? row.reinsurers : []).includes(filters.reinsurer)) return false;
        if (!needle) return true;
        return [row.twRef, row.originalInsured, row.originalInsuredCn, row.reinsured, row.className, row.aeName, ...(Array.isArray(row.reinsurers) ? row.reinsurers : [])]
          .some((value) => String(value || '').toLowerCase().includes(needle));
      });
    });
    const filteredMasterRecords = computed(() => {
      const records = mdmRecords.value.filter((row) => row.entityType === activeMdmType.value);
      return activeMdmType.value === 'clause' ? [...records].sort(compareClauses) : records;
    });

    function dashboardTrendValues() {
      return [
        ...(dashboard.value?.brokerage?.current || []),
        ...(dashboard.value?.brokerage?.prior || []),
        ...(dashboard.value?.brokerage?.target || [])
      ].map(Number).filter(Number.isFinite);
    }
    function dashboardTrendMax() {
      return Math.max(1, ...dashboardTrendValues());
    }
    function dashboardTrendX(index, total) {
      if (total <= 1) return 450;
      return 92 + (index * 778 / (total - 1));
    }
    function dashboardTrendY(value) {
      return 184 - (Math.max(0, Number(value || 0)) / dashboardTrendMax() * 150);
    }
    function dashboardTrendPoints(series) {
      const values = Array.isArray(series) ? series : [];
      return values.map((value, index) => dashboardTrendX(index, values.length) + ',' + dashboardTrendY(value)).join(' ');
    }
    function dashboardTrendSeries(series) {
      const values = Array.isArray(series) ? series : [];
      return values.map((value, index) => ({
        x: dashboardTrendX(index, values.length),
        y: dashboardTrendY(value),
        value: Number(value || 0)
      }));
    }

    function round2(value) {
      const number = Number(value);
      return Math.round(((Number.isFinite(number) ? number : 0) + Number.EPSILON) * 100) / 100;
    }

    function installmentAllocationsFor(caseData) {
      if (!caseData?.installmentEnabled) return [];
      const rows = Array.isArray(caseData.performanceInstallments) ? caseData.performanceInstallments : [];
      const totalPremium = Number(caseData.originalPremium || 0);
      const income = Number(RICaseCalculations.totals(caseData).brokerage || 0);
      const allocations = rows.map((row) => {
        const ratio = totalPremium === 0 ? Number(row?.ratio || 0) / 100 : Number(row?.premium || 0) / totalPremium;
        return {
          ...row,
          premium: totalPremium === 0 ? 0 : Number(row?.premium || 0),
          ratio,
          income: round2(income * ratio)
        };
      });
      if (allocations.length) {
        const tail = round2(income - allocations.reduce((sum, row) => sum + row.income, 0));
        allocations[0].income = round2(allocations[0].income + tail);
      }
      return allocations;
    }

    function installmentValidationFor(caseData) {
      if (!caseData?.installmentEnabled) return { valid: true, message: '' };
      const rows = Array.isArray(caseData.performanceInstallments) ? caseData.performanceInstallments : [];
      if (!rows.length) return { valid: false, message: 'Add at least one installment.' };
      if (rows.some((row) => !/^\d{4}-\d{2}$/.test(String(row?.performanceMonth || '')))) return { valid: false, message: 'Every installment needs a performance month.' };
      if (rows.some((row) => !/^\d{4}-\d{2}-\d{2}$/.test(String(row?.paymentBaseDate || '')))) return { valid: false, message: 'Every installment needs a payment base date.' };
      const totalPremium = Number(caseData.originalPremium || 0);
      if (totalPremium === 0) {
        const sum = rows.reduce((total, row) => total + Number(row?.ratio || 0), 0);
        if (rows.some((row) => Number(row?.ratio || 0) <= 0) || Math.abs(sum - 100) > 0.0001) return { valid: false, message: 'Installment ratios must be greater than 0 and total 100%.' };
      } else {
        const invalid = rows.some((row) => row?.premium === '' || row?.premium === null || row?.premium === undefined || !Number.isFinite(Number(row.premium)));
        if (invalid) return { valid: false, message: 'Enter the Premium for every installment.' };
        const sum = rows.reduce((total, row) => total + Number(row.premium), 0);
        if (Math.abs(sum - totalPremium) > 0.01) return { valid: false, message: 'Installment Premium total must equal 100% Premium.' };
      }
      return { valid: true, message: 'Installment allocation is complete.' };
    }

    function addInstallment() {
      draft.performanceInstallments.push({ clientKey: clientKey(), id: `I${Date.now()}-${Math.random().toString(36).slice(2, 6)}`, performanceMonth: '', paymentBaseDate: '', paymentTermsDays: null, reinsurerPaymentTerms: {}, premium: null, ratio: null });
    }
    function removeInstallment(index) { draft.performanceInstallments.splice(index, 1); }
    function onInstallmentToggle(enabled) { if (enabled && !draft.performanceInstallments.length) addInstallment(); }
    function installmentRowInvalid(index, key) {
      if (!reviewAttempted.value || !draft.installmentEnabled) return false;
      const row = draft.performanceInstallments[index] || {};
      if (key === 'performanceMonth') return !/^\d{4}-\d{2}$/.test(String(row.performanceMonth || ''));
      if (key === 'paymentBaseDate') return !/^\d{4}-\d{2}-\d{2}$/.test(String(row.paymentBaseDate || ''));
      if (key === 'ratio') return Number(row.ratio || 0) <= 0;
      return row.premium === '' || row.premium === null || row.premium === undefined || !Number.isFinite(Number(row.premium));
    }

    function splitValidationFor(caseData) {
      if (!caseData?.splitEnabled) return { valid: true, message: '' };
      const parties = Array.isArray(caseData.splitParties) ? caseData.splitParties : [];
      if (parties.length !== 2) return { valid: false, message: 'Performance Split requires exactly two people.' };
      const names = parties.map((row) => String(row?.name || '').trim().toLowerCase());
      if (names.some((name) => !name) || new Set(names).size !== 2) return { valid: false, message: 'Select two different people.' };
      const personnelIds = parties.map((row) => Number(row?.personnelId));
      if (personnelIds.some((id) => !Number.isInteger(id) || id < 1) || new Set(personnelIds).size !== 2) {
        return { valid: false, message: 'Select two different active Personnel records.' };
      }
      const percentages = parties.map((row) => Number(row?.pct));
      if (percentages.some((value) => !Number.isFinite(value) || value <= 0)) return { valid: false, message: 'Each split percentage must be greater than 0.' };
      const total = percentages.reduce((sum, value) => sum + value, 0);
      if (Math.abs(total - 100) > 0.0001) return { valid: false, message: `Split percentages must total 100% (currently ${formatAmount(total)}%).` };
      return { valid: true, message: 'Performance Split is complete.' };
    }

    function onSplitToggle(enabled) {
      if (!enabled || draft.splitParties.length === 2) return;
      draft.splitParties = [
        { clientKey: clientKey(), personnelId: null, name: '', pct: null },
        { clientKey: clientKey(), personnelId: null, name: '', pct: null }
      ];
    }
    function splitPartyInvalid(index, key) {
      if (!reviewAttempted.value || !draft.splitEnabled) return false;
      const row = draft.splitParties[index] || {};
      if (key === 'name') {
        const name = String(row.name || '').trim().toLowerCase();
        const personnelId = Number(row.personnelId);
        return !name || !Number.isInteger(personnelId) || personnelId < 1
          || draft.splitParties.some((item, itemIndex) => itemIndex !== index
            && (Number(item?.personnelId) === personnelId || String(item?.name || '').trim().toLowerCase() === name));
      }
      const pct = Number(row.pct);
      return !Number.isFinite(pct) || pct <= 0;
    }

    function lossRecordSummaryFor(caseData) {
      const rows = Array.isArray(caseData?.lossRecord) ? caseData.lossRecord : [];
      const years = Number(caseData?.lossRecordYears || 0);
      const subject = rows.length === 0 ? 'Loss Clean' : `${rows.length} ${rows.length === 1 ? 'loss' : 'losses'}`;
      if (!Number.isInteger(years) || years <= 0) return `${subject} — history period not specified`;
      return `${subject} in the past ${years} ${years === 1 ? 'year' : 'years'}`;
    }
    function addLossRecord() {
      draft.lossRecord.push({ clientKey: clientKey(), date: '', cause: '', lossPaid: null });
    }
    function removeLossRecord(index) { draft.lossRecord.splice(index, 1); }
    function lossRowInvalid(index, key) {
      if (!reviewAttempted.value) return false;
      const row = draft.lossRecord[index] || {};
      return !filled(row[key]);
    }

    function resetDraft() {
      const fresh = emptyDraft();
      Object.keys(draft).forEach((key) => delete draft[key]);
      Object.assign(draft, fresh);
      openSections.value = ['risk','security','terms','occupation','sumInsured','loss','specialAgreement','cedantPremium','reinsurerPremium','split','conditions'];
      saveMessage.value = '';
      reviewAttempted.value = false;
      reviewDialogVisible.value = false;
      editingCaseUid.value = '';
      editingRowVersion.value = null;
      editingOriginalStatus.value = 'draft';
      endorsementFieldsUnlocked.value = false;
      // Low/observational fix: this was only reset after a successful "Add clause"
      // (see addCaseClause), so switching cases without adding a clause could leave
      // a stray code/title typed for the previous case sitting in this input.
      Object.assign(caseClauseDraft, { code: '', title: '' });
    }

    function selectView(id) {
      if (!navigation.value.some((item) => item.id === id) && !['case-create', 'case-detail'].includes(id)) return;
      if (activeView.value === 'case-create') resetDraft();
      if (id !== 'case-detail') selectedCase.value = null;
      activeView.value = id;
      error.value = '';
      if (id === 'dashboard') loadDashboard();
      if (id === 'recycle') loadRecycleBin();
      if (id === 'mdm') loadMasterData();
      if (id === 'production') loadProductionPreview();
      if (id === 'accounting') loadAccounting();
      if (id === 'fxrates') loadFxRates();
      if (id === 'personnel') {
        const tasks = [loadPersonnel()];
        if (can('targets.read')) tasks.push(loadDashboardTargets());
        Promise.all(tasks);
      }
      if (id === 'reconciliation') loadReconciliation();
      if (id === 'audit') loadAuditLog();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
    function startNewCase() {
      resetDraft();
      activeView.value = 'case-create';
      if (!mdmRecords.value.length) loadMasterData();
      loadPersonnelOptions();
      window.scrollTo({ top: 0 });
    }
    function cancelNewCase() { resetDraft(); activeView.value = 'cases'; window.scrollTo({ top: 0 }); }
    function backToCases() { selectedCase.value = null; caseDetailTab.value = 'overview'; activeView.value = 'cases'; window.scrollTo({ top: 0 }); }

    function reinsurerKey(value) { return String(value || '').trim().toLowerCase().replace(/\s+/g, ' '); }
    function displayReinsurerName(value) {
      return selectedReinsurers.value.find((row) => row.key === reinsurerKey(value))?.label || value || '—';
    }
    function documentKindLabel(kind) {
      return { offer: 'Offer Slip', signed: 'Reinsurer Signed Slip', confirmation: 'Reinsurer Confirmation E-mail' }[kind] || kind;
    }
    function formatFileSize(value) {
      const bytes = Number(value || 0);
      if (bytes < 1024) return `${bytes} B`;
      return `${Math.ceil(bytes / 1024).toLocaleString('en-US')} KB`;
    }
    function formatDateTime(value) {
      if (!value) return '—';
      const date = new Date(value);
      return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' });
    }
    function resetDocumentForm() {
      documentForm.kind = 'offer';
      documentForm.reinsurers = [];
      documentForm.file = null;
      documentFileList.value = [];
    }
    function onDocumentKindChange() { documentForm.reinsurers = []; }
    function onDocumentFileChange(uploadFile) { documentForm.file = uploadFile?.raw || null; documentFileList.value = uploadFile ? [uploadFile] : []; }
    function onDocumentFileRemove() { documentForm.file = null; documentFileList.value = []; }

    async function documentRequest(path, options = {}) {
      const response = await fetch(path, { cache: 'no-store', ...options });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.message || body.error || `Document request failed (HTTP ${response.status}).`);
      }
      return response;
    }

    async function downloadGeneratedDocument(kind, format) {
      if (!selectedCase.value) return;
      if (kind === 'endorsement' && format !== 'pdf') return ElementPlus.ElMessage.warning('Endorsement is generated as PDF only.');
      if (kind === 'debit' && selectedCase.value.status === 'draft') {
        return ElementPlus.ElMessage.warning('Debit Note is available after the case is Announced.');
      }
      const key = `${kind}-${format}`;
      documentGenerating.value = key;
      try {
        const documentCase = generatedDocumentCase.value;
        let blob;
        let filename;
        if (format === 'docx') {
          if (!window.RIDocx || !window.RI_DOCX_TEMPLATES) throw new Error('Word document generator is unavailable.');
          blob = kind === 'cover'
            ? await window.RIDocx.generateCover(documentCase, window.RI_DOCX_TEMPLATES)
            : await window.RIDocx.generateDebit(documentCase, window.RI_DOCX_TEMPLATES);
          filename = kind === 'cover' ? window.RIDocx.coverFilename(documentCase) : window.RIDocx.debitFilename(documentCase);
          window.RIDocx.downloadBlob(blob, filename);
        } else {
          if (!window.RIPdf || !window.RI_PDF_ASSETS) throw new Error('PDF document generator is unavailable.');
          blob = kind === 'cover'
            ? await window.RIPdf.cover(documentCase)
            : kind === 'endorsement'
              ? await window.RIPdf.endorsement(documentCase)
              : await window.RIPdf.debit(documentCase);
          filename = kind === 'cover'
            ? window.RIPdf.coverFilename(documentCase)
            : kind === 'endorsement'
              ? window.RIPdf.endorsementFilename(documentCase)
              : window.RIPdf.debitFilename(documentCase);
          window.RIPdf.download(blob, filename);
        }
        ElementPlus.ElMessage.success(`${kind === 'cover' ? 'Cover Note' : kind === 'endorsement' ? 'Endorsement' : 'Debit Note'} ${format.toUpperCase()} saved.`);
      } catch (err) {
        ElementPlus.ElMessage.error(err instanceof Error ? err.message : String(err));
      } finally {
        documentGenerating.value = '';
      }
    }

    // Bugfix (#22): HTTP 409 (optimistic-lock row_version conflicts) was never
    // distinguished from any other error across the app's write flows — every
    // save function showed the same generic red toast, with no "someone else
    // changed this, reload the latest version" recovery path, which could leave
    // a user stuck repeatedly resubmitting a stale save. reportWriteError()
    // checks the real HTTP status (not a guess based on the error text) and,
    // for a 409, offers an explicit reload action instead of a plain error.
    function reportWriteError(err, reload) {
      const status = err && err.status;
      const message = err instanceof Error ? err.message : String(err);
      if (Number(status) === 409) {
        ElementPlus.ElMessageBox.confirm(
          `${message} Reload the latest version now?`,
          'Version conflict',
          { confirmButtonText: 'Reload latest version', cancelButtonText: 'Close', type: 'warning' }
        ).then(() => { if (typeof reload === 'function') reload(); }).catch(() => {});
      } else {
        ElementPlus.ElMessage.error(message);
      }
    }

    async function loadCaseDocuments() {
      if (!selectedCase.value?.caseUid) return;
      documentsLoading.value = true;
      try {
        const response = await documentRequest('/api/case-documents?caseUid=' + encodeURIComponent(selectedCase.value.caseUid), { headers: { Accept: 'application/json' } });
        const body = await response.json();
        caseDocuments.value = Array.isArray(body.files) ? body.files : [];
        documentCoverage.value = body.coverage || documentCoverage.value;
        signedSlipReminder.value = body.signedSlipReminder || signedSlipReminder.value;
      } catch (err) {
        ElementPlus.ElMessage.error(err instanceof Error ? err.message : String(err));
      } finally { documentsLoading.value = false; }
    }

    async function loadCaseWorkflow() {
      if (!selectedCase.value?.caseUid) return;
      workflowLoading.value = true;
      try {
        const response = await fetch('/api/case-workflow?caseUid=' + encodeURIComponent(selectedCase.value.caseUid), { headers: { Accept: 'application/json' }, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status));
        caseWorkflow.value = body.workflow;
      } catch (err) {
        ElementPlus.ElMessage.error(err instanceof Error ? err.message : String(err));
      } finally { workflowLoading.value = false; }
    }

    async function runWorkflowAction(action) {
      if (!selectedCase.value?.caseUid || workflowSaving.value) return;
      const label = action === 'create_endorsement' ? 'create a new endorsement Draft' : 'create a renewal Draft';
      try {
        await ElementPlus.ElMessageBox.confirm(`This will ${label} from the current case.`, 'Continue workflow', { confirmButtonText: 'Create draft', cancelButtonText: 'Cancel', type: 'warning' });
      } catch { return; }
      workflowSaving.value = true;
      try {
        const response = await fetch('/api/case-workflow', {
          method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ action, caseUid: selectedCase.value.caseUid, rowVersion: selectedCase.value.rowVersion })
        });
        const body = await response.json();
        if (!response.ok) {
          if (body.latestCaseUid) await startViewCase({ caseUid: body.latestCaseUid });
          const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status));
          requestErr.status = response.status;
          throw requestErr;
        }
        await loadData();
        await startEditCase(body.case);
        ElementPlus.ElMessage.success(action === 'create_endorsement' ? 'Endorsement Draft created' : 'Renewal Draft created');
      } catch (err) {
        reportWriteError(err, () => loadCaseWorkflow());
      } finally { workflowSaving.value = false; }
    }

    function createEndorsement() { return runWorkflowAction('create_endorsement'); }
    function createRenewal() { return runWorkflowAction('create_renewal'); }
    function viewWorkflowCase(row) { if (row?.caseUid) startViewCase(row); }

    function openAccountingNotification() {
      accountingForm.accountingPersonnelId = null;
      accountingForm.note = '';
      accountingDialogVisible.value = true;
    }

    async function saveAccountingNotification() {
      if (!accountingForm.accountingPersonnelId || !selectedCase.value?.caseUid) {
        return ElementPlus.ElMessage.warning('Select the Accounting recipient.');
      }
      workflowSaving.value = true;
      try {
        const response = await fetch('/api/case-workflow', {
          method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({
            action: 'notify_accounting',
            caseUid: selectedCase.value.caseUid,
            rowVersion: selectedCase.value.rowVersion,
            accountingPersonnelId: accountingForm.accountingPersonnelId,
            note: accountingForm.note
          })
        });
        const body = await response.json();
        if (!response.ok) {
          const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status));
          requestErr.status = response.status;
          throw requestErr;
        }
        accountingDialogVisible.value = false;
        await startViewCase({ caseUid: selectedCase.value.caseUid });
        ElementPlus.ElMessage.success('Accounting notification recorded');
      } catch (err) {
        reportWriteError(err, () => loadCaseWorkflow());
      } finally { workflowSaving.value = false; }
    }

    async function loadAccounting() {
      accountingLoading.value = true;
      error.value = '';
      try {
        const response = await fetch('/api/accounting', { headers: { Accept: 'application/json' }, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status));
        accountingRows.value = Array.isArray(body.rows) ? body.rows : [];
        accountingCurrencies.value = Array.isArray(body.currencies) ? body.currencies : [];
        accountingScope.value = body.scope || { canEdit: false };
        accountingSelection.value = [];
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
        ElementPlus.ElMessage.error(error.value);
      } finally { accountingLoading.value = false; }
    }

    function onAccountingSelectionChange(rows) {
      accountingSelection.value = Array.isArray(rows) ? rows : [];
    }

    function accountingRowSelectable(row) {
      return accountingScope.value.canEdit && row.settlement === 'open' && row.reversed !== true;
    }

    async function settleSelectedTransactions() {
      const entries = accountingSelection.value.map((row) => ({
        caseUid: row.caseUid,
        txNo: row.txNo,
        rowVersion: row.caseRowVersion
      }));
      if (!entries.length) return;
      accountingSaving.value = true;
      try {
        const response = await fetch('/api/accounting', {
          method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ action: 'settle', entries })
        });
        const body = await response.json();
        if (!response.ok) {
          const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status));
          requestErr.status = response.status;
          throw requestErr;
        }
        ElementPlus.ElMessage.success(`${body.settledCount} transaction${body.settledCount === 1 ? '' : 's'} marked as Settled`);
        await loadAccounting();
      } catch (err) {
        reportWriteError(err, () => loadAccounting());
        await loadAccounting();
      } finally { accountingSaving.value = false; }
    }

    function openSchedulePayment(row) {
      if (!row || row.source !== 'premium' || row.reviewRequired) return;
      if (Number(row.outstanding || 0) <= 0 && Number(row.paid || 0) <= 0) return;
      accountingPaymentRow.value = row;
      schedulePaymentForm.paymentDate = new Date().toISOString().slice(0, 10);
      schedulePaymentForm.amount = Number(row.outstanding || 0);
      schedulePaymentForm.note = '';
      accountingPaymentDialogVisible.value = true;
    }

    async function recordSchedulePayment() {
      const row = accountingPaymentRow.value;
      const amount = Number(schedulePaymentForm.amount);
      if (!row || !Number.isFinite(amount) || amount <= 0) return ElementPlus.ElMessage.warning('Enter a positive payment amount.');
      if (amount - Number(row.outstanding || 0) > 0.004) return ElementPlus.ElMessage.warning('Payment cannot exceed the selected installment balance.');
      accountingSaving.value = true;
      try {
        const response = await fetch('/api/accounting', {
          method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({
            action: 'record_payment', caseUid: row.caseUid, rowVersion: row.caseRowVersion,
            scheduleKey: row.scheduleKey, paymentDate: schedulePaymentForm.paymentDate,
            amount, note: schedulePaymentForm.note
          })
        });
        const body = await response.json();
        if (!response.ok) {
          const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status));
          requestErr.status = response.status;
          throw requestErr;
        }
        accountingPaymentDialogVisible.value = false;
        ElementPlus.ElMessage.success('Payment recorded against the selected installment and party');
        await loadAccounting();
      } catch (err) {
        reportWriteError(err, () => loadAccounting());
        await loadAccounting();
      } finally { accountingSaving.value = false; }
    }

    async function reverseSchedulePayment(row, entry) {
      if (!row || !entry?.id) return;
      try {
        await ElementPlus.ElMessageBox.confirm(
          'This keeps the original payment and appends an immutable reversal entry.',
          'Reverse payment',
          { confirmButtonText: 'Create reversal', cancelButtonText: 'Cancel', type: 'warning' }
        );
      } catch { return; }
      accountingSaving.value = true;
      try {
        const response = await fetch('/api/accounting', {
          method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({
            action: 'reverse_payment', caseUid: row.caseUid, rowVersion: row.caseRowVersion,
            entryId: entry.id, paymentDate: new Date().toISOString().slice(0, 10),
            note: 'Correction reversal'
          })
        });
        const body = await response.json();
        if (!response.ok) {
          const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status));
          requestErr.status = response.status;
          throw requestErr;
        }
        accountingPaymentDialogVisible.value = false;
        ElementPlus.ElMessage.success('Reversal entry created');
        await loadAccounting();
      } catch (err) {
        reportWriteError(err, () => loadAccounting());
        await loadAccounting();
      } finally { accountingSaving.value = false; }
    }

    function paymentStatusLabel(value) {
      return ({ pending_review: 'Pending review', upcoming: 'Upcoming', due_today: 'Due today', overdue: 'Overdue', partially_paid: 'Partially paid', settled: 'Settled' })[value] || value || '—';
    }

    function paymentStatusType(value) {
      return value === 'settled' ? 'success' : value === 'overdue' ? 'danger' : value === 'due_today' ? 'warning' : value === 'pending_review' ? 'info' : '';
    }

    async function openAccountingCase(row) {
      await startViewCase(row);
      caseDetailTab.value = 'soa';
    }

    async function reverseSelectedCase() {
      if (!selectedCase.value?.caseUid || selectedCase.value.status !== 'closed') return;
      try {
        await ElementPlus.ElMessageBox.confirm(
          'Existing premium transactions will remain in the SoA and be marked Reversed. After correction and a future Production close, offset entries and a new transaction cycle will be appended.',
          'Reverse confirmed case',
          { confirmButtonText: 'Reverse case', cancelButtonText: 'Cancel', type: 'warning' }
        );
      } catch { return; }
      workflowSaving.value = true;
      try {
        const response = await fetch('/api/case-workflow', {
          method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ action: 'reverse_case', caseUid: selectedCase.value.caseUid, rowVersion: selectedCase.value.rowVersion })
        });
        const body = await response.json();
        if (!response.ok) {
          const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status));
          requestErr.status = response.status;
          throw requestErr;
        }
        await loadData();
        await startViewCase({ caseUid: body.case.caseUid });
        ElementPlus.ElMessage.success('Case reversed — correct the figures and save to move it back to Announced');
      } catch (err) {
        reportWriteError(err, () => loadCaseWorkflow());
      } finally { workflowSaving.value = false; }
    }

    async function refreshSelectedCase() {
      if (!selectedCase.value?.caseUid) return;
      const response = await fetch('/api/cases?caseUid=' + encodeURIComponent(selectedCase.value.caseUid), { headers: { Accept: 'application/json' }, cache: 'no-store' });
      const body = await response.json();
      if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status));
      selectedCase.value = body.case;
    }

    async function loadClaims() {
      if (!selectedCase.value?.caseUid) return;
      claimsLoading.value = true;
      try {
        const response = await fetch('/api/claims?caseUid=' + encodeURIComponent(selectedCase.value.caseUid), { headers: { Accept: 'application/json' }, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status));
        claimsState.value = body.claimsState;
      } catch (err) {
        ElementPlus.ElMessage.error(err instanceof Error ? err.message : String(err));
      } finally { claimsLoading.value = false; }
    }

    async function submitClaimAction(action, extra = {}) {
      claimsSaving.value = true;
      try {
        const response = await fetch('/api/claims', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({
            action,
            caseUid: selectedCase.value.caseUid,
            rowVersion: claimsState.value.rootRowVersion,
            ...extra
          })
        });
        const body = await response.json();
        if (!response.ok) {
          const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status));
          requestErr.status = response.status;
          throw requestErr;
        }
        claimsState.value = body.claimsState;
        await refreshSelectedCase();
        return true;
      } catch (err) {
        // Bugfix (#22): previously guessed a version conflict by regex-matching
        // the word "reload" inside the error message; now checks the real
        // HTTP status via reportWriteError so it never misses (or misfires on
        // an unrelated error that happens to mention "reload").
        reportWriteError(err, () => loadClaims());
        return false;
      } finally { claimsSaving.value = false; }
    }

    async function createClaim() {
      const saved = await submitClaimAction('create_claim', { claim: { ...claimForm } });
      if (!saved) return;
      Object.assign(claimForm, { lossNo: '', dateOfLoss: '', outstandingReserve: null, causeOfLoss: '' });
      ElementPlus.ElMessage.success('Claim added');
    }

    async function updateClaimReserve(claim) {
      const saved = await submitClaimAction('update_reserve', { claimId: claim.id, outstandingReserve: claim.outstandingReserve });
      if (saved) ElementPlus.ElMessage.success('Outstanding reserve updated');
    }

    function openClaimPayment(claim) {
      activeClaimId.value = claim.id;
      Object.assign(paymentForm, { date: '', amount: null, note: '' });
      paymentDialogVisible.value = true;
    }

    async function recordClaimPayment() {
      // Note on #23 (reverted 2026-09-25 per user clarification): unlike a Payment
      // Terms schedule installment (recordSchedulePayment(), which correctly
      // requires a positive amount), a Claim payment can legitimately be negative
      // here — e.g. subrogation/recovery received back, or a deductible netting
      // adjustment — so only zero/invalid input is rejected, not negative values.
      if (!Number(paymentForm.amount)) return ElementPlus.ElMessage.error('Enter a non-zero payment amount.');
      const saved = await submitClaimAction('record_payment', { claimId: activeClaimId.value, payment: { ...paymentForm } });
      if (!saved) return;
      paymentDialogVisible.value = false;
      ElementPlus.ElMessage.success('Payment recorded and Claim Leg 1/2 transactions created');
    }

    function claimTotalPaid(claim) {
      return (Array.isArray(claim?.payments) ? claim.payments : []).reduce((sum, payment) => sum + Number(payment?.amount || 0), 0);
    }

    function onCaseDetailTabChange(name) {
      if (name === 'documents') loadCaseDocuments();
      if (name === 'claims') loadClaims();
      if (name === 'endorsements') loadCaseWorkflow();
    }

    function fileAsBase64(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || '').split(',')[1] || '');
        reader.onerror = () => reject(new Error('The selected file could not be read.'));
        reader.readAsDataURL(file);
      });
    }

    async function uploadCaseDocument() {
      const file = documentForm.file;
      if (!file) return ElementPlus.ElMessage.error('Select a document to upload.');
      if (!file.size || file.size > 5 * 1024 * 1024) return ElementPlus.ElMessage.error('Each document must be nonempty and no larger than 5 MB.');
      if (documentForm.kind !== 'offer' && !documentForm.reinsurers.length) return ElementPlus.ElMessage.error('Select the reinsurer(s) covered by this evidence.');
      documentsSaving.value = true;
      try {
        const base64 = await fileAsBase64(file);
        const response = await documentRequest('/api/case-documents', {
          method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ caseUid: selectedCase.value.caseUid, kind: documentForm.kind, reinsurers: documentForm.reinsurers, filename: file.name, base64 })
        });
        const body = await response.json();
        caseDocuments.value.push(body.file);
        documentCoverage.value = body.coverage;
        signedSlipReminder.value = body.signedSlipReminder || signedSlipReminder.value;
        resetDocumentForm();
        ElementPlus.ElMessage.success('Placement document uploaded and selected.');
      } catch (err) {
        ElementPlus.ElMessage.error(err instanceof Error ? err.message : String(err));
      } finally { documentsSaving.value = false; }
    }

    async function toggleDocumentSelection(row, selected) {
      const previous = !selected;
      documentsSaving.value = true;
      try {
        const response = await documentRequest('/api/case-documents', {
          method: 'PUT', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ caseUid: selectedCase.value.caseUid, fileId: row.id, selected })
        });
        const body = await response.json();
        documentCoverage.value = body.coverage;
      } catch (err) {
        row.is_selected = previous;
        ElementPlus.ElMessage.error(err instanceof Error ? err.message : String(err));
      } finally { documentsSaving.value = false; }
    }

    async function downloadCaseDocument(row) {
      try {
        const response = await documentRequest('/api/case-documents?caseUid=' + encodeURIComponent(selectedCase.value.caseUid) + '&fileId=' + encodeURIComponent(row.id));
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url; anchor.download = row.filename; document.body.appendChild(anchor); anchor.click(); anchor.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      } catch (err) { ElementPlus.ElMessage.error(err instanceof Error ? err.message : String(err)); }
    }

    async function deleteCaseDocument(row) {
      try {
        await ElementPlus.ElMessageBox.confirm(`Delete “${row.filename}” permanently?`, 'Delete placement document', { type: 'warning', confirmButtonText: 'Delete', cancelButtonText: 'Cancel' });
      } catch (_) { return; }
      documentsSaving.value = true;
      try {
        const response = await documentRequest('/api/case-documents?caseUid=' + encodeURIComponent(selectedCase.value.caseUid) + '&fileId=' + encodeURIComponent(row.id), { method: 'DELETE', headers: { Accept: 'application/json' } });
        const body = await response.json();
        caseDocuments.value = caseDocuments.value.filter((file) => file.id !== row.id);
        documentCoverage.value = body.coverage;
        signedSlipReminder.value = body.signedSlipReminder || signedSlipReminder.value;
        ElementPlus.ElMessage.success('Placement document deleted.');
      } catch (err) { ElementPlus.ElMessage.error(err instanceof Error ? err.message : String(err)); }
      finally { documentsSaving.value = false; }
    }

    function openAnnounceReview() {
      if (selectedCase.value?.status !== 'draft') return;
      if (selectedAnnounceIssues.value.length) return ElementPlus.ElMessage.error(`Complete ${selectedAnnounceIssues.value.length} required case fields before Announce.`);
      if (!documentCoverage.value.ready) return ElementPlus.ElMessage.error(documentReadinessText.value);
      announceConfirmed.value = false;
      announceDialogVisible.value = true;
    }

    async function announceSelectedCase() {
      if (!announceConfirmed.value || !selectedCase.value?.caseUid) return;
      announcing.value = true;
      try {
        const response = await fetch('/api/case-announce', {
          method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({
            caseUid: selectedCase.value.caseUid,
            rowVersion: selectedCase.value.rowVersion,
            confirmed: true,
            documentIds: documentCoverage.value.selected || []
          })
        });
        const body = await response.json();
        if (!response.ok) {
          const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status));
          requestErr.status = response.status;
          throw requestErr;
        }
        selectedCase.value = {
          ...selectedCase.value,
          twRef: body.case.twRef,
          status: body.case.status,
          rowVersion: Number(body.case.rowVersion),
          announcedAt: body.case.announcedAt
        };
        announceDialogVisible.value = false;
        announceConfirmed.value = false;
        await loadData();
        ElementPlus.ElMessage.success(`Case Announced · ${body.case.twRef}`);
      } catch (err) {
        reportWriteError(err, () => refreshSelectedCase());
        await loadCaseDocuments();
      } finally { announcing.value = false; }
    }
    function addSituation() { draft.situations.push({ clientKey: clientKey(), address: '', postcode: '' }); }
    function removeSituation(index) { if (draft.situations.length > 1) draft.situations.splice(index, 1); }
    function addReinsurer() { draft.reinsurers.push({ clientKey: clientKey(), name: '', sharePct: null, premium: null, riCommPct: null, taxPct: null, paymentTermsDays: null, foreignBroker: '', settlementRef: '' }); }
    function removeReinsurer(index) { if (draft.reinsurers.length > 1) { draft.reinsurers.splice(index, 1); syncCaseClauses(); } }
    function addSumInsured() { draft.sumInsured.push({ clientKey: clientKey(), category: '', amount: null, locationIndex: 0 }); }
    function removeSumInsured(index) { if (draft.sumInsured.length > 1) draft.sumInsured.splice(index, 1); }

    function masterTypeLabel(value) {
      return masterTypes.find((item) => item.value === value)?.label || value;
    }

    function isUniversalClauseCode(code) {
      return UNIVERSAL_CLAUSES.some((row) => row.code === String(code || '').toUpperCase());
    }

    function clauseSourceType(code) {
      return isUniversalClauseCode(code) ? 'Universal' : 'Standard';
    }

    function clauseUsedByReinsurers(code) {
      const normalized = String(code || '').toUpperCase();
      return mdmRecords.value
        .filter((row) => row.entityType === 'reinsurer' && Array.isArray(row.payload?.fixedClauses) && row.payload.fixedClauses.some((c) => String(c.code || '').toUpperCase() === normalized))
        .map((row) => row.payload?.abbreviation || row.name)
        .sort((a, b) => a.localeCompare(b));
    }

    function availableClauseOptions() {
      const alreadyAdded = new Set((mdmForm.fixedClauses || []).map((row) => String(row.code || '').toUpperCase()));
      return mdmRecords.value
        .filter((row) => row.entityType === 'clause' && row.isActive && !isUniversalClauseCode(row.code) && !alreadyAdded.has(String(row.code || '').toUpperCase()))
        .map((row) => ({ code: row.code, title: row.name }))
        .sort(compareClauses);
    }

    function onMdmClauseDraftSelect(code) {
      const match = mdmRecords.value.find((row) => row.entityType === 'clause' && row.code === code);
      mdmClauseDraft.title = match ? match.name : '';
    }

    function masterOptions(type, currentValue = '') {
      const options = mdmRecords.value
        .filter((row) => row.entityType === type && row.isActive)
        .slice()
        .sort((a, b) => a.name.localeCompare(b.name, 'en'));
      const current = String(currentValue || '').trim();
      if (current && !options.some((row) => row.name === current)) {
        options.push({ id: `historical-${type}-${current}`, entityType: type, code: '', name: current, isActive: false, historical: true });
      }
      return options;
    }

    function splitPersonOptions(row) {
      const options = personnelRecords.value
        .filter((person) => person.isActive && person.isSplitEligible)
        .slice()
        .sort((a, b) => a.name.localeCompare(b.name));
      const currentId = Number(row?.personnelId);
      const currentName = String(row?.name || '').trim();
      if (currentName && !options.some((person) => Number(person.id) === currentId || person.name === currentName)) {
        options.push({
          id: Number.isInteger(currentId) && currentId > 0 ? currentId : `historical-${currentName}`,
          name: currentName,
          department: '',
          historical: true
        });
      }
      return options;
    }

    function onSplitPersonSelected(row) {
      const person = personnelRecords.value.find((item) => item.isActive && item.isSplitEligible && item.name === row.name);
      if (person) row.personnelId = Number(person.id);
      else if (!row.name) row.personnelId = null;
    }

    function onClassSelected(name) {
      const record = mdmRecords.value.find((row) => row.entityType === 'class' && row.name === name);
      if (record) draft.classCode = record.code || '';
      else if (!name) draft.classCode = '';
    }

    function syncCaseClauses() {
      const details = UNIVERSAL_CLAUSES.map((row) => ({ ...row }));
      draft.reinsurers.forEach((line) => {
        const master = mdmRecords.value.find((row) => row.entityType === 'reinsurer' && row.name === line.name);
        normalizeClauseList(master?.payload?.fixedClauses).forEach((row) => details.push(row));
      });
      normalizeClauseList(draft.manualClauses).forEach((row) => details.push(row));
      const unique = normalizeClauseList(details).sort(compareClauses);
      draft.clauseDetails = unique;
      draft.clauses = unique.map((row) => row.code);
      const manualCodes = new Set(normalizeClauseList(draft.manualClauses).map((row) => row.code));
      draft.autoClauses = unique.filter((row) => !UNIVERSAL_CLAUSES.some((base) => base.code === row.code) && !manualCodes.has(row.code)).map((row) => row.code);
    }
    function onReinsurerSelected() {
      syncCaseClauses();
      if (allFacilityReinsurers.value) draft.sumInsured.forEach((row) => { row.locationIndex = 0; });
    }
    function addCaseClause() {
      if (!hasNonFacilityReinsurer.value) return ElementPlus.ElMessage.error('Case-specific clauses are available only when at least one selected reinsurer is not a Facility');
      const clause = normalizeClauseList([caseClauseDraft])[0];
      if (!clause) return ElementPlus.ElMessage.error('Enter both Clause code and Clause name');
      if (draft.clauses.some((code) => normalizeClauseCode(code) === clause.code)) return ElementPlus.ElMessage.error('This Clause code is already included in the case');
      draft.manualClauses.push(clause);
      Object.assign(caseClauseDraft, { code: '', title: '' });
      syncCaseClauses();
    }
    function removeCaseClause(code) {
      draft.manualClauses = normalizeClauseList(draft.manualClauses).filter((row) => row.code !== code);
      syncCaseClauses();
    }
    function isManualClause(code) { return normalizeClauseList(draft.manualClauses).some((row) => row.code === code); }
    function clauseSourceLabel(code) {
      const normalized = normalizeClauseCode(code);
      if (UNIVERSAL_CLAUSES.some((row) => row.code === normalized)) return 'Universal';
      return isManualClause(normalized) ? 'Manual' : 'Fixed';
    }

    function structureLabel(value) {
      return STRUCTURE_LABEL[value] || value || '—';
    }

    function recomputeType() {
      const suffix = STRUCTURE_SUFFIX[draft.reinsuranceStructure] || '';
      const prefix = String(draft.typePrefix || '').trim();
      draft.type = suffix ? (prefix ? `${prefix} ${suffix}` : suffix) : prefix;
    }

    function onStructureSelected() {
      if (draft.reinsuranceStructure === 'QS') draft.underlyingLimits = '';
      recomputeType();
    }

    async function loadMasterData() {
      mdmLoading.value = true; error.value = '';
      try {
        const response = await fetch('/api/master-data', { headers: { Accept: 'application/json' }, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status));
        mdmRecords.value = Array.isArray(body.records) ? body.records : [];
        mdmCounts.value = body.counts || mdmCounts.value;
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
        ElementPlus.ElMessage.error(error.value);
      } finally { mdmLoading.value = false; }
    }

    function openMasterDialog(row = null) {
      editingMasterId.value = row ? Number(row.id) : null;
      editingMasterRowVersion.value = row ? Number(row.rowVersion) : null;
      Object.assign(mdmForm, row
        ? {
            entityType: row.entityType, code: row.code || '', name: row.name || '',
            abbreviation: row.payload?.abbreviation || '', address: row.payload?.address || '',
            fixedClauses: normalizeClauseList(row.payload?.fixedClauses), ratings: normalizeRatingList(row.payload?.ratings)
          }
        : { entityType: activeMdmType.value, code: '', name: '', abbreviation: '', address: '', fixedClauses: [], ratings: [] });
      Object.assign(mdmClauseDraft, { code: '', title: '' });
      Object.assign(mdmRatingDraft, { agency: '', grade: '', outlook: '', ratingType: '', asOfDate: '', legalEntity: '', sourceUrl: '', checkedAt: '', status: '' });
      mdmDialogVisible.value = true;
    }

    function addMdmFixedClause() {
      const clause = normalizeClauseList([mdmClauseDraft])[0];
      if (!clause) return ElementPlus.ElMessage.error('Enter both Clause code and Clause name');
      if (UNIVERSAL_CLAUSES.some((row) => row.code === clause.code)) return ElementPlus.ElMessage.error(`${clause.code} is included in every case`);
      if (mdmForm.fixedClauses.some((row) => row.code === clause.code)) return ElementPlus.ElMessage.error('This Clause code already exists for the reinsurer');
      mdmForm.fixedClauses.push(clause);
      mdmForm.fixedClauses.sort(compareClauses);
      Object.assign(mdmClauseDraft, { code: '', title: '' });
    }
    function removeMdmFixedClause(index) { mdmForm.fixedClauses.splice(index, 1); }
    function addMdmRating() {
      const rating = normalizeRatingList([mdmRatingDraft])[0];
      if (!rating) return ElementPlus.ElMessage.error('Enter both Rating agency and Grade');
      mdmForm.ratings.push(rating);
      Object.assign(mdmRatingDraft, { agency: '', grade: '', outlook: '', ratingType: '', asOfDate: '', legalEntity: '', sourceUrl: '', checkedAt: '', status: '' });
    }
    function removeMdmRating(index) { mdmForm.ratings.splice(index, 1); }
    function masterPayloadFromForm() {
      const type = mdmForm.entityType;
      const payload = {};
      if (['reinsurer', 'reinsured', 'foreign_broker'].includes(type)) payload.abbreviation = String(mdmForm.abbreviation || '').trim();
      if (type === 'reinsured') payload.address = String(mdmForm.address || '').trim();
      if (type === 'reinsurer') {
        payload.fixedClauses = normalizeClauseList(mdmForm.fixedClauses);
        payload.ratings = normalizeRatingList(mdmForm.ratings);
      }
      return payload;
    }

    async function saveMasterRecord() {
      if (!mdmForm.name.trim()) {
        ElementPlus.ElMessage.error('Name is required');
        return;
      }
      if (mdmForm.entityType === 'clause' && !String(mdmForm.code || '').trim()) {
        ElementPlus.ElMessage.error('Clause code is required');
        return;
      }
      mdmSaving.value = true; error.value = '';
      try {
        const response = await fetch('/api/master-data', {
          method: editingMasterId.value ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify(editingMasterId.value
            ? { entityType: mdmForm.entityType, code: mdmForm.code, name: mdmForm.name, payload: JSON.stringify(masterPayloadFromForm()), id: editingMasterId.value, rowVersion: editingMasterRowVersion.value }
            : { entityType: mdmForm.entityType, code: mdmForm.code, name: mdmForm.name, payload: JSON.stringify(masterPayloadFromForm()) })
        });
        const body = await response.json();
        if (!response.ok) {
          const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status));
          requestErr.status = response.status;
          throw requestErr;
        }
        mdmDialogVisible.value = false;
        activeMdmType.value = body.record.entityType;
        await loadMasterData();
        ElementPlus.ElMessage.success(`${masterTypeLabel(body.record.entityType)} ${editingMasterId.value ? 'updated' : 'added'}`);
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
        reportWriteError(err, () => loadMasterData());
      } finally { mdmSaving.value = false; }
    }

    async function toggleMasterStatus(row) {
      mdmSaving.value = true; error.value = '';
      try {
        const response = await fetch('/api/master-data', {
          method: 'PUT', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({
            id: row.id, rowVersion: row.rowVersion, entityType: row.entityType,
            code: row.code, name: row.name, payload: JSON.stringify(row.payload || {}), isActive: !row.isActive
          })
        });
        const body = await response.json();
        if (!response.ok) {
          const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status));
          requestErr.status = response.status;
          throw requestErr;
        }
        await loadMasterData();
        ElementPlus.ElMessage.success(body.record.isActive ? 'Master record reactivated' : 'Master record deactivated');
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
        reportWriteError(err, () => loadMasterData());
      } finally { mdmSaving.value = false; }
    }

    function loadDraftIntoForm(payload) {
      const fresh = emptyDraft();
      Object.assign(fresh, payload || {});
      if (fresh.reinsuranceStructure === 'FACULTATIVE') fresh.reinsuranceStructure = 'QS';
      // Low/observational fix: onStructureSelected() only clears underlyingLimits
      // when the user manually switches structure to QS during the current
      // editing session. Opening an existing Draft skipped that check, so a stale
      // underlyingLimits value could briefly display here even though the backend
      // always force-clears it on the next save. Re-check it on load too.
      if (fresh.reinsuranceStructure === 'QS') fresh.underlyingLimits = '';
      const suffix = STRUCTURE_SUFFIX[fresh.reinsuranceStructure] || '';
      if (!String(payload?.typePrefix || '').trim()) {
        const storedType = String(payload?.type || '').trim();
        fresh.typePrefix = suffix && storedType.endsWith(suffix)
          ? storedType.slice(0, -suffix.length).trim()
          : storedType;
      }
      fresh.type = suffix
        ? (fresh.typePrefix ? `${fresh.typePrefix} ${suffix}` : suffix)
        : fresh.typePrefix;
      fresh.situations = (Array.isArray(payload?.situations) && payload.situations.length ? payload.situations : fresh.situations)
        .map((row) => ({ ...row, clientKey: clientKey() }));
      fresh.reinsurers = (Array.isArray(payload?.reinsurers) && payload.reinsurers.length ? payload.reinsurers : fresh.reinsurers)
        .map((row) => ({ ...row, clientKey: clientKey() }));
      fresh.sumInsured = (Array.isArray(payload?.sumInsured) && payload.sumInsured.length ? payload.sumInsured : fresh.sumInsured)
        .map((row) => ({ ...row, clientKey: clientKey() }));
      fresh.performanceInstallments = (Array.isArray(payload?.performanceInstallments) ? payload.performanceInstallments : [])
        .map((row) => ({ ...row, paymentBaseDate: row?.paymentBaseDate || '', paymentTermsDays: row?.paymentTermsDays ?? null, reinsurerPaymentTerms: row?.reinsurerPaymentTerms && typeof row.reinsurerPaymentTerms === 'object' ? row.reinsurerPaymentTerms : {}, clientKey: clientKey() }));
      fresh.lossRecord = (Array.isArray(payload?.lossRecord) ? payload.lossRecord : [])
        .map((row) => ({ ...row, clientKey: clientKey() }));
      fresh.splitParties = (Array.isArray(payload?.splitParties) && payload.splitParties.length ? payload.splitParties : fresh.splitParties)
        .slice(0, 2).map((row) => ({ ...row, clientKey: clientKey() }));
      fresh.manualClauses = normalizeClauseList(payload?.manualClauses);
      fresh.clauseDetails = normalizeClauseList(payload?.clauseDetails?.length ? payload.clauseDetails : UNIVERSAL_CLAUSES).sort(compareClauses);
      fresh.clauses = fresh.clauseDetails.map((row) => row.code);
      fresh.autoClauses = Array.isArray(payload?.autoClauses) ? payload.autoClauses.map(normalizeClauseCode).filter(Boolean) : [];
      Object.keys(draft).forEach((key) => delete draft[key]);
      Object.assign(draft, fresh);
    }

    async function startEditCase(row) {
      if (!row?.caseUid || !['draft', 'posted'].includes(row.status)) return;
      loading.value = true; error.value = '';
      try {
        if (!mdmRecords.value.length) await loadMasterData();
        if (!personnelRecords.value.length) await loadPersonnelOptions();
        const response = await fetch('/api/cases?caseUid=' + encodeURIComponent(row.caseUid), { headers: { Accept: 'application/json' }, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status));
        resetDraft();
        loadDraftIntoForm(body.case?.payload || {});
        editingCaseUid.value = body.case.caseUid;
        editingRowVersion.value = Number(body.case.rowVersion);
        editingOriginalStatus.value = body.case.status || 'draft';
        endorsementFieldsUnlocked.value = false;
        activeView.value = 'case-create';
        openSections.value = ['risk','security','terms','occupation','sumInsured','loss','specialAgreement','cedantPremium','reinsurerPremium','split','conditions'];
        window.scrollTo({ top: 0 });
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
        ElementPlus.ElMessage.error(error.value);
      } finally { loading.value = false; }
    }

    function normalizedPolicyTime(value) {
      return value === '00:00' ? '00:00' : '12:00';
    }

    function formatPolicyDateTime(date, time) {
      return date ? `${date} ${normalizedPolicyTime(time)}` : '—';
    }

    function formatPolicyPeriod(row) {
      return `${formatPolicyDateTime(row?.effectiveDate || row?.policyFrom, row?.effectiveTime || row?.policyFromTime)} ~ ${formatPolicyDateTime(row?.expirationDate || row?.policyTo, row?.expirationTime || row?.policyToTime)}`;
    }

    function openCasePreview(row) {
      if (!row?.caseUid) return;
      casePreview.value = row;
      casePreviewVisible.value = true;
    }

    async function openPreviewFullCase() {
      const row = casePreview.value;
      casePreviewVisible.value = false;
      if (row) await startViewCase(row);
    }

    async function startViewCase(row) {
      if (!row?.caseUid) return;
      caseDetailLoading.value = true; error.value = '';
      try {
        const response = await fetch('/api/cases?caseUid=' + encodeURIComponent(row.caseUid), { headers: { Accept: 'application/json' }, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status));
        selectedCase.value = body.case;
        caseDetailTab.value = 'overview';
        caseDocuments.value = [];
        documentCoverage.value = { offer: false, required: [], covered: [], missing: [], ready: false, selected: [] };
        signedSlipReminder.value = { complete: false, missing: [], eligibleStatus: false, daysSinceEffective: null, firstReminderOn: '', due: false, today: '', cadenceDays: 7, outboundEnabled: false };
        resetDocumentForm();
        caseWorkflow.value = null;
        activeView.value = 'case-detail';
        await loadCaseWorkflow();
        window.scrollTo({ top: 0 });
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
        ElementPlus.ElMessage.error(error.value);
      } finally { caseDetailLoading.value = false; }
    }

    function editSelectedCase() {
      if (['draft', 'posted', 'reversed'].includes(selectedCase.value?.status)) startEditCase(selectedCase.value);
    }

    function statusLabel(status) {
      return { draft: 'Draft', posted: 'Announced', closed: 'Confirmed', reversed: 'Reversed', archived: 'Archived' }[status] || status || 'Unknown';
    }

    function filled(value) {
      if (value === null || value === undefined) return false;
      if (typeof value === 'string') return value.trim() !== '';
      return true;
    }

    function collectPayloadAnnounceIssues(value) {
      const issues = [];
      const add = (label) => issues.push(label);
      if (!Number.isInteger(Number(value?.ownerPersonnelId)) || Number(value.ownerPersonnelId) < 1) add('Case Owner');
      [
        ['reinsuranceStructure', 'Reinsurance structure'], ['ae', 'AE'], ['currency', 'Currency'],
        ['classOfBusiness', 'Class'], ['newOrRenew', 'New / Renew'], ['type', 'Type'],
        ['reinsured', 'Reinsured'], ['originalInsured', 'Original insured (EN)'],
        ['policyFrom', 'Effective date'], ['policyTo', 'Expiration date'], ['interest', 'Interest']
      ].forEach(([field, label]) => { if (!filled(value?.[field])) add(label); });
      if (filled(value?.parentTwRef)) {
        if (!filled(value?.endoEffectiveDate)) add('Endorsement effective date');
        if (!Array.isArray(value?.endoTypes) || !value.endoTypes.length) add('At least one endorsement type');
        if (!filled(value?.endoText)) add('Endorsement wording');
      }
      const situations = Array.isArray(value?.situations) ? value.situations : [];
      if (!situations.length) add('Situation');
      situations.forEach((row, index) => {
        if (!filled(row?.address)) add(`Situation ${index + 1} Risk Address`);
        if (!/^\d{3,6}$/.test(String(row?.postcode || '').trim())) add(`Situation ${index + 1} Postcode`);
      });
      const reinsurers = Array.isArray(value?.reinsurers) ? value.reinsurers : [];
      if (!reinsurers.length) add('Schedule of Security');
      reinsurers.forEach((row, index) => {
        if (!filled(row?.name)) add(`Reinsurer ${index + 1}`);
        if (!filled(row?.sharePct)) add(`Reinsurer ${index + 1} Order hereon`);
        if (!filled(row?.premium)) add(`Reinsurer ${index + 1} Premium`);
        if (!filled(row?.riCommPct)) add(`Reinsurer ${index + 1} Deductions`);
        if (!filled(row?.taxPct)) add(`Reinsurer ${index + 1} Tax`);
      });
      [['limitOfLiability','Limit of Liability'],['deductibles','Deductibles'],['originalConditions','Original Conditions'],['occupation','Occupation'],['construction','Construction']]
        .forEach(([field,label]) => { if (!filled(value?.[field])) add(label); });
      if (value?.basisOfValuation === 'Other' && !filled(value?.basisOfValuationOther)) add('Basis of Valuation — Other');
      const sumInsured = Array.isArray(value?.sumInsured) ? value.sumInsured : [];
      if (!sumInsured.length) add('Breakdown of Sum Insured');
      sumInsured.forEach((row,index) => {
        if (!filled(row?.category)) add(`Sum insured ${index + 1} Interest insured`);
        if (!filled(row?.amount)) add(`Sum insured ${index + 1} Amount`);
      });
      if (!filled(value?.lossAdvisedDate)) add('Loss record advised by broker on');
      if (!Number.isInteger(Number(value?.lossRecordYears)) || Number(value?.lossRecordYears) <= 0) add('Loss history years');
      (Array.isArray(value?.lossRecord) ? value.lossRecord : []).forEach((row, index) => {
        if (!filled(row?.date)) add(`Loss ${index + 1} Date of Loss`);
        if (!filled(row?.cause)) add(`Loss ${index + 1} Cause`);
        if (!filled(row?.lossPaid)) add(`Loss ${index + 1} Loss Paid`);
      });
      [['originalPremium','100% Premium'],['paymentTermsDays','Payment terms'],['riCommPct','Ceding commission'],['taxPct','Cedant tax']]
        .forEach(([field,label]) => { if (!filled(value?.[field])) add(label); });
      if (value?.installmentEnabled) {
        const installmentResult = installmentValidationFor(value);
        if (!installmentResult.valid) add(installmentResult.message);
      }
      if (value?.splitEnabled) {
        const splitResult = splitValidationFor(value);
        if (!splitResult.valid) add(splitResult.message);
      }
      return issues;
    }

    function validPostcode(value) { return /^\d{3,6}$/.test(String(value || '').trim()); }
    function validPositiveInteger(value) {
      const number = Number(value);
      return filled(value) && Number.isInteger(number) && number > 0;
    }

    function fieldInvalid(key, validator) {
      if (!reviewAttempted.value) return false;
      const value = draft[key];
      if (Array.isArray(value)) return value.length === 0;
      if (validator === 'positiveInteger') return !validPositiveInteger(value);
      return !filled(value);
    }

    function rowInvalid(listName, index, key, validator) {
      if (!reviewAttempted.value) return false;
      const row = draft[listName] && draft[listName][index];
      const value = row && row[key];
      if (validator === 'postcode') return !validPostcode(value);
      return !filled(value);
    }

    function collectRequiredIssues() {
      const issues = [];
      const add = (section, label) => issues.push({ section, label });
      [
        ['reinsuranceStructure', 'Reinsurance structure'], ['ae', 'AE'], ['currency', 'Currency'],
        ['classOfBusiness', 'Class'], ['newOrRenew', 'New / Renew'], ['type', 'Type'],
        ['reinsured', 'Reinsured'], ['originalInsured', 'Original insured (EN)'],
        ['policyFrom', 'Effective date'], ['policyTo', 'Expiration date'], ['interest', 'Interest']
      ].forEach(([key, label]) => { if (!filled(draft[key])) add('risk', label); });
      if (draft.parentTwRef) {
        if (!filled(draft.endoEffectiveDate)) add('risk', 'Endorsement effective date');
        if (!Array.isArray(draft.endoTypes) || !draft.endoTypes.length) add('risk', 'At least one endorsement type');
        if (!filled(draft.endoText)) add('risk', 'Endorsement wording');
      }
      if (!draft.situations.length) add('risk', 'Situation');
      draft.situations.forEach((row, index) => {
        if (!filled(row.address)) add('risk', `Situation ${index + 1} Risk Address`);
        if (!validPostcode(row.postcode)) add('risk', `Situation ${index + 1} Postcode`);
      });

      if (!draft.reinsurers.length) add('security', 'Schedule of Security');
      draft.reinsurers.forEach((row, index) => {
        if (!filled(row.name)) add('security', `Reinsurer ${index + 1}`);
        if (!filled(row.sharePct)) add('security', `Reinsurer ${index + 1} Order hereon`);
      });

      if (!filled(draft.limitOfLiability)) add('terms', 'Limit of Liability');
      if (!filled(draft.deductibles)) add('terms', 'Deductibles');
      if (!filled(draft.originalConditions)) add('terms', 'Original Conditions');
      if (draft.basisOfValuation === 'Other' && !filled(draft.basisOfValuationOther)) add('terms', 'Basis of Valuation — Other');
      if (!filled(draft.occupation)) add('occupation', 'Occupation');
      if (!filled(draft.construction)) add('occupation', 'Construction');

      if (!draft.sumInsured.length) add('sumInsured', 'Breakdown of Sum Insured');
      draft.sumInsured.forEach((row, index) => {
        if (!filled(row.category)) add('sumInsured', `Sum insured ${index + 1} Interest insured`);
        if (!filled(row.amount)) add('sumInsured', `Sum insured ${index + 1} Amount`);
      });
      if (!filled(draft.lossAdvisedDate)) add('loss', 'Loss record advised by broker on');
      if (!validPositiveInteger(draft.lossRecordYears)) add('loss', 'Loss history years');
      draft.lossRecord.forEach((row, index) => {
        if (!filled(row.date)) add('loss', `Loss ${index + 1} Date of Loss`);
        if (!filled(row.cause)) add('loss', `Loss ${index + 1} Cause`);
        if (!filled(row.lossPaid)) add('loss', `Loss ${index + 1} Loss Paid`);
      });

      [
        ['originalPremium', '100% Premium'], ['paymentTermsDays', 'Payment terms'],
        ['riCommPct', 'Ceding commission'], ['taxPct', 'Cedant tax']
      ].forEach(([key, label]) => { if (!filled(draft[key])) add('cedantPremium', label); });
      if (draft.installmentEnabled) {
        const installmentResult = installmentValidationFor(draft);
        if (!installmentResult.valid) add('cedantPremium', installmentResult.message);
      }
      if (draft.splitEnabled) {
        const splitResult = splitValidationFor(draft);
        if (!splitResult.valid) add('split', splitResult.message);
      }
      draft.reinsurers.forEach((row, index) => {
        if (!filled(row.premium)) add('reinsurerPremium', `Reinsurer ${index + 1} Premium`);
        if (!filled(row.riCommPct)) add('reinsurerPremium', `Reinsurer ${index + 1} Deductions`);
        if (!filled(row.taxPct)) add('reinsurerPremium', `Reinsurer ${index + 1} Tax`);
      });
      return issues;
    }

    async function reviewAndConfirm() {
      reviewAttempted.value = true;
      const issues = collectRequiredIssues();
      if (!issues.length) {
        reviewDialogVisible.value = true;
        return;
      }
      openSections.value = Array.from(new Set(openSections.value.concat(issues.map((issue) => issue.section))));
      ElementPlus.ElMessage.error(validationMessage.value);
      await nextTick();
      window.setTimeout(() => {
        const first = document.querySelector('.case-form .is-required-error, .case-form .required-invalid');
        if (!first) return;
        first.scrollIntoView({ behavior: 'smooth', block: 'center' });
        const focusTarget = first.querySelector('input, textarea, button, [role="combobox"]');
        if (focusTarget && typeof focusTarget.focus === 'function') focusTarget.focus({ preventScroll: true });
      }, 180);
    }

    function formatAmount(value) {
      if (!filled(value)) return '—';
      return new Intl.NumberFormat('en-US', { maximumFractionDigits: 4 }).format(Number(value));
    }

    function formatThousands(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return '—';
      return `${new Intl.NumberFormat('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(number / 1000)}K`;
    }

    function formatFxRate(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return '—';
      return new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 6 }).format(number);
    }

    function formatMoney(value) {
      const number = Number(value);
      return new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number.isFinite(number) ? number : 0);
    }

    function formatCurrency(value, currency) {
      const number = Number(value);
      const digits = currency === 'TWD' ? 0 : 2;
      return new Intl.NumberFormat('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Number.isFinite(number) ? number : 0);
    }

    async function saveReviewedDraft() {
      reviewDialogVisible.value = false;
      await saveDraft();
    }

    function plainDraft() {
      const value = JSON.parse(JSON.stringify(draft));
      value.situations.forEach((row) => delete row.clientKey);
      value.reinsurers.forEach((row) => delete row.clientKey);
      value.sumInsured.forEach((row) => delete row.clientKey);
      value.performanceInstallments.forEach((row) => delete row.clientKey);
      value.splitParties.forEach((row) => delete row.clientKey);
      value.lossRecord.forEach((row) => delete row.clientKey);
      return value;
    }

    async function loadDashboard() {
      if (!can('dashboard.read')) return;
      dashboardLoading.value = true;
      error.value = '';
      try {
        const response = await fetch('/api/dashboard', { headers: { Accept: 'application/json' }, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status));
        dashboard.value = body;
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
      } finally {
        dashboardLoading.value = false;
      }
    }

    async function loadData() {
      if (!can('cases.read.all') && !can('cases.read.own')) {
        loading.value = false;
        cases.value = [];
        summary.value = { total: 0, draft: 0, posted: 0, closed: 0, reversed: 0 };
        return;
      }
      loading.value = true; error.value = '';
      try {
        const response = await fetch('/api/cases', { headers: { Accept: 'application/json' }, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status));
        cases.value = Array.isArray(body.cases) ? body.cases : [];
        summary.value = body.summary || summary.value;
      } catch (err) { error.value = err instanceof Error ? err.message : String(err); }
      finally { loading.value = false; }
    }

    async function loadProductionPreview() {
      if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(String(productionMonth.value || ''))) {
        error.value = 'Report month must use YYYY-MM.';
        return;
      }
      productionLoading.value = true;
      error.value = '';
      try {
        const response = await fetch('/api/production-report?month=' + encodeURIComponent(productionMonth.value), {
          headers: { Accept: 'application/json' },
          cache: 'no-store'
        });
        const body = await response.json();
        if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status));
        productionPreview.value = body;
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
      } finally {
        productionLoading.value = false;
      }
    }

    async function productionAction(action, payload = {}) {
      productionSaving.value = action;
      error.value = '';
      try {
        const response = await fetch('/api/production-report', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ action, month: productionMonth.value, ...payload })
        });
        const body = await response.json();
        if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status));
        await loadProductionPreview();
        return body;
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        error.value = message;
        ElementPlus.ElMessage.error(message);
        return null;
      } finally { productionSaving.value = ''; }
    }

    async function excludeProductionRow(row, scope) {
      let answer;
      try {
        answer = await ElementPlus.ElMessageBox.prompt(
          `Reason for excluding ${scope === 'case' ? 'this case / installment' : 'this reinsurer'} (it will move to the next open month):`,
          'Exclude and defer',
          { confirmButtonText: 'Exclude', cancelButtonText: 'Cancel', inputValidator: (value) => String(value || '').trim() ? true : 'Reason is required.' }
        );
      } catch { return; }
      const body = await productionAction('exclude', { rowId: row.id, scope, reason: answer.value });
      if (body) ElementPlus.ElMessage.success(`Item deferred to ${body.exclusion.deferred_to}`);
    }

    async function generateProductionReport() {
      const body = await productionAction('generate', { sourceSignature: productionPreview.value.sourceSignature });
      if (body) ElementPlus.ElMessage.success(`Production Report ${body.report.month} V${body.report.version} generated`);
    }

    async function closeProductionReport(report) {
      try {
        await ElementPlus.ElMessageBox.confirm(
          `Close ${report.month} using V${report.version}? This cannot be reopened.`,
          'Close Production month',
          { confirmButtonText: 'Close month', cancelButtonText: 'Cancel', type: 'warning' }
        );
      } catch { return; }
      const body = await productionAction('close', {
        reportUid: report.reportUid,
        rowVersion: report.rowVersion,
        sourceSignature: productionPreview.value.sourceSignature
      });
      if (body) ElementPlus.ElMessage.success(`Production Report ${body.month} closed · ${body.confirmedCases} case(s) fully Confirmed`);
    }

    async function downloadProductionReport(report) {
      try {
        if (!window.RIProductionXlsx) throw new Error('Production Report Excel generator is unavailable.');
        await window.RIProductionXlsx.download(report, productionPreview.value.headers);
        ElementPlus.ElMessage.success(`Production Report ${report.month} V${report.version} saved`);
      } catch (err) {
        ElementPlus.ElMessage.error(err instanceof Error ? err.message : String(err));
      }
    }

    async function loadFxRates() {
      fxLoading.value = true;
      error.value = '';
      try {
        const response = await fetch('/api/fx-rates', { headers: { Accept: 'application/json' }, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status));
        fxRates.value = Array.isArray(body.rates) ? body.rates : [];
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
      } finally {
        fxLoading.value = false;
      }
    }

    function populateFxMonth(yearMonth) {
      const existingRows = fxRates.value.filter((item) => item.yearMonth === yearMonth);
      const byCurrency = new Map(existingRows.map((item) => [item.currency, item]));
      fxForm.existingMonth = existingRows.length > 0;
      fxForm.rates = FX_CURRENCIES.map((currency) => {
        const existing = byCurrency.get(currency);
        return {
          currency,
          rate: existing ? Number(existing.rate) : null,
          rowVersion: existing ? Number(existing.rowVersion) : null,
          isLocked: Boolean(existing?.isLocked)
        };
      });
    }

    function openFxDialog(row = null) {
      fxForm.yearMonth = row?.yearMonth || currentMonth();
      populateFxMonth(fxForm.yearMonth);
      fxDialogVisible.value = true;
    }

    function onFxMonthChange(yearMonth) {
      if (/^\d{4}-(0[1-9]|1[0-2])$/.test(String(yearMonth || ''))) {
        populateFxMonth(yearMonth);
      }
    }

    async function saveFxRate() {
      if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(String(fxForm.yearMonth || ''))) {
        ElementPlus.ElMessage.error('Select a valid Performance month.');
        return;
      }
      for (const row of fxForm.rates) {
        const rate = Number(row.rate);
        if (!Number.isFinite(rate) || rate <= 0 || rate > 1000) {
          ElementPlus.ElMessage.error(`${row.currency} Rate to TWD is required and must be no more than 1000.`);
          return;
        }
      }
      fxSaving.value = true;
      error.value = '';
      try {
        const response = await fetch('/api/fx-rates', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({
            yearMonth: fxForm.yearMonth,
            rates: fxForm.rates.map((row) => ({
              currency: row.currency,
              rate: Number(row.rate),
              rowVersion: row.rowVersion
            }))
          })
        });
        const body = await response.json();
        if (!response.ok) {
          const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status));
          requestErr.status = response.status;
          throw requestErr;
        }
        fxDialogVisible.value = false;
        ElementPlus.ElMessage.success('Monthly FX rates saved');
        await loadFxRates();
        if (productionMonth.value === fxForm.yearMonth) await loadProductionPreview();
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
        reportWriteError(err, () => loadFxRates());
      } finally {
        fxSaving.value = false;
      }
    }

    function departmentLabel(value) {
      return PERSONNEL_DEPARTMENTS.find((item) => item.value === value)?.label || value || '—';
    }

    function roleLabel(value) {
      return PERSONNEL_ROLES.find((item) => item.value === value)?.label || value || '—';
    }

    async function initialize() {
      authLoading.value = true;
      error.value = '';
      try {
        const response = await fetch('/api/app-context', { headers: { Accept: 'application/json' }, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status));
        principal.value = body.principal;
        if (!navigation.value.some((item) => item.id === activeView.value)) {
          activeView.value = navigation.value[0]?.id || 'dashboard';
        }
        await loadData();
        if (activeView.value === 'dashboard') await loadDashboard();
        if (activeView.value === 'production') await loadProductionPreview();
        if (activeView.value === 'fxrates') await loadFxRates();
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
        loading.value = false;
      } finally {
        authLoading.value = false;
      }
    }

    function accountStatusLabel(value) {
      return {
        not_configured: 'Not enabled yet',
        pending: 'Pending activation',
        active: 'Active',
        disabled: 'Disabled'
      }[value] || value || 'Not enabled yet';
    }

    // RI account activation, real Personnel and account mapping remain deferred until company-VM migration.

    async function loadRecycleBin() {
      recycleLoading.value = true;
      error.value = '';
      try {
        const response = await fetch('/api/draft-recycle-bin', { headers: { Accept: 'application/json' }, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status));
        recycleItems.value = Array.isArray(body.items) ? body.items : [];
        recyclePolicy.value = { retentionYears: Number(body.retentionYears || 5), permanentDeleteAllowed: body.permanentDeleteAllowed === true };
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
      } finally {
        recycleLoading.value = false;
      }
    }

    async function recycleDraft(row) {
      try {
        await ElementPlus.ElMessageBox.confirm(
          'Move this Draft to the recycle bin? It can be restored for five years and cannot be permanently deleted by any role.',
          'Recycle Draft',
          { type: 'warning', confirmButtonText: 'Move to recycle bin', cancelButtonText: 'Cancel' }
        );
      } catch (_) { return; }
      recycleSaving.value = true;
      try {
        const response = await fetch('/api/draft-recycle-bin', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ action: 'recycle', caseUid: row.caseUid, rowVersion: Number(row.rowVersion) })
        });
        const body = await response.json();
        if (!response.ok) {
          const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status));
          requestErr.status = response.status;
          throw requestErr;
        }
        ElementPlus.ElMessage.success('Draft moved to the five-year recycle bin.');
        await loadData();
      } catch (err) {
        reportWriteError(err, () => Promise.all([loadRecycleBin(), loadData()]));
      } finally {
        recycleSaving.value = false;
      }
    }

    async function restoreDraft(row) {
      recycleSaving.value = true;
      try {
        const response = await fetch('/api/draft-recycle-bin', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ action: 'restore', recycleId: Number(row.id) })
        });
        const body = await response.json();
        if (!response.ok) {
          const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status));
          requestErr.status = response.status;
          throw requestErr;
        }
        ElementPlus.ElMessage.success('Draft restored to Account List.');
        await Promise.all([loadRecycleBin(), loadData()]);
      } catch (err) {
        reportWriteError(err, () => Promise.all([loadRecycleBin(), loadData()]));
      } finally {
        recycleSaving.value = false;
      }
    }

    async function loadReconciliation() {
      reconciliationLoading.value = true;
      error.value = '';
      try {
        const response = await fetch('/api/data-reconciliation', { headers: { Accept: 'application/json' }, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status));
        reconciliation.value = body;
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
      } finally {
        reconciliationLoading.value = false;
      }
    }

    async function loadAuditLog() {
      auditLoading.value = true;
      error.value = '';
      try {
        const response = await fetch('/api/audit-log?limit=250', { headers: { Accept: 'application/json' }, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status));
        auditEvents.value = Array.isArray(body.events) ? body.events : [];
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
      } finally {
        auditLoading.value = false;
      }
    }

    function onOwnerSelected(personnelId) {
      const person = personnelRecords.value.find((row) => Number(row.id) === Number(personnelId));
      draft.ownerPersonnelName = person?.name || '';
    }

    async function loadPersonnelOptions() {
      try {
        const response = await fetch('/api/personnel-options', { headers: { Accept: 'application/json' }, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status));
        personnelRecords.value = Array.isArray(body.personnel) ? body.personnel : [];
        if (activeView.value === 'case-create' && !isEditing.value && !draft.ownerPersonnelId && body.defaultOwnerId) {
          draft.ownerPersonnelId = Number(body.defaultOwnerId);
          onOwnerSelected(draft.ownerPersonnelId);
        }
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
      }
    }

    async function loadPersonnel() {
      personnelLoading.value = true;
      error.value = '';
      try {
        const response = await fetch('/api/personnel', { headers: { Accept: 'application/json' }, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status));
        personnelRecords.value = Array.isArray(body.personnel) ? body.personnel : [];
        personnelCounts.value = body.counts || personnelCounts.value;
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
        ElementPlus.ElMessage.error(error.value);
      } finally {
        personnelLoading.value = false;
      }
    }

    function openPersonnelDialog(row = null) {
      editingPersonnelId.value = row ? Number(row.id) : null;
      editingPersonnelRowVersion.value = row ? Number(row.rowVersion) : null;
      Object.assign(personnelForm, row
        ? {
            name: row.name || '', email: row.email || '', department: row.department,
            roleCode: row.roleCode, isActive: Boolean(row.isActive),
            isSplitEligible: Boolean(row.isSplitEligible),
            supervisorName: row.supervisorName || '', supervisorEmail: row.supervisorEmail || ''
          }
        : {
            name: '', email: '', department: 'reinsurance', roleCode: 'sales',
            isActive: false, isSplitEligible: defaultSplitEligibility('reinsurance', 'sales'), supervisorName: '', supervisorEmail: ''
          });
      personnelDialogVisible.value = true;
    }

    function onPersonnelDepartmentChange(value) {
      if (!editingPersonnelId.value) personnelForm.roleCode = DEFAULT_ROLE_BY_DEPARTMENT[value] || 'viewer';
      personnelForm.isSplitEligible = defaultSplitEligibility(value, personnelForm.roleCode);
      personnelForm.supervisorName = '';
      personnelForm.supervisorEmail = '';
    }

    function onPersonnelRoleChange(value) {
      personnelForm.isSplitEligible = defaultSplitEligibility(personnelForm.department, value);
    }

    function onSupervisorSelected(value) {
      const supervisor = supervisorOptions.value.find((person) => person.name === value);
      personnelForm.supervisorEmail = supervisor?.email || '';
    }

    async function savePersonnel() {
      if (!String(personnelForm.name || '').trim()) return ElementPlus.ElMessage.error('Personnel name is required');
      personnelSaving.value = true;
      error.value = '';
      try {
        const updating = Boolean(editingPersonnelId.value);
        const response = await fetch('/api/personnel', {
          method: updating ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({
            ...personnelForm,
            id: editingPersonnelId.value,
            rowVersion: editingPersonnelRowVersion.value
          })
        });
        const body = await response.json();
        if (!response.ok) {
          const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status));
          requestErr.status = response.status;
          throw requestErr;
        }
        personnelDialogVisible.value = false;
        await loadPersonnel();
        ElementPlus.ElMessage.success(updating ? 'Personnel updated' : 'Personnel added');
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
        reportWriteError(err, () => loadPersonnel());
      } finally {
        personnelSaving.value = false;
      }
    }

    async function togglePersonnelStatus(row) {
      personnelSaving.value = true;
      error.value = '';
      try {
        const response = await fetch('/api/personnel', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({
            ...row,
            roleCode: row.roleCode,
            rowVersion: row.rowVersion,
            isActive: !row.isActive
          })
        });
        const body = await response.json();
        if (!response.ok) {
          const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status));
          requestErr.status = response.status;
          throw requestErr;
        }
        await loadPersonnel();
        ElementPlus.ElMessage.success(body.person.isActive ? 'Personnel reactivated' : 'Personnel deactivated');
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
        reportWriteError(err, () => loadPersonnel());
      } finally {
        personnelSaving.value = false;
      }
    }

    async function loadDashboardTargets() {
      targetLoading.value = true;
      error.value = '';
      try {
        const response = await fetch('/api/dashboard-targets', { headers: { Accept: 'application/json' }, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status));
        dashboardTargets.value = Array.isArray(body.targets) ? body.targets : [];
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
        ElementPlus.ElMessage.error(error.value);
      } finally {
        targetLoading.value = false;
      }
    }

    function openTargetDialog(row = null, periodType = 'annual') {
      Object.assign(targetForm, row
        ? {
            id: Number(row.id), periodType: row.periodType, periodKey: row.periodKey,
            amount: Number(row.amount), rowVersion: Number(row.rowVersion), isActive: Boolean(row.isActive)
          }
        : {
            id: null, periodType,
            periodKey: periodType === 'annual' ? currentYear() : currentMonth(),
            amount: null, rowVersion: null, isActive: true
          });
      targetDialogVisible.value = true;
    }

    function onTargetTypeChange(value) {
      if (targetForm.id) return;
      targetForm.periodKey = value === 'annual' ? currentYear() : currentMonth();
    }

    async function saveDashboardTarget() {
      const amount = Number(targetForm.amount);
      if (!Number.isFinite(amount) || amount < 0) return ElementPlus.ElMessage.error('Target must be a non-negative amount');
      targetSaving.value = true;
      error.value = '';
      try {
        const updating = Boolean(targetForm.id);
        const response = await fetch('/api/dashboard-targets', {
          method: updating ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ ...targetForm, amount })
        });
        const body = await response.json();
        if (!response.ok) {
          const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status));
          requestErr.status = response.status;
          throw requestErr;
        }
        targetDialogVisible.value = false;
        await loadDashboardTargets();
        ElementPlus.ElMessage.success(updating ? 'Target updated' : 'Target added');
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
        reportWriteError(err, () => loadDashboardTargets());
      } finally {
        targetSaving.value = false;
      }
    }

    async function toggleDashboardTarget(row) {
      targetSaving.value = true;
      error.value = '';
      try {
        const response = await fetch('/api/dashboard-targets', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ ...row, isActive: !row.isActive })
        });
        const body = await response.json();
        if (!response.ok) {
          const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status));
          requestErr.status = response.status;
          throw requestErr;
        }
        await loadDashboardTargets();
        ElementPlus.ElMessage.success(body.target.isActive ? 'Target reactivated' : 'Target deactivated');
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
        reportWriteError(err, () => loadDashboardTargets());
      } finally {
        targetSaving.value = false;
      }
    }

    async function saveDraft() {
      const updating = isEditing.value;
      // Bugfix (#7): saving an edit to a Reversed case silently re-Announces
      // it (moves it back to 'posted'), skipping the document review/confirm
      // step Announce itself requires. Ask for the same kind of explicit
      // confirmation here before sending the request, and tell the backend
      // it was confirmed (it independently enforces this — see api/cases.js).
      const wasReversed = editingOriginalStatus.value === 'reversed';
      if (updating && wasReversed) {
        try {
          await ElementPlus.ElMessageBox.confirm(
            'This case was Reversed. Saving will correct it and move it back to Announced status, without repeating the original Announce document review. Continue?',
            'Confirm correction',
            { confirmButtonText: 'Save and move to Announced', cancelButtonText: 'Cancel', type: 'warning' }
          );
        } catch { return; }
      }
      saving.value = true; error.value = ''; saveMessage.value = '';
      try {
        const response = await fetch('/api/cases', {
          method: updating ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify(updating
            ? { caseUid: editingCaseUid.value, rowVersion: editingRowVersion.value, case: plainDraft(), reverseCorrectionConfirmed: wasReversed }
            : { case: plainDraft() })
        });
        const body = await response.json();
        if (!response.ok) {
          const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status));
          requestErr.status = response.status;
          throw requestErr;
        }
        if (updating) editingRowVersion.value = Number(body.case.rowVersion);
        const wasAnnounced = editingOriginalStatus.value === 'posted';
        saveMessage.value = updating
          ? `${wasReversed ? 'Reversed case corrected and moved to Announced' : wasAnnounced ? 'Announced case' : 'Draft'} · version ${body.case.rowVersion}.`
          : 'Draft saved. Reference will be assigned later in the confirmed workflow.';
        ElementPlus.ElMessage.success(updating
          ? (wasReversed ? 'Correction saved — case moved to Announced; record Accounting notification' : wasAnnounced ? 'Announced case updated — record Accounting notification if required' : 'Draft updated')
          : 'Draft saved');
        await loadData();
        if (updating) {
          const savedCase = { caseUid: body.case.caseUid, status: body.case.status };
          resetDraft();
          await startViewCase(savedCase);
        } else {
          activeView.value = 'cases';
          resetDraft();
          window.scrollTo({ top: 0 });
        }
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
        reportWriteError(err, () => refreshSelectedCase());
      } finally { saving.value = false; }
    }

    onMounted(initialize);
    return {
      navigation, roadmap, activeView, currentHeader, pendingDescription, loading, saving, error, saveMessage,
      dashboardLoading, dashboard, dashboardTrendMax, dashboardTrendX, dashboardTrendY, dashboardTrendPoints, dashboardTrendSeries, loadDashboard,
      principal, authLoading, can,
      filters, caseSummary, filteredCases, caseFilterOptions, draft, openSections, selectView, startNewCase, cancelNewCase,
      recycleLoading, recycleSaving, recycleItems, recyclePolicy, loadRecycleBin, recycleDraft, restoreDraft,
      addSituation, removeSituation, addReinsurer, removeReinsurer, addSumInsured, removeSumInsured,
      isEditing, isEndorsementDraft, editingRowVersion, editingOriginalStatus, endorsementFieldsUnlocked, startEditCase, startViewCase,
      casePreviewVisible, casePreview, openCasePreview, openPreviewFullCase, formatPolicyDateTime, formatPolicyPeriod,
      selectedCase, selectedPayload, selectedOverview, selectedCaseTransactions, caseDetailLoading, caseDetailTab, caseDetailTabLabel, backToCases, editSelectedCase,
      caseWorkflow, workflowLoading, workflowSaving, loadCaseWorkflow, createEndorsement, createRenewal, reverseSelectedCase, viewWorkflowCase,
      accountingDialogVisible, accountingForm, openAccountingNotification, saveAccountingNotification,
      accountingLoading, accountingSaving, accountingRows, filteredAccountingRows, accountingCurrencies, accountingScope, accountingSelection, accountingFilters,
      accountingPaymentDialogVisible, accountingPaymentRow, schedulePaymentForm,
      loadAccounting, onAccountingSelectionChange, accountingRowSelectable, settleSelectedTransactions, openAccountingCase,
      openSchedulePayment, recordSchedulePayment, reverseSchedulePayment, paymentStatusLabel, paymentStatusType,
      claimsLoading, claimsSaving, claimsState, claimForm, paymentDialogVisible, paymentForm, createClaim, updateClaimReserve, openClaimPayment, recordClaimPayment, claimTotalPaid, loadClaims,
      documentsLoading, documentsSaving, documentGenerating, caseDocuments, documentCoverage, signedSlipReminder, documentForm, documentFileList, selectedReinsurers, documentReadinessText, selectedAnnounceIssues,
      generatedDocumentCase, downloadGeneratedDocument, loadCaseDocuments, onCaseDetailTabChange, onDocumentKindChange, onDocumentFileChange, onDocumentFileRemove, uploadCaseDocument,
      toggleDocumentSelection, downloadCaseDocument, deleteCaseDocument, documentKindLabel, displayReinsurerName, formatFileSize, formatDateTime,
      announceDialogVisible, announceConfirmed, announcing, openAnnounceReview, announceSelectedCase,
      productionLoading, productionSaving, productionMonth, productionPreview, loadProductionPreview,
      excludeProductionRow, generateProductionReport, closeProductionReport, downloadProductionReport,
      fxLoading, fxSaving, fxDialogVisible, fxRates, fxForm, loadFxRates, openFxDialog, onFxMonthChange, saveFxRate,
      personnelLoading, personnelSaving, personnelDialogVisible, personnelRecords, sortedPersonnelRecords, personnelCounts, personnelTab,
      personnelForm, editingPersonnelId, personnelDepartments: PERSONNEL_DEPARTMENTS, personnelRoles: PERSONNEL_ROLES,
      loadPersonnel, openPersonnelDialog, supervisorOptions, onPersonnelDepartmentChange, onPersonnelRoleChange, onSupervisorSelected, savePersonnel, togglePersonnelStatus,
      onOwnerSelected,
      departmentLabel, roleLabel, accountStatusLabel,
      targetLoading, targetSaving, targetDialogVisible, dashboardTargets, targetForm,
      loadDashboardTargets, openTargetDialog, onTargetTypeChange, saveDashboardTarget, toggleDashboardTarget,
      masterTypes, activeMdmType, mdmRecords, mdmCounts, filteredMasterRecords, mdmLoading, mdmSaving,
      mdmDialogVisible, mdmForm, mdmClauseDraft, mdmRatingDraft, editingMasterId, masterTypeLabel, loadMasterData, openMasterDialog, saveMasterRecord, toggleMasterStatus, addMdmFixedClause, removeMdmFixedClause, addMdmRating, removeMdmRating,
      isUniversalClauseCode, clauseSourceType, clauseUsedByReinsurers, availableClauseOptions, onMdmClauseDraftSelect,
      masterOptions, onClassSelected, structureLabel, recomputeType, onStructureSelected, onReinsurerSelected,
      caseClauseDraft, addCaseClause, removeCaseClause, isManualClause, clauseSourceLabel,
      reviewAttempted, reviewReady, validationMessage, fieldInvalid, rowInvalid, reviewAndConfirm,
      reviewDialogVisible, totalOrderHereon, totalSumInsured, allFacilityReinsurers, hasNonFacilityReinsurer, lossRecordSummary, installmentAllocations, installmentStatus,
      addInstallment, removeInstallment, onInstallmentToggle, installmentRowInvalid,
      splitStatus, onSplitToggle, splitPartyInvalid, splitPersonOptions, onSplitPersonSelected,
      formatAmount, formatThousands, formatFxRate, formatMoney, formatCurrency, saveReviewedDraft,
      addLossRecord, removeLossRecord, lossRowInvalid,
      reconciliationLoading, reconciliation, loadReconciliation,
      auditLoading, auditEvents, loadAuditLog,
      statusLabel, loadData, saveDraft
    };
  }
}).use(ElementPlus).mount('#app');