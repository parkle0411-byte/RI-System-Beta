// 案件工作區的邏輯：逐函式移植自 Alpha public/app.js（名稱、順序、內容盡量相同，方便之後對照同步）。
// 模板在 CaseWorkspace.vue（由 scripts/build_case_workspace.py 從 Alpha index.html 切出）。
//
// 與 Alpha 不同的地方（都記在 MIGRATION-STATUS.md）：
//   - fetch() → apiFetch()（補上 CSRF 與同源 cookie；回傳一樣的 Response）
//   - 金額合計用統一的逐步進位算法（src/alpha/caseCalculations.js）
//   - startEditCase 允許 Reversed（Alpha 漏了，「Correct reversed case」按了沒反應）
//   - 文件單檔上限 10 MB（Alpha 5 MB）
//   - 從 Accounting 點 TW Ref 會帶 ?case=…&tab=soa 過來（Alpha 是同一頁切換）：載入後直接開該案件的 SOA 分頁
//   - 理賠：出險日與付款日期必填（後端檢查，錯誤訊息照常顯示）
//   - 產生 Word／PDF 文件的程式尚未移植：產生文件的按鈕停用
import { computed, nextTick, onMounted, reactive, ref, watch, watchEffect } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { apiFetch } from '../api'
import { can } from '../auth'
import { RICaseCalculations } from '../alpha/caseCalculations'
import {
  STRUCTURE_SUFFIX, UNIVERSAL_CLAUSES, clientKey, compareClauses, emptyDraft, normalizeClauseCode, normalizeClauseList
} from '../alpha/constants'
import {
  departmentLabel, filled, formatAmount, formatCurrency, formatDateTime, formatFileSize, formatMoney,
  formatPolicyDateTime, formatPolicyPeriod, jsonOrThrow, reportWriteError, statusLabel, structureLabel
} from '../alpha/format'
import { setHeader, shell } from '../alpha/shell'

const MAX_DOCUMENT_BYTES = 10 * 1024 * 1024 // VM：10 MB（Alpha 5 MB）
const OPEN_SECTIONS = ['risk', 'security', 'terms', 'occupation', 'sumInsured', 'loss', 'specialAgreement', 'cedantPremium', 'reinsurerPremium', 'split', 'conditions']
const headers = {
  cases: { kicker: 'Placement', title: 'Account List', subtitle: 'All facultative outward cases' },
  'case-create': { kicker: 'Placement · Draft', title: 'Account', subtitle: 'Draft — not yet saved' },
  'case-detail': { kicker: 'Placement · Case', title: 'Case overview', subtitle: 'Saved case snapshot and computed amounts' }
}

export function useCaseWorkspace() {
  const activeView = ref('cases')
  const loading = ref(true)
  const saving = ref(false)
  const saveMessage = ref('')
  const reviewAttempted = ref(false)
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
  const openSections = ref([...OPEN_SECTIONS])
  const reviewReady = computed(() => reviewAttempted.value && collectRequiredIssues().length === 0)
  const validationMessage = computed(() => {
    if (!reviewAttempted.value) return ''
    const count = collectRequiredIssues().length
    return count === 0
      ? 'All required fields are complete. This draft is ready for the confirmation workflow milestone.'
      : `Please complete ${count} required field${count === 1 ? '' : 's'} before Review & confirm.`
  })
  const totalOrderHereon = computed(() => RICaseCalculations.totalOrderHereon(draft))
  const isFacilityName = (name) => /\(Facility\)\s*$/i.test(String(name || '').trim())
  const selectedDraftReinsurers = computed(() => draft.reinsurers.filter((row) => String(row.name || '').trim()))
  const allFacilityReinsurers = computed(() => selectedDraftReinsurers.value.length > 0 && selectedDraftReinsurers.value.every((row) => isFacilityName(row.name)))
  const hasNonFacilityReinsurer = computed(() => selectedDraftReinsurers.value.some((row) => !isFacilityName(row.name)))
  const totalSumInsured = computed(() => RICaseCalculations.totalSumInsured(draft))
  const lossRecordSummary = computed(() => lossRecordSummaryFor(draft))
  const installmentAllocations = computed(() => installmentAllocationsFor(draft))
  const installmentStatus = computed(() => installmentValidationFor(draft))
  const splitStatus = computed(() => splitValidationFor(draft))

  const isEditing = computed(() => Boolean(editingCaseUid.value))
  const isEndorsementDraft = computed(() => Boolean(draft.parentTwRef))
  const selectedPayload = computed(() => selectedCase.value?.payload || {})
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
      clauseDetails: normalizeClauseList(payload.clauseDetails?.length ? payload.clauseDetails : UNIVERSAL_CLAUSES).sort(compareClauses)
    }
  })
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
  const caseDetailTabLabel = computed(() => ({ documents: 'Cover & Debit Note', soa: 'SOA / Transactions', claims: 'Claim', endorsements: 'Endorsements' }[caseDetailTab.value] || 'Case detail'))
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
    key: `${transaction.txNo || 'transaction'}:${index}`,
    sourceLabel: transaction.source === 'claim' ? 'Claim' : 'Premium',
    reconciliationRef: reconciliationRefFor(selectedPayload.value, transaction),
    settlement: transaction.source === 'claim'
      ? (transaction.settlement === 'settled' ? 'settled' : 'open')
      : (transaction.paymentScheduleSettlement || 'not_tracked')
  })))
  const currentHeader = computed(() => {
    if (activeView.value === 'case-create' && isEditing.value) {
      return { ...headers['case-create'], kicker: 'Placement · Draft', title: draft.parentTwRef ? 'New endorsement' : 'Account', subtitle: draft.parentTwRef ? ('Endorsement to ' + draft.parentTwRef) : 'Draft — versioned update' }
    }
    if (activeView.value === 'case-detail' && selectedCase.value) {
      const payload = selectedPayload.value
      return {
        ...headers['case-detail'],
        title: selectedCase.value.twRef || 'Draft · not assigned',
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
      return [row.twRef, row.originalInsured, row.originalInsuredCn, row.reinsured, row.className, row.aeName, ...(Array.isArray(row.reinsurers) ? row.reinsurers : [])]
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
    const income = Number(RICaseCalculations.totals(caseData).brokerage || 0)
    const allocations = rows.map((row) => {
      const ratio = totalPremium === 0 ? Number(row?.ratio || 0) / 100 : Number(row?.premium || 0) / totalPremium
      return {
        ...row,
        premium: totalPremium === 0 ? 0 : Number(row?.premium || 0),
        ratio,
        income: round2(income * ratio)
      }
    })
    if (allocations.length) {
      const tail = round2(income - allocations.reduce((sum, row) => sum + row.income, 0))
      allocations[0].income = round2(allocations[0].income + tail)
    }
    return allocations
  }

  function installmentValidationFor(caseData) {
    if (!caseData?.installmentEnabled) return { valid: true, message: '' }
    const rows = Array.isArray(caseData.performanceInstallments) ? caseData.performanceInstallments : []
    if (!rows.length) return { valid: false, message: 'Add at least one installment.' }
    if (rows.some((row) => !/^\d{4}-\d{2}$/.test(String(row?.performanceMonth || '')))) return { valid: false, message: 'Every installment needs a performance month.' }
    if (rows.some((row) => !/^\d{4}-\d{2}-\d{2}$/.test(String(row?.paymentBaseDate || '')))) return { valid: false, message: 'Every installment needs a payment base date.' }
    const totalPremium = Number(caseData.originalPremium || 0)
    if (totalPremium === 0) {
      const sum = rows.reduce((total, row) => total + Number(row?.ratio || 0), 0)
      if (rows.some((row) => Number(row?.ratio || 0) <= 0) || Math.abs(sum - 100) > 0.0001) return { valid: false, message: 'Installment ratios must be greater than 0 and total 100%.' }
    } else {
      const invalid = rows.some((row) => row?.premium === '' || row?.premium === null || row?.premium === undefined || !Number.isFinite(Number(row.premium)))
      if (invalid) return { valid: false, message: 'Enter the Premium for every installment.' }
      const sum = rows.reduce((total, row) => total + Number(row.premium), 0)
      if (Math.abs(sum - totalPremium) > 0.01) return { valid: false, message: 'Installment Premium total must equal 100% Premium.' }
    }
    return { valid: true, message: 'Installment allocation is complete.' }
  }

  function addInstallment() {
    draft.performanceInstallments.push({ clientKey: clientKey(), id: `I${Date.now()}-${Math.random().toString(36).slice(2, 6)}`, performanceMonth: '', paymentBaseDate: '', paymentTermsDays: null, reinsurerPaymentTerms: {}, premium: null, ratio: null })
  }
  function removeInstallment(index) { draft.performanceInstallments.splice(index, 1) }
  function onInstallmentToggle(enabled) { if (enabled && !draft.performanceInstallments.length) addInstallment() }
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
    if (!Number.isInteger(years) || years <= 0) return `${subject} — history period not specified`
    return `${subject} in the past ${years} ${years === 1 ? 'year' : 'years'}`
  }
  function addLossRecord() {
    draft.lossRecord.push({ clientKey: clientKey(), date: '', cause: '', lossPaid: null })
  }
  function removeLossRecord(index) { draft.lossRecord.splice(index, 1) }
  function lossRowInvalid(index, key) {
    if (!reviewAttempted.value) return false
    const row = draft.lossRecord[index] || {}
    return !filled(row[key])
  }

  function resetDraft() {
    const fresh = emptyDraft()
    Object.keys(draft).forEach((key) => delete draft[key])
    Object.assign(draft, fresh)
    openSections.value = [...OPEN_SECTIONS]
    saveMessage.value = ''
    reviewAttempted.value = false
    reviewDialogVisible.value = false
    editingCaseUid.value = ''
    editingRowVersion.value = null
    editingOriginalStatus.value = 'draft'
    endorsementFieldsUnlocked.value = false
    Object.assign(caseClauseDraft, { code: '', title: '' })
  }

  function startNewCase() {
    resetDraft()
    activeView.value = 'case-create'
    if (!mdmRecords.value.length) loadMasterData()
    loadPersonnelOptions()
    window.scrollTo({ top: 0 })
  }
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

  // VM：產生 Word／PDF 的程式尚未移植（按鈕停用；這裡只是保險）
  function downloadGeneratedDocument() {
    ElMessage.warning('Document generation is not available on the VM yet.')
  }

  async function loadCaseDocuments() {
    if (!selectedCase.value?.caseUid) return
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
    try {
      await ElMessageBox.confirm(`This will ${label} from the current case.`, 'Continue workflow', { confirmButtonText: 'Create draft', cancelButtonText: 'Cancel', type: 'warning' })
    } catch { return }
    workflowSaving.value = true
    try {
      const response = await apiFetch('/api/case-workflow', {
        method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ action, caseUid: selectedCase.value.caseUid, rowVersion: selectedCase.value.rowVersion })
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

  function openClaimPayment(claim) {
    activeClaimId.value = claim.id
    Object.assign(paymentForm, { date: '', amount: null, note: '' })
    paymentDialogVisible.value = true
  }

  async function recordClaimPayment() {
    // 理賠付款可以是負數（追償、自負額沖抵等），只擋 0 與無效輸入（同 Alpha）
    if (!Number(paymentForm.amount)) return ElMessage.error('Enter a non-zero payment amount.')
    const saved = await submitClaimAction('record_payment', { claimId: activeClaimId.value, payment: { ...paymentForm } })
    if (!saved) return
    paymentDialogVisible.value = false
    ElMessage.success('Payment recorded and Claim Leg 1/2 transactions created')
  }

  function claimTotalPaid(claim) {
    return (Array.isArray(claim?.payments) ? claim.payments : []).reduce((sum, payment) => sum + Number(payment?.amount || 0), 0)
  }

  function onCaseDetailTabChange(name) {
    if (name === 'documents') loadCaseDocuments()
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
      ElMessage.success(`Case Announced · ${body.case.twRef}`)
    } catch (err) {
      reportWriteError(err, () => refreshSelectedCase())
      await loadCaseDocuments()
    } finally { announcing.value = false }
  }
  function addSituation() { draft.situations.push({ clientKey: clientKey(), address: '', postcode: '' }) }
  function removeSituation(index) { if (draft.situations.length > 1) draft.situations.splice(index, 1) }
  function addReinsurer() { draft.reinsurers.push({ clientKey: clientKey(), name: '', sharePct: null, premium: null, riCommPct: null, taxPct: null, paymentTermsDays: null, foreignBroker: '', settlementRef: '' }) }
  function removeReinsurer(index) { if (draft.reinsurers.length > 1) { draft.reinsurers.splice(index, 1); syncCaseClauses() } }
  function addSumInsured() { draft.sumInsured.push({ clientKey: clientKey(), category: '', amount: null, locationIndex: 0 }) }
  function removeSumInsured(index) { if (draft.sumInsured.length > 1) draft.sumInsured.splice(index, 1) }

  function masterOptions(type, currentValue = '') {
    const options = mdmRecords.value
      .filter((row) => row.entityType === type && row.isActive)
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name, 'en'))
    const current = String(currentValue || '').trim()
    if (current && !options.some((row) => row.name === current)) {
      options.push({ id: `historical-${type}-${current}`, entityType: type, code: '', name: current, isActive: false, historical: true })
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
  }

  function syncCaseClauses() {
    const details = UNIVERSAL_CLAUSES.map((row) => ({ ...row }))
    draft.reinsurers.forEach((line) => {
      const master = mdmRecords.value.find((row) => row.entityType === 'reinsurer' && row.name === line.name)
      normalizeClauseList(master?.payload?.fixedClauses).forEach((row) => details.push(row))
    })
    normalizeClauseList(draft.manualClauses).forEach((row) => details.push(row))
    const unique = normalizeClauseList(details).sort(compareClauses)
    draft.clauseDetails = unique
    draft.clauses = unique.map((row) => row.code)
    const manualCodes = new Set(normalizeClauseList(draft.manualClauses).map((row) => row.code))
    draft.autoClauses = unique.filter((row) => !UNIVERSAL_CLAUSES.some((base) => base.code === row.code) && !manualCodes.has(row.code)).map((row) => row.code)
  }
  function onReinsurerSelected() {
    syncCaseClauses()
    if (allFacilityReinsurers.value) draft.sumInsured.forEach((row) => { row.locationIndex = 0 })
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
    const suffix = STRUCTURE_SUFFIX[draft.reinsuranceStructure] || ''
    const prefix = String(draft.typePrefix || '').trim()
    draft.type = suffix ? (prefix ? `${prefix} ${suffix}` : suffix) : prefix
  }

  function onStructureSelected() {
    if (draft.reinsuranceStructure === 'QS') draft.underlyingLimits = ''
    recomputeType()
  }

  async function loadMasterData() {
    try {
      const response = await apiFetch('/api/master-data', { headers: { Accept: 'application/json' } })
      const body = await response.json()
      if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
      mdmRecords.value = Array.isArray(body.records) ? body.records : []
    } catch (err) {
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
    fresh.situations = (Array.isArray(payload?.situations) && payload.situations.length ? payload.situations : fresh.situations)
      .map((row) => ({ ...row, clientKey: clientKey() }))
    fresh.reinsurers = (Array.isArray(payload?.reinsurers) && payload.reinsurers.length ? payload.reinsurers : fresh.reinsurers)
      .map((row) => ({ ...row, clientKey: clientKey() }))
    fresh.sumInsured = (Array.isArray(payload?.sumInsured) && payload.sumInsured.length ? payload.sumInsured : fresh.sumInsured)
      .map((row) => ({ ...row, clientKey: clientKey() }))
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
  }

  async function startEditCase(row) {
    // VM 修正：Alpha 這裡只允許 draft／posted，Reversed 案件的「Correct reversed case」因此沒有反應（#7 的確認流程走不到）
    if (!row?.caseUid || !['draft', 'posted', 'reversed'].includes(row.status)) return
    loading.value = true; shell.error = ''
    try {
      if (!mdmRecords.value.length) await loadMasterData()
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
      caseDetailTab.value = 'overview'
      caseDocuments.value = []
      documentCoverage.value = { offer: false, required: [], covered: [], missing: [], ready: false, selected: [] }
      signedSlipReminder.value = { complete: false, missing: [], eligibleStatus: false, daysSinceEffective: null, firstReminderOn: '', due: false, today: '', cadenceDays: 7, outboundEnabled: false }
      resetDocumentForm()
      caseWorkflow.value = null
      activeView.value = 'case-detail'
      await loadCaseWorkflow()
      window.scrollTo({ top: 0 })
    } catch (err) {
      shell.error = err instanceof Error ? err.message : String(err)
      ElMessage.error(shell.error)
    } finally { caseDetailLoading.value = false }
  }

  function editSelectedCase() {
    if (['draft', 'posted', 'reversed'].includes(selectedCase.value?.status)) startEditCase(selectedCase.value)
  }

  function collectPayloadAnnounceIssues(value) {
    const issues = []
    const add = (label) => issues.push(label)
    if (!Number.isInteger(Number(value?.ownerPersonnelId)) || Number(value.ownerPersonnelId) < 1) add('Case Owner');
    [
      ['reinsuranceStructure', 'Reinsurance structure'], ['ae', 'AE'], ['currency', 'Currency'],
      ['classOfBusiness', 'Class'], ['newOrRenew', 'New / Renew'], ['type', 'Type'],
      ['reinsured', 'Reinsured'], ['originalInsured', 'Original insured (EN)'],
      ['policyFrom', 'Effective date'], ['policyTo', 'Expiration date'], ['interest', 'Interest']
    ].forEach(([field, label]) => { if (!filled(value?.[field])) add(label) })
    if (filled(value?.parentTwRef)) {
      if (!filled(value?.endoEffectiveDate)) add('Endorsement effective date')
      if (!Array.isArray(value?.endoTypes) || !value.endoTypes.length) add('At least one endorsement type')
      if (!filled(value?.endoText)) add('Endorsement wording')
    }
    const situations = Array.isArray(value?.situations) ? value.situations : []
    if (!situations.length) add('Situation')
    situations.forEach((row, index) => {
      if (!filled(row?.address)) add(`Situation ${index + 1} Risk Address`)
      if (!/^\d{3,6}$/.test(String(row?.postcode || '').trim())) add(`Situation ${index + 1} Postcode`)
    })
    const reinsurers = Array.isArray(value?.reinsurers) ? value.reinsurers : []
    if (!reinsurers.length) add('Schedule of Security')
    reinsurers.forEach((row, index) => {
      if (!filled(row?.name)) add(`Reinsurer ${index + 1}`)
      if (!filled(row?.sharePct)) add(`Reinsurer ${index + 1} Order hereon`)
      if (!filled(row?.premium)) add(`Reinsurer ${index + 1} Premium`)
      if (!filled(row?.riCommPct)) add(`Reinsurer ${index + 1} Deductions`)
      if (!filled(row?.taxPct)) add(`Reinsurer ${index + 1} Tax`)
    });
    [['limitOfLiability', 'Limit of Liability'], ['deductibles', 'Deductibles'], ['originalConditions', 'Original Conditions'], ['occupation', 'Occupation'], ['construction', 'Construction']]
      .forEach(([field, label]) => { if (!filled(value?.[field])) add(label) })
    if (value?.basisOfValuation === 'Other' && !filled(value?.basisOfValuationOther)) add('Basis of Valuation — Other')
    const sumInsured = Array.isArray(value?.sumInsured) ? value.sumInsured : []
    if (!sumInsured.length) add('Breakdown of Sum Insured')
    sumInsured.forEach((row, index) => {
      if (!filled(row?.category)) add(`Sum insured ${index + 1} Interest insured`)
      if (!filled(row?.amount)) add(`Sum insured ${index + 1} Amount`)
    })
    if (!filled(value?.lossAdvisedDate)) add('Loss record advised by broker on')
    if (!Number.isInteger(Number(value?.lossRecordYears)) || Number(value?.lossRecordYears) <= 0) add('Loss history years');
    (Array.isArray(value?.lossRecord) ? value.lossRecord : []).forEach((row, index) => {
      if (!filled(row?.date)) add(`Loss ${index + 1} Date of Loss`)
      if (!filled(row?.cause)) add(`Loss ${index + 1} Cause`)
      if (!filled(row?.lossPaid)) add(`Loss ${index + 1} Loss Paid`)
    });
    [['originalPremium', '100% Premium'], ['paymentTermsDays', 'Payment terms'], ['riCommPct', 'Ceding commission'], ['taxPct', 'Cedant tax']]
      .forEach(([field, label]) => { if (!filled(value?.[field])) add(label) })
    if (value?.installmentEnabled) {
      const installmentResult = installmentValidationFor(value)
      if (!installmentResult.valid) add(installmentResult.message)
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

  function fieldInvalid(key, validator) {
    if (!reviewAttempted.value) return false
    const value = draft[key]
    if (Array.isArray(value)) return value.length === 0
    if (validator === 'positiveInteger') return !validPositiveInteger(value)
    return !filled(value)
  }

  function rowInvalid(listName, index, key, validator) {
    if (!reviewAttempted.value) return false
    const row = draft[listName] && draft[listName][index]
    const value = row && row[key]
    if (validator === 'postcode') return !validPostcode(value)
    return !filled(value)
  }

  function collectRequiredIssues() {
    const issues = []
    const add = (section, label) => issues.push({ section, label });
    [
      ['reinsuranceStructure', 'Reinsurance structure'], ['ae', 'AE'], ['currency', 'Currency'],
      ['classOfBusiness', 'Class'], ['newOrRenew', 'New / Renew'], ['type', 'Type'],
      ['reinsured', 'Reinsured'], ['originalInsured', 'Original insured (EN)'],
      ['policyFrom', 'Effective date'], ['policyTo', 'Expiration date'], ['interest', 'Interest']
    ].forEach(([key, label]) => { if (!filled(draft[key])) add('risk', label) })
    if (draft.parentTwRef) {
      if (!filled(draft.endoEffectiveDate)) add('risk', 'Endorsement effective date')
      if (!Array.isArray(draft.endoTypes) || !draft.endoTypes.length) add('risk', 'At least one endorsement type')
      if (!filled(draft.endoText)) add('risk', 'Endorsement wording')
    }
    if (!draft.situations.length) add('risk', 'Situation')
    draft.situations.forEach((row, index) => {
      if (!filled(row.address)) add('risk', `Situation ${index + 1} Risk Address`)
      if (!validPostcode(row.postcode)) add('risk', `Situation ${index + 1} Postcode`)
    })

    if (!draft.reinsurers.length) add('security', 'Schedule of Security')
    draft.reinsurers.forEach((row, index) => {
      if (!filled(row.name)) add('security', `Reinsurer ${index + 1}`)
      if (!filled(row.sharePct)) add('security', `Reinsurer ${index + 1} Order hereon`)
    })

    if (!filled(draft.limitOfLiability)) add('terms', 'Limit of Liability')
    if (!filled(draft.deductibles)) add('terms', 'Deductibles')
    if (!filled(draft.originalConditions)) add('terms', 'Original Conditions')
    if (draft.basisOfValuation === 'Other' && !filled(draft.basisOfValuationOther)) add('terms', 'Basis of Valuation — Other')
    if (!filled(draft.occupation)) add('occupation', 'Occupation')
    if (!filled(draft.construction)) add('occupation', 'Construction')

    if (!draft.sumInsured.length) add('sumInsured', 'Breakdown of Sum Insured')
    draft.sumInsured.forEach((row, index) => {
      if (!filled(row.category)) add('sumInsured', `Sum insured ${index + 1} Interest insured`)
      if (!filled(row.amount)) add('sumInsured', `Sum insured ${index + 1} Amount`)
    })
    if (!filled(draft.lossAdvisedDate)) add('loss', 'Loss record advised by broker on')
    if (!validPositiveInteger(draft.lossRecordYears)) add('loss', 'Loss history years')
    draft.lossRecord.forEach((row, index) => {
      if (!filled(row.date)) add('loss', `Loss ${index + 1} Date of Loss`)
      if (!filled(row.cause)) add('loss', `Loss ${index + 1} Cause`)
      if (!filled(row.lossPaid)) add('loss', `Loss ${index + 1} Loss Paid`)
    });

    [
      ['originalPremium', '100% Premium'], ['paymentTermsDays', 'Payment terms'],
      ['riCommPct', 'Ceding commission'], ['taxPct', 'Cedant tax']
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
    const value = JSON.parse(JSON.stringify(draft))
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

  return {
    can, activeView, currentHeader, loading, saving, saveMessage,
    filters, filteredCases, draft, openSections, startNewCase, cancelNewCase,
    recycleSaving, recycleDraft,
    addSituation, removeSituation, addReinsurer, removeReinsurer, addSumInsured, removeSumInsured,
    isEditing, isEndorsementDraft, editingRowVersion, editingOriginalStatus, endorsementFieldsUnlocked, startEditCase, startViewCase,
    casePreviewVisible, casePreview, openCasePreview, openPreviewFullCase, formatPolicyDateTime, formatPolicyPeriod,
    selectedCase, selectedPayload, selectedOverview, selectedCaseTransactions, caseDetailLoading, caseDetailTab, caseDetailTabLabel, backToCases, editSelectedCase,
    caseWorkflow, workflowLoading, workflowSaving, loadCaseWorkflow, createEndorsement, createRenewal, reverseSelectedCase, viewWorkflowCase,
    accountingDialogVisible, accountingForm, openAccountingNotification, saveAccountingNotification,
    claimsLoading, claimsSaving, claimsState, claimForm, paymentDialogVisible, paymentForm, createClaim, updateClaimReserve, openClaimPayment, recordClaimPayment, claimTotalPaid, loadClaims,
    documentsLoading, documentsSaving, documentGenerating, caseDocuments, documentCoverage, signedSlipReminder, documentForm, documentFileList, selectedReinsurers, documentReadinessText, selectedAnnounceIssues,
    downloadGeneratedDocument, loadCaseDocuments, onCaseDetailTabChange, onDocumentKindChange, onDocumentFileChange, onDocumentFileRemove, uploadCaseDocument,
    toggleDocumentSelection, downloadCaseDocument, deleteCaseDocument, documentKindLabel, displayReinsurerName, formatFileSize, formatDateTime,
    announceDialogVisible, announceConfirmed, announcing, openAnnounceReview, announceSelectedCase,
    personnelRecords, onOwnerSelected, departmentLabel,
    masterOptions, onClassSelected, structureLabel, recomputeType, onStructureSelected, onReinsurerSelected,
    caseClauseDraft, addCaseClause, removeCaseClause, isManualClause, clauseSourceLabel,
    reviewAttempted, reviewReady, validationMessage, fieldInvalid, rowInvalid, reviewAndConfirm,
    reviewDialogVisible, totalOrderHereon, totalSumInsured, allFacilityReinsurers, hasNonFacilityReinsurer, lossRecordSummary, installmentAllocations, installmentStatus,
    addInstallment, removeInstallment, onInstallmentToggle, installmentRowInvalid,
    splitStatus, onSplitToggle, splitPartyInvalid, splitPersonOptions, onSplitPersonSelected,
    formatAmount, formatMoney, formatCurrency, saveReviewedDraft,
    addLossRecord, removeLossRecord, lossRowInvalid,
    statusLabel, loadData, saveDraft
  }
}
