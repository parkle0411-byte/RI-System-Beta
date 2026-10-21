import { premiumInputErrors, premiumPeriodAmounts } from '../alpha/lib/accounting.js'
// 案件工作區邏輯直接在此維護；現行規則以 VM-RULES.md 為準。
// 模板直接維護於 CaseWorkspace.vue。
//
// 與 Alpha 不同的地方（都記在 VM-RULES.md）：
//   - fetch() → apiFetch()（補上 CSRF 與同源 cookie；回傳一樣的 Response）
//   - 金額合計用統一的逐步進位算法（src/alpha/caseCalculations.js）
//   - startEditCase 允許 Reversed（Alpha 漏了，「Correct reversed case」按了沒反應）
//   - 文件單檔上限 10 MB（Alpha 5 MB）
//   - 從 Accounting 點 TW Ref 會帶 ?case=…&tab=soa 過來（Alpha 是同一頁切換）：載入後直接開該案件的 SOA 分頁
//   - 理賠：出險日與付款日期必填（後端檢查，錯誤訊息照常顯示）
//   - 產生 Word／PDF 文件的程式尚未移植：產生文件的按鈕停用
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch, watchEffect } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { apiFetch } from '../api'
import { generateDocx } from '../alpha/documents'
import { resolveClauseTitles } from '../alpha/clauseTitles'
import { auth, can } from '../auth'
import { RICaseCalculations } from '../alpha/caseCalculations'
import {
  FIXED_TEXT, STRUCTURE_SUFFIX, UNIVERSAL_CLAUSES, clientKey, compareClauses, emptyDraft, normalizeClauseCode, normalizeClauseList
} from '../alpha/constants'
import {
  departmentLabel, filled, formatAmount, formatCurrency, formatDateTime, formatFileSize, formatMoney, formatMoneyInput, parseMoneyInput,
  formatPolicyDateTime, formatPolicyPeriod, jsonOrThrow, reportWriteError, statusLabel, structureLabel
} from '../alpha/format'
import { setHeader, shell } from '../alpha/shell'
import { AUW_FOREIGN_BROKER, displayTwRef, isAuwReinsurer, isPureAuwCase, requiresManualTwRef } from '../alpha/manualTwRef'
import { isAllianzReinsurer, hasAllianz } from '../alpha/allianzFacility'
import { isGreatAmericanTarget, hasGreatAmerican } from '../alpha/greatAmericanFacility'
import { allSumInsuredFacility, sumLocationIndex, sumInsuredPlacementIssues, mergeFacilitySumItems, sumInsuredLimitWarning } from '../alpha/sumInsured'
import { transactionNumber } from '../alpha/transactionNumber'
import { isSwissFacility, isSwissPropertyCase } from '../alpha/swissFacility'
import { transactionParty, transactionRecipient, paymentDirection } from '../alpha/transactionParty'
import { isStandardCgl, emptyCglInformation, cglInformationIssues } from '../alpha/cglInformation'
import { CGL_INTEREST, cglTypePrefix, cglType, cglTypeIssues, cglUnderlyingIssues, liabilityLimitLabel, cglRiskDetailsIssues, CGL_CLAUSE_PRESETS, cglAnnual } from '../alpha/cglRiskDetails'

const MAX_DOCUMENT_BYTES = 10 * 1024 * 1024 // VM：10 MB（Alpha 5 MB）
const OPEN_SECTIONS = ['risk', 'security', 'terms', 'information', 'occupation', 'sumInsured', 'loss', 'specialAgreement', 'cedantPremium', 'reinsurerPremium', 'split', 'conditions']
const headers = {
  cases: { kicker: 'Placement', title: 'Account List', subtitle: 'All outward cases' },
  'case-create': { kicker: 'Placement · Draft', title: 'Account', subtitle: 'Draft — not yet saved' },
  'case-detail': { kicker: 'Placement · Case', title: 'Case overview', subtitle: 'Saved case snapshot and computed amounts' }
}

export function useCaseWorkspace() {
  const activeView = ref('cases')
  const loading = ref(true)
  const saving = ref(false)
  const saveMessage = ref('')
  const reviewAttempted = ref(false)
  const lossSaveAttempted = ref(false)
  const manualRefSaveAttempted = ref(false)
  const auwBoundRows = new WeakSet()
  const reviewDialogVisible = ref(false)
  const editingCaseUid = ref('')
  const editingRowVersion = ref(null)
  const editingOriginalStatus = ref('draft')
  const endorsementFieldsUnlocked = ref(false)
  const mdmRecords = ref([])
  const caseClauseDraft = reactive({ code: '', title: '' })
  const selectedCase = ref(null)
  const casePreviewVisible = ref(false)
  const casePreview = ref(null)
  const caseDetailLoading = ref(false)
  const caseDetailTab = ref('overview')
  const documentsLoading = ref(false)
  const documentsSaving = ref(false)
  const documentGenerating = ref('')
  const caseDocuments = ref([])
  const documentCoverage = ref({ offer: false, required: [], covered: [], missing: [], ready: false, selected: [] })
  const signedSlipReminder = ref({ complete: false, missing: [], eligibleStatus: false, daysSinceEffective: null, firstReminderOn: '', due: false, today: '', cadenceDays: 7, outboundEnabled: false })
  const documentForm = reactive({ kind: 'offer', reinsurers: [], file: null })
  const documentFileList = ref([])
  const caseWorkflow = ref(null)
  const workflowLoading = ref(false)
  const workflowSaving = ref(false)
  const accountingDialogVisible = ref(false)
  const accountingForm = reactive({ accountingPersonnelId: null, note: '' })
  const announceDialogVisible = ref(false)
  const announceConfirmed = ref(false)
  const announcing = ref(false)
  const personnelRecords = ref([])
  const cases = ref([])
  const recycleSaving = ref(false)
  const summary = ref({ total: 0, draft: 0, posted: 0, closed: 0, reversed: 0 })
  const filters = reactive({ search: '', status: 'all', year: 'all', className: 'all', reinsurer: 'all', reinsured: 'all', aeName: 'all' })
  const draft = reactive(emptyDraft())
  const isCglInformation = computed(() => isStandardCgl(draft))
  const gaBoundRows = new WeakMap()
  watchEffect(() => {
    draft.reinsurers.forEach((row,index) => {
      const bound = gaBoundRows.get(row)
      if (isGreatAmericanTarget(draft,row.name)) {
        const prior = bound || {days:row.paymentTermsDays,periods:new WeakMap()}
        gaBoundRows.set(row,prior)
        row.paymentTermsDays = 90
        draft.performanceInstallments.forEach(period => {
          if (!period.reinsurerPaymentTerms || typeof period.reinsurerPaymentTerms !== 'object') period.reinsurerPaymentTerms = {}
          if (!prior.periods.has(period)) prior.periods.set(period,period.reinsurerPaymentTerms['r'+(index+1)])
          period.reinsurerPaymentTerms['r'+(index+1)] = 90
        })
      } else if (bound) {
        if (!isAuwReinsurer(row.name) && !isAllianzReinsurer(row.name) && !(isSwissPropertyCase(draft)&&isSwissFacility(row.name))) {
          row.paymentTermsDays = bound.days ?? null
          draft.performanceInstallments.forEach(period => {
            const key='r'+(index+1),prior=bound.periods.get(period)
            if (period.reinsurerPaymentTerms) { if(prior==null) delete period.reinsurerPaymentTerms[key]; else period.reinsurerPaymentTerms[key]=prior }
          })
        }
        gaBoundRows.delete(row)
      }
    })
  })
  const allianzBoundRows = new WeakSet()
  watchEffect(() => {
    draft.reinsurers.forEach((row,index) => {
      if (!isAllianzReinsurer(row.name)) return
      row.paymentTermsDays = 90
      allianzBoundRows.add(row)
      draft.performanceInstallments.forEach(period => {
        if (!period.reinsurerPaymentTerms || typeof period.reinsurerPaymentTerms !== "object") period.reinsurerPaymentTerms = {}
        period.reinsurerPaymentTerms["r" + (index+1)] = 90
      })
    })
  })
  const isSwissProperty = computed(() => isSwissPropertyCase(draft))
  watchEffect(() => {
    if (!isSwissProperty.value) return
    draft.paymentTermsDays = 90
    draft.reinsurers.forEach(row => { if (isSwissFacility(row.name)) row.paymentTermsDays = 90 })
    draft.performanceInstallments.forEach(row => {
      row.paymentTermsDays = 90
      draft.reinsurers.forEach((r,index) => { if (isSwissFacility(r.name)) row.reinsurerPaymentTerms["r" + (index+1)] = 90 })
    })
  })
  watchEffect(() => {
    if (!isCglInformation.value) return
    const info = draft.cglInformation
    if (!info.estimatedTurnover.length) info.estimatedTurnover.push({ clientKey: clientKey(), region: '', currency: draft.currency || '', amount: null })
    info.estimatedTurnover.forEach(row => { if (!row.currency && draft.currency) row.currency = draft.currency })
  })
  let autoPolicyTo = ''
  let sumInsuredFacilityMode = null
  const openSections = ref([...OPEN_SECTIONS])
  const reviewReady = computed(() => reviewAttempted.value && collectRequiredIssues().length === 0)
  const validationMessage = computed(() => {
    if (!reviewAttempted.value) return ''
    const count = collectRequiredIssues().length
    return count === 0
      ? 'All required fields are complete. This draft is ready for the confirmation workflow milestone.'
      : `Please complete ${count} required field${count === 1 ? '' : 's'} before Review & confirm.`
  })
  const hasManualTwRefReinsurer = computed(() => requiresManualTwRef(draft))
  const totalOrderHereon = computed(() => RICaseCalculations.totalOrderHereon(draft))
  const isFacilityName = (name) => /\(Facility\)\s*$/i.test(String(name || '').trim())
  const selectedDraftReinsurers = computed(() => draft.reinsurers.filter((row) => String(row.name || '').trim()))
  const allFacilityReinsurers = computed(() => selectedDraftReinsurers.value.length > 0 && selectedDraftReinsurers.value.every((row) => isFacilityName(row.name)))
  const sumInsuredGroups = computed(() => {
    const indexed = draft.sumInsured.map((row, index) => ({ row, index }))
    if (allFacilityReinsurers.value) return [{ key: 'facility', label: 'Items', locationIndex: null, address: '', postcode: '', rows: indexed }]
    return draft.situations.map((situation, index) => ({ key: situation.clientKey, label: `Location ${index + 1}`, locationIndex: index, address: situation.address, postcode: situation.postcode, rows: indexed.filter(item => sumLocationIndex(item.row, draft.situations.length) === index) }))
  })
  const unassignedSumInsured = computed(() => allFacilityReinsurers.value ? [] : draft.sumInsured.map((row, index) => ({ row, index })).filter(item => sumLocationIndex(item.row, draft.situations.length) === null))
  function sumGroupInvalid(index) { return reviewAttempted.value && !draft.sumInsured.some(row => sumLocationIndex(row, draft.situations.length) === index) }
  function syncSumInsuredMode() {
    if (!draft.reinsurers.some(row => String(row.name || '').trim())) return
    const facility = allSumInsuredFacility(draft)
    if (sumInsuredFacilityMode !== null && facility !== sumInsuredFacilityMode) {
      // 2026-10-14：改成混合時保留已指到有效 Location 的項目，只清空沒有有效 Location 的（與後端 prepare_transition 一致）
      draft.sumInsured = facility ? mergeFacilitySumItems(draft.sumInsured) : draft.sumInsured.map(row => sumLocationIndex(row, draft.situations.length) === null ? { ...row, locationIndex: null } : row)
      ElMessage.info(facility ? 'Matching Sum Insured items have been combined into Facility totals.' : 'Allocate the existing Sum Insured items to Locations before Review & Announce.')
    }
    sumInsuredFacilityMode = facility
  }
  const hasNonFacilityReinsurer = computed(() => selectedDraftReinsurers.value.some((row) => !isFacilityName(row.name)))
  const totalSumInsured = computed(() => RICaseCalculations.totalSumInsured(draft))
  const draftSumInsuredWarning = computed(() => isStandardCgl(draft) ? null : sumInsuredLimitWarning(draft))
  const lossRecordSummary = computed(() => lossRecordSummaryFor(draft))
  const lossRecordYearsMin = computed(() => validLossRecordYears(0, draft) ? 0 : 1)
  const installmentAllocations = computed(() => installmentAllocationsFor(draft))
  const installmentStatus = computed(() => installmentValidationFor(draft))
  const splitStatus = computed(() => splitValidationFor(draft))

  const isEditing = computed(() => Boolean(editingCaseUid.value))
  const isEndorsementDraft = computed(() => Boolean(draft.parentTwRef))
  watch(isCglInformation, (standardCgl) => {
    if (activeView.value !== 'case-create') return
    if (!isEditing.value && !draft.parentTwRef && !draft.renewedFromTwRef
      && [FIXED_TEXT.interest, CGL_INTEREST].includes(draft.interest)) {
      draft.interest = standardCgl ? CGL_INTEREST : FIXED_TEXT.interest
    }
    recomputeType()
  })
  const auwRefLocked = computed(() => isEditing.value && editingOriginalStatus.value !== 'draft' && draft.twRefSource === 'auw_manual')
  const selectedPayload = computed(() => selectedCase.value?.payload || {})
  const draftClauseDetails = computed(() => resolveClauseTitles(draft.clauseDetails, mdmRecords.value, draft))
  const selectedSumInsuredIssues = computed(() => sumInsuredPlacementIssues(selectedPayload.value))
  const selectedSumInsuredWarning = computed(() => isStandardCgl(selectedPayload.value) ? null : sumInsuredLimitWarning(selectedPayload.value))
  const selectedOverview = computed(() => {
    const payload = selectedPayload.value
    const legs = RICaseCalculations.totals(payload)
    const flipped = legs.leg1 < 0
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
      clauseDetails: resolveClauseTitles(payload.clauseDetails?.length ? payload.clauseDetails : UNIVERSAL_CLAUSES, mdmRecords.value, payload).sort(compareClauses)
    }
  })
  const isTreatyDocumentCase = computed(() => String(selectedPayload.value.reinsuranceStructure || '').trim() === 'TREATY')
  const generatedDocumentCase = computed(() => {
    const payload = selectedPayload.value || {}
    const normalizedReinsured = String(payload.reinsured || '').trim().toLowerCase()
    const reinsuredMaster = mdmRecords.value.find((row) =>
      row.entityType === 'reinsured' && String(row.name || '').trim().toLowerCase() === normalizedReinsured
    )
    const aeName = String(payload.ae || '').trim()
    const aePerson = personnelRecords.value.find((row) => String(row.name || '').trim().toLowerCase() === aeName.toLowerCase())
    return {
      ...payload,
      caseUid: selectedCase.value?.caseUid || '',
      twRef: selectedCase.value?.twRef || payload.twRef || '',
      status: selectedCase.value?.status || payload.status || 'draft',
      reinsuredAddress: payload.reinsuredAddress || reinsuredMaster?.payload?.address || '',
      aeName,
      aeEmail: String(payload.aeEmail || '').trim() || String(aePerson?.email || '').trim(),
      clauseDetails: selectedOverview.value.clauseDetails
    }
  })
  function unsupportedDebitBankCurrency(caseData) {
    return ['QS', 'XOL'].includes(String(caseData?.reinsuranceStructure || '').trim())
      && !['USD', 'TWD'].includes(String(caseData?.currency ?? '').trim().toUpperCase())
  }
  function missingDebitPaymentTerms(caseData) {
    if (caseData?.installmentEnabled === true || !['QS', 'XOL'].includes(String(caseData?.reinsuranceStructure || '').trim())) return false
    const valid = (value) => Number.isInteger(Number(value)) && Number(value) >= 15
    const defaultValid = valid(caseData?.paymentTermsDays)
    const reinsurers = Array.isArray(caseData?.reinsurers) ? caseData.reinsurers : []
    return reinsurers.some(row => !isAuwReinsurer(row?.name) && !isAllianzReinsurer(row?.name) && !isGreatAmericanTarget(caseData,row?.name) && !(isSwissPropertyCase(caseData) && isSwissFacility(row?.name)) && !valid(row?.paymentTermsDays))
  }
  function missingDebitInstallmentBaseDates(caseData) {
    if (caseData?.installmentEnabled !== true || !['QS', 'XOL'].includes(String(caseData?.reinsuranceStructure || '').trim())) return false
    const valid = (value) => {
      if (typeof value !== 'string' || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value) || value.startsWith('0000-')) return false
      const date = new Date(`${value}T00:00:00Z`)
      return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value
    }
    const installments = caseData?.performanceInstallments
    return !Array.isArray(installments) || !installments.length || installments.some(row => !valid(row?.paymentBaseDate))
  }
  function missingDebitInstallmentPaymentTerms(caseData) {
    if (caseData?.installmentEnabled !== true || !['QS', 'XOL'].includes(String(caseData?.reinsuranceStructure || '').trim())) return false
    const valid = (value) => Number.isInteger(Number(value)) && Number(value) >= 15
    const installments = Array.isArray(caseData?.performanceInstallments) ? caseData.performanceInstallments : []
    const reinsurers = Array.isArray(caseData?.reinsurers) ? caseData.reinsurers : []
    return installments.some(installment => !valid(installment.paymentTermsDays) || reinsurers.some((reinsurer, index) => !isAuwReinsurer(reinsurer?.name) && !isAllianzReinsurer(reinsurer?.name) && !isGreatAmericanTarget(caseData,reinsurer?.name) && !(isSwissPropertyCase(caseData) && isSwissFacility(reinsurer?.name)) && !valid(installment?.reinsurerPaymentTerms?.[`r${index + 1}`])))
  }
  function missingDebitInstallmentAllocation(caseData) {
    if (caseData?.installmentEnabled !== true || !['QS', 'XOL'].includes(String(caseData?.reinsuranceStructure || '').trim())) return false
    const installments = Array.isArray(caseData?.performanceInstallments) ? caseData.performanceInstallments : []
    const filled = (value) => Boolean(String(value ?? '').trim())
    return installments.length > 0 && installments.some(row => !filled(row?.premium) && !filled(row?.ratio))
  }
  function invalidDebitInstallmentAllocation(caseData) {
    if (caseData?.installmentEnabled !== true || !['QS', 'XOL'].includes(String(caseData?.reinsuranceStructure || '').trim())) return false
    const installments = Array.isArray(caseData?.performanceInstallments) ? caseData.performanceInstallments : []
    return installments.some(row => {
      const premium = Number(row?.premium)
      const value = Number.isFinite(premium) && row?.premium !== '' && row?.premium != null ? premium : Number(row?.ratio)
      return !Number.isFinite(value) || value <= 0
    })
  }
  const selectedReinsurers = computed(() => {
    const seen = new Set()
    return (Array.isArray(selectedPayload.value.reinsurers) ? selectedPayload.value.reinsurers : [])
      .map((row) => ({ key: reinsurerKey(row?.name), label: String(row?.name || '').trim() }))
      .filter((row) => row.key && !seen.has(row.key) && seen.add(row.key))
  })
  const documentReadinessText = computed(() => {
    const coverage = documentCoverage.value
    if (coverage.ready) return 'Documents complete. This case is ready for the Review & Announce confirmation step.'
    const needs = []
    if (!coverage.offer) needs.push('Offer Slip')
    if ((coverage.missing || []).length) needs.push(`Signed Slip or Confirmation E-mail for ${coverage.missing.map(displayReinsurerName).join(', ')}`)
    if (!coverage.required?.length) needs.push('at least one named reinsurer in Schedule of Security')
    return `Not ready to Announce. Missing ${needs.join('; ')}.`
  })
  const selectedAnnounceIssues = computed(() => collectPayloadAnnounceIssues(selectedPayload.value))
  const caseDetailTabLabel = computed(() => ({ documents: 'Documentation', soa: 'SOA / Transactions', claims: 'Claim', endorsements: 'Endorsements', reminders: 'Reminders' }[caseDetailTab.value] || 'Case detail'))
  function reconciliationRefFor(caseData, transaction) {
    const leg = String(transaction?.legType || '')
    const isClaim = leg.startsWith('Claim')
    const cedantFacing = isClaim ? leg.startsWith('Claim Leg 2') : leg.startsWith('Leg 1')
    const reinsurerFacing = isClaim ? leg.startsWith('Claim Leg 1') : leg.startsWith('Leg 2')
    if (cedantFacing) return String(caseData?.statementNo || '')
    if (reinsurerFacing) {
      const index = Number.isInteger(transaction?.reinsurerIdx) ? transaction.reinsurerIdx : -1
      return index >= 0 ? String(caseData?.reinsurers?.[index]?.settlementRef || '') : ''
    }
    return ''
  }
  const selectedCaseTransactions = computed(() => (Array.isArray(selectedPayload.value.transactions) ? selectedPayload.value.transactions : []).map((transaction, index) => ({
    ...transaction,
    displayTxNo: transactionNumber(transaction.txNo),
    displayLabel: transactionRecipient(transaction, selectedPayload.value),
    displayParty: transactionParty(transaction, selectedPayload.value),
    key: `${transaction.txNo || 'transaction'}:${index}`,
    sourceLabel: transaction.source === 'claim' ? 'Claim' : (selectedPayload.value.parentTwRef && Number(selectedPayload.value.originalPremium) < 0 ? 'Return premium' : 'Premium'),
    paymentDirection: paymentDirection(transaction),
    reconciliationRef: reconciliationRefFor(selectedPayload.value, transaction),
    settlement: transaction.paymentScheduleSettlement || (transaction.source === 'claim' ? (transaction.settlement === 'settled' ? 'settled' : 'open') : 'not_tracked')
  })))
  const currentHeader = computed(() => {
    if (activeView.value === 'case-create' && isEditing.value) {
      return { ...headers['case-create'], kicker: 'Placement · Draft', title: draft.parentTwRef ? 'New endorsement' : 'Account', subtitle: draft.parentTwRef ? ('Endorsement to ' + draft.parentTwRef) : 'Draft — versioned update' }
    }
    if (activeView.value === 'case-detail' && selectedCase.value) {
      const payload = selectedPayload.value
      return {
        ...headers['case-detail'],
        title: selectedCase.value.twRef ? displayTwRef(selectedCase.value) : 'Draft · not assigned',
        subtitle: `${payload.originalInsured || 'Unnamed case'} · ${statusLabel(selectedCase.value.status)}`
      }
    }
    return headers[activeView.value] || headers.cases
  })
  watchEffect(() => setHeader(currentHeader.value))

  const filteredCases = computed(() => {
    const needle = filters.search.trim().toLowerCase()
    return cases.value.filter((row) => {
      if (filters.status !== 'all' && row.status !== filters.status) return false
      if (filters.year !== 'all' && String(row.effectiveDate || row.updatedAt || '').slice(0, 4) !== filters.year) return false
      if (filters.className !== 'all' && row.className !== filters.className) return false
      if (filters.reinsured !== 'all' && row.reinsured !== filters.reinsured) return false
      if (filters.aeName !== 'all' && row.aeName !== filters.aeName) return false
      if (filters.reinsurer !== 'all' && !(Array.isArray(row.reinsurers) ? row.reinsurers : []).includes(filters.reinsurer)) return false
      if (!needle) return true
      return [displayTwRef(row), row.twRef, row.manualTwRef, ...(row.previousTwRefs || []), row.originalInsured, row.originalInsuredCn, row.reinsured, row.className, row.aeName, ...(Array.isArray(row.reinsurers) ? row.reinsurers : [])]
        .some((value) => String(value || '').toLowerCase().includes(needle))
    })
  })

  function round2(value) {
    const number = Number(value)
    return Math.round(((Number.isFinite(number) ? number : 0) + Number.EPSILON) * 100) / 100
  }

  function installmentAllocationsFor(caseData) {
    if (!caseData?.installmentEnabled) return []
    const rows = Array.isArray(caseData.performanceInstallments) ? caseData.performanceInstallments : []
    const totalPremium = Number(caseData.originalPremium || 0)
    const periodAmounts = premiumPeriodAmounts(caseData)
    const allocations = rows.map((row, i) => ({
      ...row,
      premium: totalPremium === 0 ? 0 : Number(row?.premium || 0),
      ratio: totalPremium === 0 ? Number(row?.ratio || 0) / 100 : Number(row?.premium || 0) / totalPremium,
      income: periodAmounts[i]?.leg3 || 0
    }))
    return allocations
  }

  function installmentCountErrorFor(caseData) {
    if (caseData?.installmentEnabled !== true) return ''
    const rows = Array.isArray(caseData.performanceInstallments) ? caseData.performanceInstallments : []
    return rows.length < 2 ? 'Premium Installments requires at least two installments. Turn it off for a single payment.' : ''
  }

  function installmentValidationFor(caseData) {
    if (!caseData?.installmentEnabled) return { valid: true, message: '' }
    const rows = Array.isArray(caseData.performanceInstallments) ? caseData.performanceInstallments : []
    const countError = installmentCountErrorFor(caseData)
    if (countError) return { valid: false, message: countError }
    if (rows.some((row) => !/^\d{4}-\d{2}$/.test(String(row?.performanceMonth || '')))) return { valid: false, message: 'Every installment needs a performance month.' }
    if (rows.some((row) => !/^\d{4}-\d{2}-\d{2}$/.test(String(row?.paymentBaseDate || '')))) return { valid: false, message: 'Every installment needs a payment base date.' }
    const totalPremium = Number(caseData.originalPremium || 0)
    if (totalPremium === 0) {
      const sum = rows.reduce((total, row) => total + Number(row?.ratio || 0), 0)
      if (rows.some((row) => Number(row?.ratio || 0) <= 0) || Math.abs(sum - 100) > 0.0001) return { valid: false, message: 'Installment ratios must be greater than 0 and total 100%.' }
    } else {
      const invalid = rows.some((row) => row?.premium === '' || row?.premium === null || row?.premium === undefined || !Number.isFinite(Number(row.premium)))
      if (invalid) return { valid: false, message: 'Enter the Premium for every installment.' }
      if (rows.some((row) => Number(row.premium) * totalPremium < 0)) return { valid: false, message: 'Installment Premium must have the same sign as 100% Premium.' }
      const sum = rows.reduce((total, row) => total + Number(row.premium), 0)
      if (Math.abs(sum - totalPremium) > 0.01) return { valid: false, message: 'Installment Premium total must equal 100% Premium.' }
    }
    return { valid: true, message: 'Installment allocation is complete.' }
  }

  function addInstallment() {
    draft.performanceInstallments.push({ clientKey: clientKey(), id: `I${Date.now()}-${Math.random().toString(36).slice(2, 6)}`, performanceMonth: '', paymentBaseDate: '', paymentTermsDays: null, reinsurerPaymentTerms: {}, premium: null, ratio: null })
  }
  function removeInstallment(index) { draft.performanceInstallments.splice(index, 1) }
  function onInstallmentToggle(enabled) {
    if (isEndorsementDraft.value) { draft.installmentEnabled = false; draft.performanceInstallments = []; return }
    if (enabled && !draft.performanceInstallments.length) addInstallment()
  }
  function installmentRowInvalid(index, key) {
    if (!reviewAttempted.value || !draft.installmentEnabled) return false
    const row = draft.performanceInstallments[index] || {}
    if (key === 'performanceMonth') return !/^\d{4}-\d{2}$/.test(String(row.performanceMonth || ''))
    if (key === 'paymentBaseDate') return !/^\d{4}-\d{2}-\d{2}$/.test(String(row.paymentBaseDate || ''))
    if (key === 'ratio') return Number(row.ratio || 0) <= 0
    return row.premium === '' || row.premium === null || row.premium === undefined || !Number.isFinite(Number(row.premium))
  }

  function splitValidationFor(caseData) {
    if (!caseData?.splitEnabled) return { valid: true, message: '' }
    const parties = Array.isArray(caseData.splitParties) ? caseData.splitParties : []
    if (parties.length !== 2) return { valid: false, message: 'Performance Split requires exactly two people.' }
    const names = parties.map((row) => String(row?.name || '').trim().toLowerCase())
    if (names.some((name) => !name) || new Set(names).size !== 2) return { valid: false, message: 'Select two different people.' }
    const personnelIds = parties.map((row) => Number(row?.personnelId))
    if (personnelIds.some((id) => !Number.isInteger(id) || id < 1) || new Set(personnelIds).size !== 2) {
      return { valid: false, message: 'Select two different active Personnel records.' }
    }
    const percentages = parties.map((row) => Number(row?.pct))
    if (percentages.some((value) => !Number.isFinite(value) || value <= 0)) return { valid: false, message: 'Each split percentage must be greater than 0.' }
    const total = percentages.reduce((sum, value) => sum + value, 0)
    if (Math.abs(total - 100) > 0.0001) return { valid: false, message: `Split percentages must total 100% (currently ${formatAmount(total)}%).` }
    return { valid: true, message: 'Performance Split is complete.' }
  }

  function onSplitToggle(enabled) {
    if (!enabled || draft.splitParties.length === 2) return
    draft.splitParties = [
      { clientKey: clientKey(), personnelId: null, name: '', pct: null },
      { clientKey: clientKey(), personnelId: null, name: '', pct: null }
    ]
  }
  function splitPartyInvalid(index, key) {
    if (!reviewAttempted.value || !draft.splitEnabled) return false
    const row = draft.splitParties[index] || {}
    if (key === 'name') {
      const name = String(row.name || '').trim().toLowerCase()
      const personnelId = Number(row.personnelId)
      return !name || !Number.isInteger(personnelId) || personnelId < 1
        || draft.splitParties.some((item, itemIndex) => itemIndex !== index
          && (Number(item?.personnelId) === personnelId || String(item?.name || '').trim().toLowerCase() === name))
    }
    const pct = Number(row.pct)
    return !Number.isFinite(pct) || pct <= 0
  }

  function lossRecordSummaryFor(caseData) {
    const rows = Array.isArray(caseData?.lossRecord) ? caseData.lossRecord : []
    const years = Number(caseData?.lossRecordYears || 0)
    const subject = rows.length === 0 ? 'Loss Clean' : `${rows.length} ${rows.length === 1 ? 'loss' : 'losses'}`
    if (filled(caseData?.lossRecordYears) && years === 0 && rows.length === 0
      && caseData?.newOrRenew === 'New' && !filled(caseData?.renewedFromTwRef)) return 'Loss Clean since operation.'
    if (!Number.isInteger(years) || years <= 0) return `${subject} — history period not specified`
    return `${subject} in the past ${years} ${years === 1 ? 'year' : 'years'}`
  }
  function addLossRecord() {
    if (Number(draft.lossRecordYears) === 0 && filled(draft.lossRecordYears)) return
    draft.lossRecord.push({ clientKey: clientKey(), date: '', cause: '', lossPaid: null })
  }
  function removeLossRecord(index) { draft.lossRecord.splice(index, 1) }
  function lossRowInvalid(index, key) {
    if (!reviewAttempted.value) return false
    const row = draft.lossRecord[index] || {}
    return !filled(row[key])
  }

  function resetDraft() {
    autoPolicyTo = ''
    const fresh = emptyDraft()
    Object.keys(draft).forEach((key) => delete draft[key])
    Object.assign(draft, fresh)
    sumInsuredFacilityMode = null
    openSections.value = [...OPEN_SECTIONS]
    saveMessage.value = ''
    reviewAttempted.value = false
    lossSaveAttempted.value = false
    manualRefSaveAttempted.value = false
    reviewDialogVisible.value = false
    editingCaseUid.value = ''
    editingRowVersion.value = null
    editingOriginalStatus.value = 'draft'
    endorsementFieldsUnlocked.value = false
    Object.assign(caseClauseDraft, { code: '', title: '' })
  }

  function startNewCase() {
    resetDraft()
    draft.currency = 'TWD'
    draft.paymentTermsDays = 90
    draft.cedantTermsBasis = 'case'
    draft.taxPct = 1
    draft.ae = auth.principal?.name || ''
    draft.reinsurers.forEach((row) => { row.taxPct = 1 })
    activeView.value = 'case-create'
    if (!mdmRecords.value.length) loadMasterData()
    loadPersonnelOptions()
    window.scrollTo({ top: 0 })
  }
  function onPolicyFromChange(value) {
    if (isEndorsementDraft.value || (isEditing.value && editingOriginalStatus.value !== 'draft')
      || (draft.policyTo && draft.policyTo !== autoPolicyTo)) return
    if (value && !/^\d{4}-\d{2}-\d{2}$/.test(value)) return
    if (!value) {
      draft.policyTo = ''
      autoPolicyTo = ''
      return
    }
    const [year, month, day] = value.split('-').map(Number)
    const nextYear = year + 1
    const lastDay = new Date(Date.UTC(nextYear, month, 0)).getUTCDate()
    autoPolicyTo = `${nextYear}-${String(month).padStart(2, '0')}-${String(Math.min(day, lastDay)).padStart(2, '0')}`
    draft.policyTo = autoPolicyTo
  }
  watch(() => draft.policyFrom, (value) => {
    if (activeView.value === 'case-create') onPolicyFromChange(value)
  })
  function cancelNewCase() { resetDraft(); activeView.value = 'cases'; window.scrollTo({ top: 0 }) }
  function backToCases() { selectedCase.value = null; caseDetailTab.value = 'overview'; activeView.value = 'cases'; window.scrollTo({ top: 0 }) }

  function reinsurerKey(value) { return String(value || '').trim().toLowerCase().replace(/\s+/g, ' ') }
  function displayReinsurerName(value) {
    return selectedReinsurers.value.find((row) => row.key === reinsurerKey(value))?.label || value || '—'
  }
  function documentKindLabel(kind) {
    return { offer: 'Offer Slip', signed: 'Reinsurer Signed Slip', confirmation: 'Reinsurer Confirmation E-mail' }[kind] || kind
  }
  function resetDocumentForm() {
    documentForm.kind = 'offer'
    documentForm.reinsurers = []
    documentForm.file = null
    documentFileList.value = []
  }
  function onDocumentKindChange() { documentForm.reinsurers = [] }
  function onDocumentFileChange(uploadFile) { documentForm.file = uploadFile?.raw || null; documentFileList.value = uploadFile ? [uploadFile] : [] }
  function onDocumentFileRemove() { documentForm.file = null; documentFileList.value = [] }

  async function documentRequest(path, options = {}) {
    const response = await apiFetch(path, options)
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.message || body.error || `Document request failed (HTTP ${response.status}).`)
    }
    return response
  }

  // 同 Alpha downloadGeneratedDocument；產生程式與 VM 的 API 串接在 ../alpha/documents
  async function downloadGeneratedDocument(kind, format) {
    if (!selectedCase.value || !can('documents.read')) return
    if (format !== 'docx') return ElMessage.warning('Download Word (.docx) and export it to PDF in Word.')
    if (!isTreatyDocumentCase.value) {
      if (kind === 'cover' && !selectedCase.value.twRef) {
        return ElMessage.warning('Cover Note is available after Announce assigns a TW Reference.')
      }
      if (kind === 'debit' && selectedCase.value.status === 'draft') {
        return ElMessage.warning('Debit Note is available after the case is Announced.')
      }
      if ((kind === 'cover' || kind === 'debit') && !String(selectedPayload.value.reinsured || '').trim()) {
        return ElMessage.warning('Complete Reinsured in the case before generating a Cover Note or Debit Note.')
      }
      if ((kind === 'cover' || kind === 'debit') && !String(selectedPayload.value.originalInsured || '').trim()) {
        return ElMessage.warning('Complete Original Insured in the case before generating a Cover Note or Debit Note.')
      }
      if ((kind === 'cover' || kind === 'debit') && !String(selectedPayload.value.type || '').trim()) {
        return ElMessage.warning('Complete Type in the case before generating a Cover Note or Debit Note.')
      }
      if ((kind === 'cover' || kind === 'debit') && (!String(selectedPayload.value.policyFrom || '').trim() || !String(selectedPayload.value.policyTo || '').trim())) {
        return ElMessage.warning('Complete the policy start and end dates in the case before generating a Cover Note or Debit Note.')
      }
      if (!String(selectedPayload.value.ae || '').trim()) {
        return ElMessage.warning('Select an Account Executive in the case before generating a document.')
      }
      if (!String(generatedDocumentCase.value.aeEmail || '').trim()) {
        return ElMessage.warning('Complete the Account Executive Email in the case or Personnel before generating a document.')
      }
      if (kind === 'cover' && cglTypeIssues(selectedPayload.value).length) return ElMessage.warning(cglTypeIssues(selectedPayload.value)[0].label)
      if (kind === 'cover' && cglRiskDetailsIssues(selectedPayload.value).length) return ElMessage.warning('Complete Coverages: ' + cglRiskDetailsIssues(selectedPayload.value).map(issue => issue.label).join('; '))
      if (kind === 'cover' && cglInformationIssues(selectedPayload.value).length) return ElMessage.warning('Complete Information: ' + cglInformationIssues(selectedPayload.value).map(issue => issue.label).join('; '))
      if (kind === 'cover' && !String(selectedPayload.value.interest || '').trim()) {
        return ElMessage.warning('Complete Interest in the case before generating a Cover Note.')
      }
      if (kind === 'cover' && !String(selectedPayload.value.limitOfLiability ?? '').trim()) {
        return ElMessage.warning(`Complete ${liabilityLimitLabel(selectedPayload.value)} in the case before generating a Cover Note.`)
      }
      if (kind === 'cover' && String(selectedPayload.value.reinsuranceStructure || '').trim() === 'XOL' && !String(selectedPayload.value.underlyingLimits || '').trim()) {
        return ElMessage.warning('Complete Underlying Limits in the case before generating a Cover Note.')
      }
      if (kind === 'cover' && ['QS', 'XOL'].includes(String(selectedPayload.value.reinsuranceStructure || '').trim()) && !String(selectedPayload.value.deductibles || '').trim()) {
        return ElMessage.warning('Complete Deductibles in the case before generating a Cover Note.')
      }
      if (kind === 'cover' && ['QS', 'XOL'].includes(String(selectedPayload.value.reinsuranceStructure || '').trim()) && !String(selectedPayload.value.reinsuredRetention || '').trim()) {
        return ElMessage.warning('Complete Reinsured’s Retention in the case before generating a Cover Note.')
      }
      if (kind === 'cover' && ['QS', 'XOL'].includes(String(selectedPayload.value.reinsuranceStructure || '').trim()) && (!Array.isArray(selectedPayload.value.situations) || !selectedPayload.value.situations.length || selectedPayload.value.situations.some(row => !String(row?.address || '').trim()))) {
        return ElMessage.warning(isStandardCgl(selectedPayload.value) ? 'Complete Principal Address in the case before generating a Cover Note.' : 'Complete Risk Address for every Situation in the case before generating a Cover Note.')
      }
      if (kind === 'cover' && ['QS', 'XOL'].includes(String(selectedPayload.value.reinsuranceStructure || '').trim()) && (!Array.isArray(selectedPayload.value.situations) || !selectedPayload.value.situations.length || selectedPayload.value.situations.some(row => !/^[0-9]{3,6}$/.test(String(row?.postcode ?? '').trim())))) {
        return ElMessage.warning(isStandardCgl(selectedPayload.value) ? 'Complete a 3–6 digit Postcode for every Principal Address in the case before generating a Cover Note.' : 'Complete a 3–6 digit Postcode for every Situation in the case before generating a Cover Note.')
      }
      if (['cover', 'debit'].includes(kind) && ['QS', 'XOL'].includes(String(selectedPayload.value.reinsuranceStructure || '').trim()) && !String(selectedPayload.value.originalPremium ?? '').trim()) {
        return ElMessage.warning('Complete 100% Premium in the case before generating a Cover Note or Debit Note.')
      }
      if (['cover', 'debit'].includes(kind) && ['QS', 'XOL'].includes(String(selectedPayload.value.reinsuranceStructure || '').trim()) && (!Array.isArray(selectedPayload.value.reinsurers) || !selectedPayload.value.reinsurers.length || selectedPayload.value.reinsurers.some(row => !String(row?.sharePct ?? '').trim()))) {
        return ElMessage.warning('Add at least one Reinsurer and complete Order hereon for every Reinsurer in the case before generating a Cover Note or Debit Note.')
      }
      if (kind === 'cover' && !isStandardCgl(selectedPayload.value) && ['QS', 'XOL'].includes(String(selectedPayload.value.reinsuranceStructure || '').trim()) && (!Array.isArray(selectedPayload.value.sumInsured) || !selectedPayload.value.sumInsured.length || selectedPayload.value.sumInsured.some(row => !String(row?.category ?? '').trim()))) {
        return ElMessage.warning('Add at least one Sum Insured entry and complete Interest insured for every entry before generating a Cover Note.')
      }
      if (kind === 'cover' && !isStandardCgl(selectedPayload.value) && ['QS', 'XOL'].includes(String(selectedPayload.value.reinsuranceStructure || '').trim()) && (!Array.isArray(selectedPayload.value.sumInsured) || !selectedPayload.value.sumInsured.length || selectedPayload.value.sumInsured.some(row => !Number.isFinite(Number(row?.amount)) || Number(row?.amount) <= 0))) {
        return ElMessage.warning('Enter an Amount greater than 0 for every Sum Insured entry before generating a Cover Note.')
      }
      if (kind === 'cover' && !isStandardCgl(selectedPayload.value) && ['QS', 'XOL'].includes(String(selectedPayload.value.reinsuranceStructure || '').trim())) {
        const issues = sumInsuredPlacementIssues(selectedPayload.value)
        if (issues.some(issue => issue.kind === 'location')) return ElMessage.warning('Assign every Sum Insured entry to a valid Location and add at least one entry for every Location before generating a Cover Note.')
        if (issues.some(issue => issue.kind === 'duplicate')) return ElMessage.warning('Use unique Interest insured names within each Location or the Facility items before generating a Cover Note.')
      }
      if (kind === 'cover' && ['QS', 'XOL'].includes(String(selectedPayload.value.reinsuranceStructure || '').trim()) && !String(selectedPayload.value.lossAdvisedDate ?? '').trim()) {
        return ElMessage.warning('Complete the Loss Record advised date in the case before generating a Cover Note.')
      }
      if (kind === 'cover' && ['QS', 'XOL'].includes(String(selectedPayload.value.reinsuranceStructure || '').trim()) && !String(selectedPayload.value.lossRecordYears ?? '').trim()) {
        return ElMessage.warning('Complete Past year(s) in the Loss Record section of the case before generating a Cover Note.')
      }
      if (kind === 'cover' && ['QS', 'XOL'].includes(String(selectedPayload.value.reinsuranceStructure || '').trim()) && Array.isArray(selectedPayload.value.lossRecord) && selectedPayload.value.lossRecord.some(row => !String(row?.date ?? '').trim())) {
        return ElMessage.warning('Complete Date of Loss for every Loss Record entry in the case before generating a Cover Note.')
      }
      if (kind === 'cover' && ['QS', 'XOL'].includes(String(selectedPayload.value.reinsuranceStructure || '').trim()) && Array.isArray(selectedPayload.value.lossRecord) && selectedPayload.value.lossRecord.some(row => !String(row?.cause ?? '').trim())) {
        return ElMessage.warning('Complete Cause for every Loss Record entry in the case before generating a Cover Note.')
      }
      if (kind === 'cover' && ['QS', 'XOL'].includes(String(selectedPayload.value.reinsuranceStructure || '').trim()) && Array.isArray(selectedPayload.value.lossRecord) && selectedPayload.value.lossRecord.some(row => !String(row?.lossPaid ?? '').trim())) {
        return ElMessage.warning('Complete Loss Paid for every Loss Record entry in the case before generating a Cover Note.')
      }
      if (kind === 'cover' && ['QS', 'XOL'].includes(String(selectedPayload.value.reinsuranceStructure || '').trim()) && Array.isArray(selectedPayload.value.reinsurers) && selectedPayload.value.reinsurers.some(row => !String(row?.name ?? '').trim())) {
        return ElMessage.warning('Complete the Reinsurer name for every Schedule of Security entry in the case before generating a Cover Note.')
      }
      if (kind === 'debit' && missingDebitPaymentTerms(selectedPayload.value)) {
        return ElMessage.warning('Complete valid Payment Terms Days (an integer of at least 15) for every Reinsurer, using the Case default when needed, before generating a Debit Note.')
      }
      if (kind === 'debit' && missingDebitInstallmentBaseDates(selectedPayload.value)) {
        return ElMessage.warning('Add at least one installment and complete a valid Payment Base Date for every installment before generating a Debit Note.')
      }
      if (kind === 'debit' && missingDebitInstallmentPaymentTerms(selectedPayload.value)) {
        return ElMessage.warning('Complete valid Payment Terms Days (an integer of at least 15) for every Reinsurer in every installment before generating a Debit Note.')
      }
      if (kind === 'debit' && missingDebitInstallmentAllocation(selectedPayload.value)) {
        return ElMessage.warning('Complete Premium or Ratio for every installment before generating a Debit Note.')
      }
      if (kind === 'debit' && invalidDebitInstallmentAllocation(selectedPayload.value)) {
        return ElMessage.warning('Use a Premium or Ratio greater than 0 for every installment before generating a Debit Note.')
      }
      if (kind === 'debit' && unsupportedDebitBankCurrency(selectedPayload.value)) {
        return ElMessage.warning('Debit Note generation is available only for USD and TWD. The receiving bank account for other currencies is pending confirmation.')
      }
    }
    if (kind === 'cover' && !isTreatyDocumentCase.value && ['QS', 'XOL'].includes(String(selectedPayload.value.reinsuranceStructure || '').trim())) {
      const warning = sumInsuredLimitWarning(selectedPayload.value)
      if (warning) ElMessage.warning(warning.message)
    }
    const key = `${kind}-${format}`
    documentGenerating.value = key
    try {
      await loadMasterData({ required: true })
      const documentCase = generatedDocumentCase.value
      await generateDocx(kind, documentCase)
      ElMessage.success(`${kind === 'cover' ? 'Cover Note' : kind === 'endorsement' ? 'Endorsement' : 'Debit Note'} ${format.toUpperCase()} saved.`)
    } catch (err) {
      ElMessage.error(err instanceof Error ? err.message : String(err))
    } finally {
      documentGenerating.value = ''
    }
  }

  // VM：案件的提醒紀錄（Reminders 分頁；Alpha 沒有這個畫面）
  const caseReminders = ref(null)
  const remindersLoading = ref(false)
  const reminderPreview = ref(null)
  const reminderPreviewVisible = ref(false)
  const REMINDER_STATUS = { sent: ['Sent', 'success'], simulated: ['Simulated (test address)', 'info'], suppressed: ['Suppressed (not sent)', 'warning'], failed: ['Failed', 'danger'], pending: ['Pending', 'info'] }
  const reminderStatusLabel = (status) => (REMINDER_STATUS[status] || [status || '—'])[0]
  const reminderStatusType = (status) => (REMINDER_STATUS[status] || [null, 'info'])[1]
  const paymentReminderLabel = (kind) => ({ seven_days_before: '7 天後到期', due_today: '今日到期', weekly_overdue: '逾期每週提醒' }[kind] || kind)
  function openReminderPreview(row) {
    reminderPreview.value = row
    reminderPreviewVisible.value = true
  }
  async function loadCaseReminders() {
    const caseUid = selectedCase.value?.caseUid
    if (!caseUid) return
    if (caseReminders.value?.caseUid !== caseUid) caseReminders.value = null   // 換了案件就不顯示上一件的紀錄
    remindersLoading.value = true
    try {
      const response = await apiFetch(`/api/case-reminders?caseUid=${encodeURIComponent(caseUid)}`, { headers: { Accept: 'application/json' } })
      const body = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(body.message || body.error || `Reminder request failed (HTTP ${response.status}).`)
      if (selectedCase.value?.caseUid === caseUid) caseReminders.value = body
    } catch (err) {
      ElMessage.error(err instanceof Error ? err.message : String(err))
    } finally {
      remindersLoading.value = false
    }
  }

  async function loadCaseDocuments() {
    if (!selectedCase.value?.caseUid || !can('documents.read')) return
    documentsLoading.value = true
    try {
      const response = await documentRequest('/api/case-documents?caseUid=' + encodeURIComponent(selectedCase.value.caseUid), { headers: { Accept: 'application/json' } })
      const body = await response.json()
      caseDocuments.value = Array.isArray(body.files) ? body.files : []
      documentCoverage.value = body.coverage || documentCoverage.value
      signedSlipReminder.value = body.signedSlipReminder || signedSlipReminder.value
    } catch (err) {
      ElMessage.error(err instanceof Error ? err.message : String(err))
    } finally { documentsLoading.value = false }
  }

  async function loadCaseWorkflow() {
    // VM：流程狀態需要 cases.read.all（Case Viewer 沒有）；Alpha 會直接呼叫而跳出權限錯誤，VM 不呼叫
    if (!selectedCase.value?.caseUid || !can('cases.read.all')) return
    workflowLoading.value = true
    try {
      const response = await apiFetch('/api/case-workflow?caseUid=' + encodeURIComponent(selectedCase.value.caseUid), { headers: { Accept: 'application/json' } })
      const body = await response.json()
      if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
      caseWorkflow.value = body.workflow
    } catch (err) {
      ElMessage.error(err instanceof Error ? err.message : String(err))
    } finally { workflowLoading.value = false }
  }

  async function runWorkflowAction(action) {
    if (!selectedCase.value?.caseUid || workflowSaving.value) return
    const label = action === 'create_endorsement' ? 'create a new endorsement Draft' : 'create a renewal Draft'
    let manualTwRef = ''
    try {
      if (requiresManualTwRef(selectedPayload.value)) {
        const input = await ElMessageBox.prompt(
          `Enter the new AUW TW Ref. to ${label}.`, 'TW Ref. (for AUW)',
          { confirmButtonText: 'Create draft', cancelButtonText: 'Cancel', inputPlaceholder: 'New AUW TW Ref.',
            inputValidator: (value) => {
              const reference = String(value || '').trim()
              if (!reference) return 'TW Ref. (for AUW) is required.'
              if (reference.length > 160) return 'TW Ref. (for AUW) must not exceed 160 characters.'
              if (/[\x00-\x1f\x7f]/.test(reference)) return 'Enter a single-line TW Ref.'
              return true
            } }
        )
        manualTwRef = input.value.trim()
      } else {
        await ElMessageBox.confirm(`This will ${label} from the current case.`, 'Continue workflow', { confirmButtonText: 'Create draft', cancelButtonText: 'Cancel', type: 'warning' })
      }
    } catch { return }
    workflowSaving.value = true
    try {
      const response = await apiFetch('/api/case-workflow', {
        method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ action, caseUid: selectedCase.value.caseUid, rowVersion: selectedCase.value.rowVersion, ...(manualTwRef ? { manualTwRef } : {}) })
      })
      const body = await response.json()
      if (!response.ok) {
        if (body.latestCaseUid) await startViewCase({ caseUid: body.latestCaseUid })
        const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status))
        requestErr.status = response.status
        throw requestErr
      }
      await loadData()
      await startEditCase(body.case)
      ElMessage.success(action === 'create_endorsement' ? 'Endorsement Draft created' : 'Renewal Draft created')
    } catch (err) {
      reportWriteError(err, () => loadCaseWorkflow())
    } finally { workflowSaving.value = false }
  }

  function createEndorsement() { return runWorkflowAction('create_endorsement') }
  function createRenewal() { return runWorkflowAction('create_renewal') }
  function viewWorkflowCase(row) { if (row?.caseUid) startViewCase(row) }

  function openAccountingNotification() {
    accountingForm.accountingPersonnelId = null
    accountingForm.note = ''
    accountingDialogVisible.value = true
  }

  async function saveAccountingNotification() {
    if (!accountingForm.accountingPersonnelId || !selectedCase.value?.caseUid) {
      return ElMessage.warning('Select the Accounting recipient.')
    }
    workflowSaving.value = true
    try {
      await jsonOrThrow(await apiFetch('/api/case-workflow', {
        method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          action: 'notify_accounting',
          caseUid: selectedCase.value.caseUid,
          rowVersion: selectedCase.value.rowVersion,
          accountingPersonnelId: accountingForm.accountingPersonnelId,
          note: accountingForm.note
        })
      }))
      accountingDialogVisible.value = false
      await startViewCase({ caseUid: selectedCase.value.caseUid })
      ElMessage.success('Accounting notification recorded')
    } catch (err) {
      reportWriteError(err, () => loadCaseWorkflow())
    } finally { workflowSaving.value = false }
  }

  async function reverseSelectedCase() {
    if (!selectedCase.value?.caseUid || selectedCase.value.status !== 'closed') return
    try {
      await ElMessageBox.confirm(
        'Existing premium transactions will remain in the SoA and be marked Reversed. After correction and a future Production close, offset entries and a new transaction cycle will be appended.',
        'Reverse confirmed case',
        { confirmButtonText: 'Reverse case', cancelButtonText: 'Cancel', type: 'warning' }
      )
    } catch { return }
    workflowSaving.value = true
    try {
      const body = await jsonOrThrow(await apiFetch('/api/case-workflow', {
        method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ action: 'reverse_case', caseUid: selectedCase.value.caseUid, rowVersion: selectedCase.value.rowVersion })
      }))
      await loadData()
      await startViewCase({ caseUid: body.case.caseUid })
      ElMessage.success('Case reversed — correct the figures and save to move it back to Announced')
    } catch (err) {
      reportWriteError(err, () => loadCaseWorkflow())
    } finally { workflowSaving.value = false }
  }

  async function refreshSelectedCase() {
    if (!selectedCase.value?.caseUid) return
    const response = await apiFetch('/api/cases?caseUid=' + encodeURIComponent(selectedCase.value.caseUid), { headers: { Accept: 'application/json' } })
    const body = await response.json()
    if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
    selectedCase.value = body.case
  }

  // ---- 理賠（Alpha 的 loadClaims／submitClaimAction／createClaim／updateClaimReserve／openClaimPayment／recordClaimPayment／claimTotalPaid）----
  const claimsLoading = ref(false)
  const claimsSaving = ref(false)
  const claimsState = ref({ rootCaseUid: '', rootTwRef: '', rootStatus: '', rootRowVersion: null, currency: '', claims: [], splitSource: { reinsurers: [] }, actions: { canWrite: false } })
  const claimForm = reactive({ lossNo: '', dateOfLoss: '', outstandingReserve: null, causeOfLoss: '' })
  const paymentDialogVisible = ref(false)
  const activeClaimId = ref(null)
  const paymentForm = reactive({ date: '', amount: null, note: '' })

  async function loadClaims() {
    if (!selectedCase.value?.caseUid) return
    claimsLoading.value = true
    try {
      const response = await apiFetch('/api/claims?caseUid=' + encodeURIComponent(selectedCase.value.caseUid), { headers: { Accept: 'application/json' } })
      const body = await response.json()
      if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
      claimsState.value = body.claimsState
    } catch (err) {
      ElMessage.error(err instanceof Error ? err.message : String(err))
    } finally { claimsLoading.value = false }
  }

  async function submitClaimAction(action, extra = {}) {
    claimsSaving.value = true
    try {
      const response = await apiFetch('/api/claims', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          action,
          caseUid: selectedCase.value.caseUid,
          rowVersion: claimsState.value.rootRowVersion,
          ...extra
        })
      })
      const body = await response.json()
      if (!response.ok) {
        const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status))
        requestErr.status = response.status
        throw requestErr
      }
      claimsState.value = body.claimsState
      await refreshSelectedCase()
      return true
    } catch (err) {
      reportWriteError(err, () => loadClaims())
      return false
    } finally { claimsSaving.value = false }
  }

  async function createClaim() {
    const saved = await submitClaimAction('create_claim', { claim: { ...claimForm } })
    if (!saved) return
    Object.assign(claimForm, { lossNo: '', dateOfLoss: '', outstandingReserve: null, causeOfLoss: '' })
    ElMessage.success('Claim added')
  }

  async function updateClaimReserve(claim) {
    const saved = await submitClaimAction('update_reserve', { claimId: claim.id, outstandingReserve: claim.outstandingReserve })
    if (saved) ElMessage.success('Outstanding reserve updated')
  }

  function openClaimPayment(claim, payment = null) {
    activeClaimId.value = claim.id
    Object.assign(paymentForm, { date: payment?.date || '', amount: payment?.amount ?? null, note: payment?.note || '', paymentId: payment?.id ?? null, reason: '' })
    paymentDialogVisible.value = true
  }

  async function recordClaimPayment() {
    // 理賠付款可以是負數（追償、自負額沖抵等），只擋 0 與無效輸入（同 Alpha）
    if (!Number(paymentForm.amount)) return ElMessage.error('Enter a non-zero payment amount.')
    if (paymentForm.paymentId != null && !paymentForm.reason?.trim()) return ElMessage.error('Enter the correction reason.')
    const saved = await submitClaimAction(paymentForm.paymentId == null ? 'record_payment' : 'correct_payment', { claimId: activeClaimId.value, paymentId: paymentForm.paymentId, reason: paymentForm.reason, payment: { ...paymentForm } })
    if (!saved) return
    paymentDialogVisible.value = false
    ElMessage.success('Claim obligations saved; Accounting records receipts and payments separately')
  }

  function claimTotalPaid(claim) {
    return (Array.isArray(claim?.payments) ? claim.payments : []).reduce((sum, payment) => sum + Number(payment?.amount || 0), 0)
  }

  function onCaseDetailTabChange(name) {
    if (name === 'overview' || name === 'documents') loadCaseDocuments()
    if (name === 'reminders') loadCaseReminders()
    if (name === 'claims') loadClaims()
    if (name === 'endorsements') loadCaseWorkflow()
  }

  function fileAsBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result || '').split(',')[1] || '')
      reader.onerror = () => reject(new Error('The selected file could not be read.'))
      reader.readAsDataURL(file)
    })
  }

  async function uploadCaseDocument() {
    const file = documentForm.file
    if (!file) return ElMessage.error('Select a document to upload.')
    if (!file.size || file.size > MAX_DOCUMENT_BYTES) return ElMessage.error('Each document must be nonempty and no larger than 10 MB.')
    if (documentForm.kind !== 'offer' && !documentForm.reinsurers.length) return ElMessage.error('Select the reinsurer(s) covered by this evidence.')
    documentsSaving.value = true
    try {
      const base64 = await fileAsBase64(file)
      const response = await documentRequest('/api/case-documents', {
        method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ caseUid: selectedCase.value.caseUid, kind: documentForm.kind, reinsurers: documentForm.reinsurers, filename: file.name, base64 })
      })
      const body = await response.json()
      caseDocuments.value.push(body.file)
      documentCoverage.value = body.coverage
      signedSlipReminder.value = body.signedSlipReminder || signedSlipReminder.value
      resetDocumentForm()
      ElMessage.success('Placement document uploaded and selected.')
    } catch (err) {
      ElMessage.error(err instanceof Error ? err.message : String(err))
    } finally { documentsSaving.value = false }
  }

  async function toggleDocumentSelection(row, selected) {
    const previous = !selected
    documentsSaving.value = true
    try {
      const response = await documentRequest('/api/case-documents', {
        method: 'PUT', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ caseUid: selectedCase.value.caseUid, fileId: row.id, selected })
      })
      const body = await response.json()
      documentCoverage.value = body.coverage
    } catch (err) {
      row.is_selected = previous
      ElMessage.error(err instanceof Error ? err.message : String(err))
    } finally { documentsSaving.value = false }
  }

  async function downloadCaseDocument(row) {
    try {
      const response = await documentRequest('/api/case-documents?caseUid=' + encodeURIComponent(selectedCase.value.caseUid) + '&fileId=' + encodeURIComponent(row.id))
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url; anchor.download = row.filename; document.body.appendChild(anchor); anchor.click(); anchor.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (err) { ElMessage.error(err instanceof Error ? err.message : String(err)) }
  }

  async function deleteCaseDocument(row) {
    try {
      await ElMessageBox.confirm(`Delete “${row.filename}” permanently?`, 'Delete placement document', { type: 'warning', confirmButtonText: 'Delete', cancelButtonText: 'Cancel' })
    } catch (_) { return }
    documentsSaving.value = true
    try {
      const response = await documentRequest('/api/case-documents?caseUid=' + encodeURIComponent(selectedCase.value.caseUid) + '&fileId=' + encodeURIComponent(row.id), { method: 'DELETE', headers: { Accept: 'application/json' } })
      const body = await response.json()
      caseDocuments.value = caseDocuments.value.filter((file) => file.id !== row.id)
      documentCoverage.value = body.coverage
      signedSlipReminder.value = body.signedSlipReminder || signedSlipReminder.value
      ElMessage.success('Placement document deleted.')
    } catch (err) { ElMessage.error(err instanceof Error ? err.message : String(err)) }
    finally { documentsSaving.value = false }
  }

  function openAnnounceReview() {
    if (selectedCase.value?.status !== 'draft') return
    if (selectedAnnounceIssues.value.length) return ElMessage.error(`Complete ${selectedAnnounceIssues.value.length} required case fields before Announce.`)
    if (!documentCoverage.value.ready) return ElMessage.error(documentReadinessText.value)
    announceConfirmed.value = false
    announceDialogVisible.value = true
  }

  async function announceSelectedCase() {
    if (!announceConfirmed.value || !selectedCase.value?.caseUid) return
    announcing.value = true
    try {
      const body = await jsonOrThrow(await apiFetch('/api/case-announce', {
        method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          caseUid: selectedCase.value.caseUid,
          rowVersion: selectedCase.value.rowVersion,
          confirmed: true,
          documentIds: documentCoverage.value.selected || []
        })
      }))
      selectedCase.value = {
        ...selectedCase.value,
        twRef: body.case.twRef,
        status: body.case.status,
        rowVersion: Number(body.case.rowVersion),
        announcedAt: body.case.announcedAt
      }
      announceDialogVisible.value = false
      announceConfirmed.value = false
      await loadData()
      ElMessage.success(`Case Announced · ${displayTwRef(selectedCase.value)}`)
      for (const warning of body.warnings || []) ElMessage.warning({ message: warning.message, duration: 8000, showClose: true })
      if (body.productionDeferrals?.length) {
        const moves = [...new Set(body.productionDeferrals.map((row) => `${row.fromMonth} → ${row.toMonth}`))]
        ElMessage.warning({ message: `Production automatically deferred because the original month is closed: ${moves.join(', ')}`, duration: 8000, showClose: true })
      }
    } catch (err) {
      reportWriteError(err, () => refreshSelectedCase())
      await loadCaseDocuments()
    } finally { announcing.value = false }
  }
  function addSituation() { draft.situations.push({ clientKey: clientKey(), address: '', postcode: '' }) }
  async function removeSituation(index) {
    if (draft.situations.length <= 1 || !draft.situations[index]) return
    const situation = draft.situations[index]
    const linked = allFacilityReinsurers.value ? 0 : draft.sumInsured.filter(row => sumLocationIndex(row, draft.situations.length) === index).length
    try {
      await ElMessageBox.confirm(`Delete ${isCglInformation.value ? 'Principal Address' : 'Location'} ${index + 1}${situation.address ? ' — ' + situation.address : ''}?${linked ? ` Its ${linked} Sum Insured item(s) will also be deleted.` : ''}`, isCglInformation.value ? 'Delete Principal Address' : 'Delete Location', { type: 'warning', confirmButtonText: 'Delete', cancelButtonText: 'Cancel' })
    } catch { return }
    if (draft.situations[index] !== situation) return
    if (!allFacilityReinsurers.value) {
      const count = draft.situations.length
      draft.sumInsured = draft.sumInsured.filter(row => sumLocationIndex(row, count) !== index).map(row => {
        const location = sumLocationIndex(row, count)
        return { ...row, locationIndex: location === null ? null : location > index ? location - 1 : location }
      })
    }
    draft.situations.splice(index, 1)
    // 2026-10-14：刪除 Location 不可讓 Sum Insured 變成零筆；留一筆空白項目給第 1 個 Location 填寫
    if (!draft.sumInsured.length) {
      draft.sumInsured.push({ clientKey: clientKey(), category: '', amount: null, locationIndex: allFacilityReinsurers.value ? null : 0 })
    }
  }
  function addReinsurer() { draft.reinsurers.push({ clientKey: clientKey(), name: '', sharePct: null, premium: null, riCommPct: null, taxPct: 1, paymentTermsDays: null, foreignBroker: '', settlementRef: '' }) }
  function removeReinsurer(index) { if (draft.reinsurers.length > 1) { draft.reinsurers.splice(index, 1); syncCaseClauses(); syncSumInsuredMode() } }
  function addSumInsured(locationIndex = 0) { draft.sumInsured.push({ clientKey: clientKey(), category: '', amount: null, locationIndex: allFacilityReinsurers.value ? null : locationIndex }) }
  function removeSumInsured(index) { if (draft.sumInsured.length > 1) draft.sumInsured.splice(index, 1) }

  function masterOptions(type, currentValue = '') {
    const options = mdmRecords.value
      .filter((row) => row.entityType === type && row.isActive)
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name, 'en'))
    const current = String(currentValue || '').trim()
    if (current && !options.some((row) => row.name === current)) {
      const isCreator = type === 'ae' && !isEditing.value && current === auth.principal?.name
      options.push({ id: `historical-${type}-${current}`, entityType: type, code: '', name: current, isActive: isCreator, historical: !isCreator })
    }
    return options
  }

  function splitPersonOptions(row) {
    const options = personnelRecords.value
      .filter((person) => person.isActive && person.isSplitEligible)
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
    const currentId = Number(row?.personnelId)
    const currentName = String(row?.name || '').trim()
    if (currentName && !options.some((person) => Number(person.id) === currentId || person.name === currentName)) {
      options.push({
        id: Number.isInteger(currentId) && currentId > 0 ? currentId : `historical-${currentName}`,
        name: currentName,
        department: '',
        historical: true
      })
    }
    return options
  }

  function onSplitPersonSelected(row) {
    const person = personnelRecords.value.find((item) => item.isActive && item.isSplitEligible && item.name === row.name)
    if (person) row.personnelId = Number(person.id)
    else if (!row.name) row.personnelId = null
  }

  function onClassSelected(name) {
    const record = mdmRecords.value.find((row) => row.entityType === 'class' && row.name === name)
    if (record) draft.classCode = record.code || ''
    else if (!name) draft.classCode = ''
    syncCaseClauses()
  }

  function syncCaseClauses() {
    const details = UNIVERSAL_CLAUSES.map((row) => ({ ...row }))
    // VM 才有（2026-09-29 決定）：Class 自己的 Fixed Clause，以及再保人條款的適用 Class（沒有 classIds = All classes）
    const classRecord = mdmRecords.value.find((row) => row.entityType === 'class' && row.name === draft.classOfBusiness)
    const classId = classRecord ? Number(classRecord.id) : null
    const appliesToCaseClass = (row) => !Array.isArray(row?.classIds) || (classId !== null && row.classIds.map(Number).includes(classId))
    normalizeClauseList(classRecord?.payload?.fixedClauses).forEach((row) => details.push(row))
    draft.reinsurers.forEach((line) => {
      const master = mdmRecords.value.find((row) => row.entityType === 'reinsurer' && row.name === line.name)
      const fixed = Array.isArray(master?.payload?.fixedClauses) ? master.payload.fixedClauses : []
      normalizeClauseList(fixed.filter(appliesToCaseClass)).forEach((row) => details.push(row))
    })
    normalizeClauseList(draft.manualClauses).forEach((row) => details.push(row))
    const unique = resolveClauseTitles(details, mdmRecords.value, draft).sort(compareClauses)
    draft.clauseDetails = unique
    draft.clauses = unique.map((row) => row.code)
    const manualCodes = new Set(normalizeClauseList(draft.manualClauses).map((row) => row.code))
    draft.autoClauses = unique.filter((row) => !UNIVERSAL_CLAUSES.some((base) => base.code === row.code) && !manualCodes.has(row.code)).map((row) => row.code)
  }
  function applyAuwReinsurerRules() {
    draft.reinsurers.forEach((row) => {
      if (isAuwReinsurer(row.name)) {
        row.taxPct = 0
        row.paymentTermsDays = 120
        row.foreignBroker = AUW_FOREIGN_BROKER
        auwBoundRows.add(row)
      }
    })
  }
  function onReinsurerSelected(row) {
    if (row && !isAllianzReinsurer(row.name) && allianzBoundRows.has(row)) {
      row.paymentTermsDays = null
      draft.performanceInstallments.forEach(period => { delete period.reinsurerPaymentTerms?.["r" + (draft.reinsurers.indexOf(row)+1)] })
      allianzBoundRows.delete(row)
    }
    if (row && !isAuwReinsurer(row.name) && auwBoundRows.has(row)) {
      row.foreignBroker = ''
      row.riCommPct = null
      row.taxPct = null
      row.paymentTermsDays = null
      draft.performanceInstallments.forEach((installment) => { delete installment.reinsurerPaymentTerms?.['r' + (draft.reinsurers.indexOf(row) + 1)] })
      auwBoundRows.delete(row)
    }
    if (isAuwReinsurer(row?.name)) row.riCommPct = 10
    applyAuwReinsurerRules()
    syncCaseClauses()
    syncSumInsuredMode()
  }
  function addCaseClause() {
    if (!hasNonFacilityReinsurer.value) return ElMessage.error('Case-specific clauses are available only when at least one selected reinsurer is not a Facility')
    const clause = normalizeClauseList([caseClauseDraft])[0]
    if (!clause) return ElMessage.error('Enter both Clause code and Clause name')
    if (draft.clauses.some((code) => normalizeClauseCode(code) === clause.code)) return ElMessage.error('This Clause code is already included in the case')
    draft.manualClauses.push(clause)
    Object.assign(caseClauseDraft, { code: '', title: '' })
    syncCaseClauses()
  }
  function toggleCglTemplateClause(code, selected) {
    if (!isCglInformation.value || !hasNonFacilityReinsurer.value) return
    const clause = CGL_CLAUSE_PRESETS.find(row => row.code === code)
    if (!clause) return
    if (selected) {
      if (draft.clauses.includes(code)) return
      draft.manualClauses.push({ ...clause })
      syncCaseClauses()
    } else if (isManualClause(code)) removeCaseClause(code)
  }
  function removeCaseClause(code) {
    draft.manualClauses = normalizeClauseList(draft.manualClauses).filter((row) => row.code !== code)
    syncCaseClauses()
  }
  function isManualClause(code) { return normalizeClauseList(draft.manualClauses).some((row) => row.code === code) }
  function clauseSourceLabel(code) {
    const normalized = normalizeClauseCode(code)
    if (UNIVERSAL_CLAUSES.some((row) => row.code === normalized)) return 'Universal'
    return isManualClause(normalized) ? 'Manual' : 'Fixed'
  }

  function recomputeType() {
    if (isStandardCgl(draft)) {
      draft.type = cglType({ ...draft, type: '' })
      return
    }
    const suffix = STRUCTURE_SUFFIX[draft.reinsuranceStructure] || ''
    const prefix = String(draft.typePrefix || '').trim()
    draft.type = suffix ? (prefix ? `${prefix} ${suffix}` : suffix) : prefix
  }

  function onStructureSelected() {
    if (draft.reinsuranceStructure === 'QS') draft.underlyingLimits = ''
    recomputeType()
  }

  let masterDataQueue = Promise.resolve()
  async function loadMasterData({ required = false, quiet = false } = {}) {
    const request = masterDataQueue.catch(() => {}).then(async () => {
      const response = await apiFetch('/api/master-data', { headers: { Accept: 'application/json' } })
      const body = await response.json()
      if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
      mdmRecords.value = Array.isArray(body.records) ? body.records : []
    })
    masterDataQueue = request
    try { await request }
    catch (err) {
      if (required) throw err
      if (quiet) return
      shell.error = err instanceof Error ? err.message : String(err)
      ElMessage.error(shell.error)
    }
  }

  function loadDraftIntoForm(payload) {
    const fresh = emptyDraft()
    Object.assign(fresh, payload || {})
    if (fresh.reinsuranceStructure === 'FACULTATIVE') fresh.reinsuranceStructure = 'QS'
    if (fresh.reinsuranceStructure === 'QS') fresh.underlyingLimits = ''
    const suffix = STRUCTURE_SUFFIX[fresh.reinsuranceStructure] || ''
    if (!String(payload?.typePrefix || '').trim()) {
      const storedType = String(payload?.type || '').trim()
      fresh.typePrefix = suffix && storedType.endsWith(suffix)
        ? storedType.slice(0, -suffix.length).trim()
        : storedType
    }
    fresh.type = suffix
      ? (fresh.typePrefix ? `${fresh.typePrefix} ${suffix}` : suffix)
      : fresh.typePrefix
    if (isStandardCgl(fresh)) {
      fresh.typePrefix = cglTypePrefix(payload || {})
      fresh.type = cglType({ ...fresh, type: '' })
      fresh.interest = String(payload?.interest ?? '')
    }
    fresh.situations = (Array.isArray(payload?.situations) && payload.situations.length ? payload.situations : fresh.situations)
      .map((row) => ({ ...row, clientKey: clientKey() }))
    fresh.reinsurers = (Array.isArray(payload?.reinsurers) && payload.reinsurers.length ? payload.reinsurers : fresh.reinsurers)
      .map((row) => ({ ...row, clientKey: clientKey() }))
    fresh.sumInsured = (Array.isArray(payload?.sumInsured) && payload.sumInsured.length ? payload.sumInsured : fresh.sumInsured)
      .map((row) => ({ ...row, clientKey: clientKey() }))
    fresh.coverages = Array.isArray(payload?.coverages) ? [...payload.coverages] : []
    fresh.coveragesOther = String(payload?.coveragesOther || '')
    fresh.selfInsuredRetention = String(payload?.selfInsuredRetention || '')
    fresh.cglInformation = { ...emptyCglInformation(), ...(payload?.cglInformation || {}) }
    fresh.cglInformation.estimatedTurnover = (Array.isArray(payload?.cglInformation?.estimatedTurnover) ? payload.cglInformation.estimatedTurnover : [])
      .map(row => ({ ...row, clientKey: clientKey() }))
    if (!payload?.cglInformation && fresh.specialAgreement) fresh.cglInformation.specialAgreementApplies = 'applicable'
    fresh.performanceInstallments = (Array.isArray(payload?.performanceInstallments) ? payload.performanceInstallments : [])
      .map((row) => ({ ...row, paymentBaseDate: row?.paymentBaseDate || '', paymentTermsDays: row?.paymentTermsDays ?? null, reinsurerPaymentTerms: row?.reinsurerPaymentTerms && typeof row.reinsurerPaymentTerms === 'object' ? row.reinsurerPaymentTerms : {}, clientKey: clientKey() }))
    fresh.lossRecord = (Array.isArray(payload?.lossRecord) ? payload.lossRecord : [])
      .map((row) => ({ ...row, clientKey: clientKey() }))
    fresh.splitParties = (Array.isArray(payload?.splitParties) && payload.splitParties.length ? payload.splitParties : fresh.splitParties)
      .slice(0, 2).map((row) => ({ ...row, clientKey: clientKey() }))
    fresh.manualClauses = normalizeClauseList(payload?.manualClauses)
    fresh.clauseDetails = normalizeClauseList(payload?.clauseDetails?.length ? payload.clauseDetails : UNIVERSAL_CLAUSES).sort(compareClauses)
    fresh.clauses = fresh.clauseDetails.map((row) => row.code)
    fresh.autoClauses = Array.isArray(payload?.autoClauses) ? payload.autoClauses.map(normalizeClauseCode).filter(Boolean) : []
    Object.keys(draft).forEach((key) => delete draft[key])
    Object.assign(draft, fresh)
    sumInsuredFacilityMode = allSumInsuredFacility(draft)
    applyAuwReinsurerRules()
  }

  async function startEditCase(row) {
    // 允許 reversed，「Correct reversed case」才走得到 #7 的確認（原本是 VM 的修正，2026-09-29 已同步回 Alpha v59）
    if (!row?.caseUid || !['draft', 'posted', 'reversed'].includes(row.status)) return
    loading.value = true; shell.error = ''
    try {
      await loadMasterData({ required: true })
      if (!personnelRecords.value.length) await loadPersonnelOptions()
      const response = await apiFetch('/api/cases?caseUid=' + encodeURIComponent(row.caseUid), { headers: { Accept: 'application/json' } })
      const body = await response.json()
      if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
      resetDraft()
      loadDraftIntoForm(body.case?.payload || {})
      editingCaseUid.value = body.case.caseUid
      editingRowVersion.value = Number(body.case.rowVersion)
      editingOriginalStatus.value = body.case.status || 'draft'
      endorsementFieldsUnlocked.value = false
      activeView.value = 'case-create'
      openSections.value = [...OPEN_SECTIONS]
      window.scrollTo({ top: 0 })
    } catch (err) {
      shell.error = err instanceof Error ? err.message : String(err)
      ElMessage.error(shell.error)
    } finally { loading.value = false }
  }

  function openCasePreview(row) {
    if (!row?.caseUid) return
    casePreview.value = row
    casePreviewVisible.value = true
  }

  async function openPreviewFullCase() {
    const row = casePreview.value
    casePreviewVisible.value = false
    if (row) await startViewCase(row)
  }

  async function startViewCase(row) {
    if (!row?.caseUid) return
    caseDetailLoading.value = true; shell.error = ''
    try {
      const response = await apiFetch('/api/cases?caseUid=' + encodeURIComponent(row.caseUid), { headers: { Accept: 'application/json' } })
      const body = await response.json()
      if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
      selectedCase.value = body.case
      await loadMasterData({ required: true })
      caseDetailTab.value = 'overview'
      caseDocuments.value = []
      documentCoverage.value = { offer: false, required: [], covered: [], missing: [], ready: false, selected: [] }
      signedSlipReminder.value = { complete: false, missing: [], eligibleStatus: false, daysSinceEffective: null, firstReminderOn: '', due: false, today: '', cadenceDays: 7, outboundEnabled: false }
      resetDocumentForm()
      caseWorkflow.value = null
      activeView.value = 'case-detail'
      // Word 文件的 AE Email 要靠人員清單補；重新登入／F5／直接連結時清單尚未載入，文件會被擋
      await Promise.all([loadCaseWorkflow(), loadCaseDocuments(), can('cases.write') ? loadPersonnelOptions() : null])
      window.scrollTo({ top: 0 })
    } catch (err) {
      shell.error = err instanceof Error ? err.message : String(err)
      ElMessage.error(shell.error)
    } finally { caseDetailLoading.value = false }
  }

  function editSelectedCase() {
    if (['draft', 'posted', 'reversed'].includes(selectedCase.value?.status)) startEditCase(selectedCase.value)
  }

  function validSumInsuredAmount(value) {
    const amount = Number(value)
    return filled(value) && Number.isFinite(amount) && amount > 0
  }

  function collectPayloadAnnounceIssues(value) {
    const issues = []
    const add = (label) => issues.push(label)
    if (requiresManualTwRef(value) && !filled(value?.manualTwRef)) add('TW Ref. (for AUW)')
    if (!Number.isInteger(Number(value?.ownerPersonnelId)) || Number(value.ownerPersonnelId) < 1) add('Case Owner');
    [
      ['reinsuranceStructure', 'Reinsurance structure'], ['ae', 'Account Executive'], ['currency', 'Currency'],
      ['classOfBusiness', 'Class'], ['newOrRenew', 'New / Renew'], ['type', 'Type'],
      ['reinsured', 'Reinsured'], ['originalInsured', 'Original insured (EN)'],
      ['policyFrom', 'Effective date'], ['policyTo', 'Expiration date'], ['interest', 'Interest']
    ].forEach(([field, label]) => { if (field === 'type' && isStandardCgl(value)) return; if (!filled(value?.[field])) add(label) })
    if (filled(value?.parentTwRef)) {
      if (!filled(value?.endoEffectiveDate)) add('Endorsement effective date')
      if (!Array.isArray(value?.endoTypes) || !value.endoTypes.length) add('At least one endorsement type')
      if (!filled(value?.endoText)) add('Endorsement wording')
    }
    const situations = Array.isArray(value?.situations) ? value.situations : []
    if (!situations.length) add(isStandardCgl(value) ? 'Principal Address' : 'Situation')
    situations.forEach((row, index) => {
      if (!filled(row?.address)) add(isStandardCgl(value) ? `Principal Address ${index + 1}` : `Situation ${index + 1} Risk Address`)
      if (!/^\d{3,6}$/.test(String(row?.postcode || '').trim())) add(`${isStandardCgl(value) ? 'Principal Address' : 'Situation'} ${index + 1} Postcode`)
    })
    const reinsurers = Array.isArray(value?.reinsurers) ? value.reinsurers : []
    if (!reinsurers.length) add('Schedule of Security')
    reinsurers.forEach((row, index) => {
      if (!filled(row?.name)) add(`Reinsurer ${index + 1}`)
      if (!filled(row?.sharePct)) add(`Reinsurer ${index + 1} Order hereon`)
      if (!filled(row?.premium)) add(`Reinsurer ${index + 1} Premium`)
      if (!filled(row?.riCommPct)) add(`Reinsurer ${index + 1} Deductions`)
      if (!filled(row?.taxPct)) add(`Reinsurer ${index + 1} Tax`)
      if (isAuwReinsurer(row?.name)) {
        if (row.foreignBroker !== AUW_FOREIGN_BROKER) add(`Reinsurer ${index + 1} Foreign RI Broker must be Howden Specialty Limited for AUW`)
        if (filled(row?.taxPct) && Number(row.taxPct) !== 0) add(`Reinsurer ${index + 1} Tax must be 0% for AUW`)
      }
    });
    [['limitOfLiability', liabilityLimitLabel(value)], ['deductibles', 'Deductibles'], ['originalConditions', 'Original Conditions'], ...(isStandardCgl(value) ? [] : [['occupation', 'Occupation'], ['construction', 'Construction']])]
      .forEach(([field, label]) => { if (!filled(value?.[field])) add(label) })
    if (!isStandardCgl(value) && value?.basisOfValuation === 'Other' && !filled(value?.basisOfValuationOther)) add('Basis of Valuation — Other')
    if (!isStandardCgl(value)) {
    const sumInsured = Array.isArray(value?.sumInsured) ? value.sumInsured : []
    if (!sumInsured.length) add('Breakdown of Sum Insured')
    sumInsured.forEach((row, index) => {
      if (!filled(row?.category)) add(`Sum insured ${index + 1} Interest insured`)
      if (!validSumInsuredAmount(row?.amount)) add(`Sum insured ${index + 1} Amount must be greater than 0`)
    })
    sumInsuredPlacementIssues(value).forEach(issue => add(issue.label))
    }
    cglUnderlyingIssues(value).forEach(issue => add(issue.label))
    cglTypeIssues(value).forEach(issue => add(issue.label))
    cglRiskDetailsIssues(value).forEach(issue => add(issue.label))
    cglInformationIssues(value).forEach(issue => add(issue.label))
    if (!filled(value?.lossAdvisedDate)) add('Loss record advised by broker on')
    if (!validLossRecordYears(value?.lossRecordYears, value)) add('Loss history years')
    const lossRecord = Array.isArray(value?.lossRecord) ? value.lossRecord : []
    if (filled(value?.lossRecordYears) && Number(value.lossRecordYears) === 0 && lossRecord.length) add('Loss Record must be empty when loss history years is 0')
    lossRecord.forEach((row, index) => {
      if (!filled(row?.date)) add(`Loss ${index + 1} Date of Loss`)
      if (!filled(row?.cause)) add(`Loss ${index + 1} Cause`)
      if (!filled(row?.lossPaid)) add(`Loss ${index + 1} Loss Paid`)
    });
    [['originalPremium', '100% Premium']]
      .forEach(([field, label]) => { if (!filled(value?.[field])) add(label) })
    if (value?.installmentEnabled) {
      const installmentResult = installmentValidationFor(value)
      if (!installmentResult.valid) add(installmentResult.message)
      if (value?.renewedFromTwRef) {
        const start = String(value.policyFrom || '')
        const expiry = String(value.policyTo || '')
        ;(Array.isArray(value.performanceInstallments) ? value.performanceInstallments : []).forEach((row, index) => {
          const month = String(row?.performanceMonth || '')
          const validMonth = /^\d{4}-(0[1-9]|1[0-2])$/.test(month)
          const nextMonth = validMonth
            ? new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5, 7)), 1)).toISOString().slice(0, 10)
            : ''
          if (!validMonth || !(`${month}-01` < expiry && nextMonth > start)) {
            add(`Installment ${index + 1} performance month must be within renewal coverage`)
          }
          const baseDate = String(row?.paymentBaseDate || '')
          if (!(baseDate >= start && baseDate < expiry)) {
            add(`Installment ${index + 1} payment base date must be within renewal coverage`)
          }
        })
      }
    }
    if (value?.splitEnabled) {
      const splitResult = splitValidationFor(value)
      if (!splitResult.valid) add(splitResult.message)
    }
    return issues
  }

  function validPostcode(value) { return /^\d{3,6}$/.test(String(value || '').trim()) }
  function validPositiveInteger(value) {
    const number = Number(value)
    return filled(value) && Number.isInteger(number) && number > 0
  }
  function validLossRecordYears(value, caseData) {
    const number = Number(value)
    return filled(value) && Number.isInteger(number) && number >= 0
      && (number > 0 || (caseData?.newOrRenew === 'New' && !filled(caseData?.renewedFromTwRef)))
  }

  function fieldInvalid(key, validator) {
    if (key === 'manualTwRef' && manualRefSaveAttempted.value && requiresManualTwRef(draft)) return !filled(draft.manualTwRef)
    if (key === 'lossAdvisedDate' && lossSaveAttempted.value) return !filled(draft.lossAdvisedDate)
    if (key === 'lossRecordYears' && lossSaveAttempted.value) return !validLossRecordYears(draft.lossRecordYears, draft)
    if (!reviewAttempted.value) return false
    const value = draft[key]
    if (Array.isArray(value)) return value.length === 0
    if (validator === 'positiveInteger') return !validPositiveInteger(value)
    if (validator === 'lossRecordYears') return !validLossRecordYears(value, draft)
    return !filled(value)
  }

  function rowInvalid(listName, index, key, validator) {
    if (!reviewAttempted.value) return false
    const row = draft[listName] && draft[listName][index]
    const value = row && row[key]
    if (validator === 'postcode') return !validPostcode(value)
    if (listName === 'sumInsured' && key === 'category' && sumInsuredPlacementIssues(draft).some(issue => issue.kind === 'duplicate' && issue.field === `sumInsured.${index}.category`)) return true
    if (validator === 'sumInsuredLocation') return sumLocationIndex(row, draft.situations.length) === null
    if (validator === 'sumInsuredAmount') return !validSumInsuredAmount(value)
    return !filled(value)
  }

  function collectRequiredIssues() {
    const issues = []
    const add = (section, label) => {
      const combined = draft.classOfBusiness === 'Property'
        ? ['occupation', 'sumInsured', 'loss', 'specialAgreement'].includes(section)
        : isCglInformation.value && ['loss', 'specialAgreement'].includes(section)
      issues.push({ section: combined ? 'information' : section, label })
    }
    if (hasManualTwRefReinsurer.value && !filled(draft.manualTwRef)) add('security', 'TW Ref. (for AUW)')
    [
      ['reinsuranceStructure', 'Reinsurance structure'], ['ae', 'Account Executive'], ['currency', 'Currency'],
      ['classOfBusiness', 'Class'], ['newOrRenew', 'New / Renew'], ['type', 'Type'],
      ['reinsured', 'Reinsured'], ['originalInsured', 'Original insured (EN)'],
      ['policyFrom', 'Effective date'], ['policyTo', 'Expiration date'], ['interest', 'Interest']
    ].forEach(([key, label]) => { if (key === 'type' && isCglInformation.value) return; if (!filled(draft[key])) add('risk', label) })
    if (draft.parentTwRef) {
      if (!filled(draft.endoEffectiveDate)) add('risk', 'Endorsement effective date')
      if (!Array.isArray(draft.endoTypes) || !draft.endoTypes.length) add('risk', 'At least one endorsement type')
      if (!filled(draft.endoText)) add('risk', 'Endorsement wording')
    }
    if (!draft.situations.length) add('risk', isCglInformation.value ? 'Principal Address' : 'Situation')
    draft.situations.forEach((row, index) => {
      if (!filled(row.address)) add('risk', isCglInformation.value ? `Principal Address ${index + 1}` : `Situation ${index + 1} Risk Address`)
      if (!validPostcode(row.postcode)) add('risk', `${isCglInformation.value ? 'Principal Address' : 'Situation'} ${index + 1} Postcode`)
    })

    if (!draft.reinsurers.length) add('security', 'Schedule of Security')
    draft.reinsurers.forEach((row, index) => {
      if (!filled(row.name)) add('security', `Reinsurer ${index + 1}`)
      if (!filled(row.sharePct)) add('security', `Reinsurer ${index + 1} Order hereon`)
    })

    if (!filled(draft.limitOfLiability)) add('terms', liabilityLimitLabel(draft))
    if (!filled(draft.deductibles)) add('terms', 'Deductibles')
    if (!filled(draft.originalConditions)) add('terms', 'Original Conditions')
    if (!isCglInformation.value && draft.basisOfValuation === 'Other' && !filled(draft.basisOfValuationOther)) add('terms', 'Basis of Valuation — Other')
    if (!isCglInformation.value) {
    if (!filled(draft.occupation)) add('occupation', 'Occupation')
    if (!filled(draft.construction)) add('occupation', 'Construction')

    if (!draft.sumInsured.length) add('sumInsured', 'Breakdown of Sum Insured')
    draft.sumInsured.forEach((row, index) => {
      if (!filled(row.category)) add('sumInsured', `Sum insured ${index + 1} Interest insured`)
      if (!validSumInsuredAmount(row.amount)) add('sumInsured', `Sum insured ${index + 1} Amount must be greater than 0`)
    })
    sumInsuredPlacementIssues(draft).forEach(issue => add('sumInsured', issue.label))
    }
    cglUnderlyingIssues(draft).forEach(issue => add('terms', issue.label))
    cglTypeIssues(draft).forEach(issue => add('risk', issue.label))
    cglRiskDetailsIssues(draft).forEach(issue => add('risk', issue.label))
    cglInformationIssues(draft).forEach(issue => add('information', issue.label))
    if (!filled(draft.lossAdvisedDate)) add('loss', 'Loss record advised by broker on')
    if (!validLossRecordYears(draft.lossRecordYears, draft)) add('loss', 'Loss history years')
    if (filled(draft.lossRecordYears) && Number(draft.lossRecordYears) === 0 && draft.lossRecord.length) add('loss', 'Loss Record must be empty when loss history years is 0')
    draft.lossRecord.forEach((row, index) => {
      if (!filled(row.date)) add('loss', `Loss ${index + 1} Date of Loss`)
      if (!filled(row.cause)) add('loss', `Loss ${index + 1} Cause`)
      if (!filled(row.lossPaid)) add('loss', `Loss ${index + 1} Loss Paid`)
    });

    [
      ['originalPremium', '100% Premium'],
    ].forEach(([key, label]) => { if (!filled(draft[key])) add('cedantPremium', label) })
    if (draft.installmentEnabled) {
      const installmentResult = installmentValidationFor(draft)
      if (!installmentResult.valid) add('cedantPremium', installmentResult.message)
    }
    if (draft.splitEnabled) {
      const splitResult = splitValidationFor(draft)
      if (!splitResult.valid) add('split', splitResult.message)
    }
    draft.reinsurers.forEach((row, index) => {
      if (!filled(row.premium)) add('reinsurerPremium', `Reinsurer ${index + 1} Premium`)
      if (!filled(row.riCommPct)) add('reinsurerPremium', `Reinsurer ${index + 1} Deductions`)
      if (!filled(row.taxPct)) add('reinsurerPremium', `Reinsurer ${index + 1} Tax`)
    })
    return issues
  }

  async function reviewAndConfirm() {
    try { await loadMasterData({ required: true }) }
    catch (err) { ElMessage.error(err instanceof Error ? err.message : String(err)); return }
    reviewAttempted.value = true
    const issues = collectRequiredIssues()
    if (!issues.length) {
      reviewDialogVisible.value = true
      return
    }
    openSections.value = Array.from(new Set(openSections.value.concat(issues.map((issue) => issue.section))))
    ElMessage.error(validationMessage.value)
    await nextTick()
    window.setTimeout(() => {
      const first = document.querySelector('.case-form .is-required-error, .case-form .required-invalid')
      if (!first) return
      first.scrollIntoView({ behavior: 'smooth', block: 'center' })
      const focusTarget = first.querySelector('input, textarea, button, [role="combobox"]')
      if (focusTarget && typeof focusTarget.focus === 'function') focusTarget.focus({ preventScroll: true })
    }, 180)
  }

  async function saveReviewedDraft() {
    reviewDialogVisible.value = false
    await saveDraft()
  }

  function plainDraft() {
    syncSumInsuredMode()
    applyAuwReinsurerRules()
    const value = JSON.parse(JSON.stringify(draft))
    value.clauseDetails = draftClauseDetails.value.map(row => ({ ...row }))
    value.manualClauses = resolveClauseTitles(value.manualClauses, mdmRecords.value, draft)
    value.situations.forEach((row) => delete row.clientKey)
    value.reinsurers.forEach((row) => delete row.clientKey)
    value.sumInsured.forEach((row) => delete row.clientKey)
    value.performanceInstallments.forEach((row) => delete row.clientKey)
    value.splitParties.forEach((row) => delete row.clientKey)
    value.lossRecord.forEach((row) => delete row.clientKey)
    return value
  }

  async function loadData() {
    if (!can('cases.read.all') && !can('cases.read.own')) {
      loading.value = false
      cases.value = []
      summary.value = { total: 0, draft: 0, posted: 0, closed: 0, reversed: 0 }
      return
    }
    loading.value = true; shell.error = ''
    try {
      const response = await apiFetch('/api/cases', { headers: { Accept: 'application/json' } })
      const body = await response.json()
      if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
      cases.value = Array.isArray(body.cases) ? body.cases : []
      summary.value = body.summary || summary.value
    } catch (err) { shell.error = err instanceof Error ? err.message : String(err) }
    finally { loading.value = false }
  }

  async function recycleDraft(row) {
    try {
      await ElMessageBox.confirm(
        'Move this Draft to the recycle bin? It can be restored for five years and cannot be permanently deleted by any role.',
        'Recycle Draft',
        { type: 'warning', confirmButtonText: 'Move to recycle bin', cancelButtonText: 'Cancel' }
      )
    } catch (_) { return }
    recycleSaving.value = true
    try {
      await jsonOrThrow(await apiFetch('/api/draft-recycle-bin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ action: 'recycle', caseUid: row.caseUid, rowVersion: Number(row.rowVersion) })
      }))
      ElMessage.success('Draft moved to the five-year recycle bin.')
      await loadData()
    } catch (err) {
      reportWriteError(err, () => loadData())
    } finally {
      recycleSaving.value = false
    }
  }

  function onOwnerSelected(personnelId) {
    const person = personnelRecords.value.find((row) => Number(row.id) === Number(personnelId))
    draft.ownerPersonnelName = person?.name || ''
  }

  async function loadPersonnelOptions() {
    try {
      const response = await apiFetch('/api/personnel-options', { headers: { Accept: 'application/json' } })
      const body = await response.json()
      if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
      personnelRecords.value = Array.isArray(body.personnel) ? body.personnel : []
      if (activeView.value === 'case-create' && !isEditing.value && !draft.ownerPersonnelId && body.defaultOwnerId) {
        draft.ownerPersonnelId = Number(body.defaultOwnerId)
        onOwnerSelected(draft.ownerPersonnelId)
      }
    } catch (err) {
      shell.error = err instanceof Error ? err.message : String(err)
    }
  }

  async function saveDraft() {
    const premiumError = premiumInputErrors(draft, selectedPayload.value)[0]
    if (premiumError) {
      openSections.value = [...new Set([...openSections.value, 'cedantPremium', 'reinsurerPremium'])]
      ElMessage.error(premiumError)
      return
    }
    const installmentCountError = installmentCountErrorFor(draft)
    if (installmentCountError) {
      openSections.value = [...new Set([...openSections.value, 'cedantPremium'])]
      ElMessage.error(installmentCountError)
      return
    }
    lossSaveAttempted.value = true
    const lossError = !filled(draft.lossAdvisedDate)
      ? 'Loss record advised by broker on is required before saving.'
      : !validLossRecordYears(draft.lossRecordYears, draft)
        ? 'Loss history years is required, and 0 is allowed only for a New case.'
        : Number(draft.lossRecordYears) === 0 && draft.lossRecord.length
          ? 'Loss Record must be empty when loss history years is 0.' : ''
    if (lossError) {
      openSections.value = [...new Set([...openSections.value, isCglInformation.value || draft.classOfBusiness === 'Property' ? 'information' : 'loss'])]
      ElMessage.error(lossError)
      return
    }
    manualRefSaveAttempted.value = true
    if (requiresManualTwRef(draft) && !filled(draft.manualTwRef)) {
      ElMessage.error('TW Ref. (for AUW) is required before saving an AUW Draft.')
      await nextTick()
      document.querySelector('[data-testid="manual-tw-ref-section"] input')?.focus()
      return
    }
    const updating = isEditing.value
    // Alpha #7：Reversed 案件存檔會直接回到 Announced，要先明確確認；後端也會獨立檢查
    const wasReversed = editingOriginalStatus.value === 'reversed'
    if (updating && wasReversed) {
      try {
        await ElMessageBox.confirm(
          'This case was Reversed. Saving will correct it and move it back to Announced status, without repeating the original Announce document review. Continue?',
          'Confirm correction',
          { confirmButtonText: 'Save and move to Announced', cancelButtonText: 'Cancel', type: 'warning' }
        )
      } catch { return }
    }
    saving.value = true; shell.error = ''; saveMessage.value = ''
    try {
      await loadMasterData({ required: true })
      const body = await jsonOrThrow(await apiFetch('/api/cases', {
        method: updating ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(updating
          ? { caseUid: editingCaseUid.value, rowVersion: editingRowVersion.value, case: plainDraft(), reverseCorrectionConfirmed: wasReversed }
          : { case: plainDraft() })
      }))
      if (updating) editingRowVersion.value = Number(body.case.rowVersion)
      const wasAnnounced = editingOriginalStatus.value === 'posted'
      saveMessage.value = updating
        ? `${wasReversed ? 'Reversed case corrected and moved to Announced' : wasAnnounced ? 'Announced case' : 'Draft'} · version ${body.case.rowVersion}.`
        : 'Draft saved. Reference will be assigned later in the confirmed workflow.'
      ElMessage.success(updating
        ? (wasReversed ? 'Correction saved — case moved to Announced; record Accounting notification' : wasAnnounced ? 'Announced case updated — record Accounting notification if required' : 'Draft updated')
        : 'Draft saved')
      await loadData()
      if (updating) {
        const savedCase = { caseUid: body.case.caseUid, status: body.case.status }
        resetDraft()
        await startViewCase(savedCase)
      } else {
        activeView.value = 'cases'
        resetDraft()
        window.scrollTo({ top: 0 })
      }
    } catch (err) {
      shell.error = err instanceof Error ? err.message : String(err)
      reportWriteError(err, () => refreshSelectedCase())
    } finally { saving.value = false }
  }

  // 在案件畫面時再按一次左側「Account List」：回到列表（Alpha 的 selectView('cases')）
  watch(() => shell.navClicks, () => {
    if (activeView.value === 'case-create') resetDraft()
    backToCases()
    loadData()
  })

  // Accounting 的「開啟案件」：/cases?case=<caseUid>&tab=soa（Alpha 的 openAccountingCase）
  const route = useRoute()
  const router = useRouter()
  async function openFromQuery() {
    if (route.query.action === 'new') {
      await router.replace({ path: '/cases' })
      if (can('cases.write')) startNewCase()
      return
    }
    const caseUid = typeof route.query.case === 'string' ? route.query.case : ''
    if (!caseUid) return
    const tab = route.query.tab === 'soa' ? 'soa' : ''
    router.replace({ path: '/cases' })
    await startViewCase({ caseUid })
    if (tab && selectedCase.value?.caseUid === caseUid) caseDetailTab.value = tab
  }

  onMounted(async () => {
    await loadData()
    await openFromQuery()
  })

  let clauseTitleRefresh = null
  let refreshingClauseTitles = false
  async function refreshVisibleClauseTitles() {
    if (document.visibilityState === 'hidden' || refreshingClauseTitles || !['case-create', 'case-detail'].includes(activeView.value)) return
    refreshingClauseTitles = true
    try { await loadMasterData({ quiet: true }) }
    finally { refreshingClauseTitles = false }
  }
  onMounted(() => {
    window.addEventListener('focus', refreshVisibleClauseTitles)
    document.addEventListener('visibilitychange', refreshVisibleClauseTitles)
    clauseTitleRefresh = window.setInterval(refreshVisibleClauseTitles, 30000)
  })
  onBeforeUnmount(() => {
    window.removeEventListener('focus', refreshVisibleClauseTitles)
    document.removeEventListener('visibilitychange', refreshVisibleClauseTitles)
    window.clearInterval(clauseTitleRefresh)
  })

  return {
    can, activeView, currentHeader, loading, saving, saveMessage,
    isCglInformation, isStandardCgl, cglInformationIssues, displayTwRef, isAuwReinsurer, isAllianzReinsurer, hasAllianz, isGreatAmericanTarget, hasGreatAmerican, isPureAuwCase, requiresManualTwRef, hasManualTwRefReinsurer, filters, filteredCases, draft, openSections, startNewCase, cancelNewCase, onPolicyFromChange,
    recycleSaving, recycleDraft,
    addSituation, removeSituation, addReinsurer, removeReinsurer, addSumInsured, removeSumInsured,
    isEditing, isEndorsementDraft, auwRefLocked, editingRowVersion, editingOriginalStatus, endorsementFieldsUnlocked, startEditCase, startViewCase,
    casePreviewVisible, casePreview, openCasePreview, openPreviewFullCase, formatPolicyDateTime, formatPolicyPeriod,
    refreshSelectedCase, selectedCase, selectedPayload, selectedSumInsuredIssues, selectedSumInsuredWarning, selectedOverview, selectedCaseTransactions, caseDetailLoading, caseDetailTab, caseDetailTabLabel, backToCases, editSelectedCase,
    caseWorkflow, workflowLoading, workflowSaving, loadCaseWorkflow, createEndorsement, createRenewal, reverseSelectedCase, viewWorkflowCase,
    accountingDialogVisible, accountingForm, openAccountingNotification, saveAccountingNotification,
    claimsLoading, claimsSaving, claimsState, claimForm, paymentDialogVisible, paymentForm, createClaim, updateClaimReserve, openClaimPayment, recordClaimPayment, claimTotalPaid, loadClaims,
    documentsLoading, documentsSaving, documentGenerating, generatedDocumentCase, isTreatyDocumentCase, unsupportedDebitBankCurrency, missingDebitPaymentTerms, missingDebitInstallmentBaseDates, missingDebitInstallmentPaymentTerms, missingDebitInstallmentAllocation, invalidDebitInstallmentAllocation, caseDocuments, documentCoverage, signedSlipReminder, documentForm, documentFileList, selectedReinsurers, documentReadinessText, selectedAnnounceIssues,
    caseReminders, remindersLoading, loadCaseReminders, reminderPreview, reminderPreviewVisible, openReminderPreview, reminderStatusLabel, reminderStatusType, paymentReminderLabel,
    downloadGeneratedDocument, loadCaseDocuments, onCaseDetailTabChange, onDocumentKindChange, onDocumentFileChange, onDocumentFileRemove, uploadCaseDocument,
    toggleDocumentSelection, downloadCaseDocument, deleteCaseDocument, documentKindLabel, displayReinsurerName, formatFileSize, formatDateTime,
    announceDialogVisible, announceConfirmed, announcing, openAnnounceReview, announceSelectedCase,
    personnelRecords, onOwnerSelected, departmentLabel,
    masterOptions, onClassSelected, structureLabel, recomputeType, onStructureSelected, onReinsurerSelected,
    draftClauseDetails, caseClauseDraft, addCaseClause, removeCaseClause, isManualClause, clauseSourceLabel, CGL_CLAUSE_PRESETS, toggleCglTemplateClause, cglAnnual,
    reviewAttempted, reviewReady, validationMessage, fieldInvalid, rowInvalid, reviewAndConfirm,
    isSwissProperty, isSwissFacility, reviewDialogVisible, totalOrderHereon, totalSumInsured, draftSumInsuredWarning, sumInsuredGroups, unassignedSumInsured, sumGroupInvalid, allFacilityReinsurers, hasNonFacilityReinsurer, lossRecordSummary, lossRecordYearsMin, installmentAllocations, installmentStatus,
    addInstallment, removeInstallment, onInstallmentToggle, installmentRowInvalid,
    splitStatus, onSplitToggle, splitPartyInvalid, splitPersonOptions, onSplitPersonSelected,
    formatAmount, formatMoney, formatCurrency, formatMoneyInput, parseMoneyInput, saveReviewedDraft,
    addLossRecord, removeLossRecord, lossRowInvalid,
    statusLabel, loadData, saveDraft
  }
}
