"""
從 Alpha 的 index.html（alpha-reference/，雜湊已核對）按行號切出案件工作區的模板，產生 src/views/CaseWorkspace.vue。
每一處替換都寫在 REPLACEMENTS，並要求「剛好出現指定次數」，Alpha 改版時不會悄悄失效。

  python3 scripts/build_case_workspace.py
"""
import hashlib
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "alpha-reference" / "index.html"
TARGET = ROOT / "src" / "views" / "CaseWorkspace.vue"
EXPECTED_SHA256 = "c1872c843dca201e51340042807ce6563c77caf43f675d7e823d77371cbb385d"

text = SOURCE.read_text(encoding="utf-8")
assert hashlib.sha256(text.encode()).hexdigest() == EXPECTED_SHA256, "alpha-reference/index.html 與記錄的 Alpha v63 不同"
lines = text.split("\n")


def span(first, last, starts_with, ends_with):
    """第 first～last 行（含），並核對頭尾內容，行號錯了立刻失敗。"""
    chunk = lines[first - 1:last]
    assert chunk[0].strip().startswith(starts_with), (first, chunk[0][:80])
    assert chunk[-1].strip().startswith(ends_with), (last, chunk[-1][:80])
    return chunk


header_actions = span(50, 59, '<div v-else-if="activeView === \'case-create\'"', "</div>")
cases = span(151, 196, "<template v-else-if=\"activeView === 'cases'\">", "</template>")
detail = span(217, 630, "<template v-else-if=\"activeView === 'case-detail'\">", "</template>")
create = span(632, 864, "<template v-else-if=\"activeView === 'case-create'\">", "</template>")

body = "\n".join(["<template>", "  <Teleport defer to=\"#page-header-actions\">"]
                 + [l.replace('v-else-if="activeView === \'case-create\'"', 'v-if="activeView === \'case-create\'"', 1) if i == 0 else l
                    for i, l in enumerate(header_actions)]
                 + ["  </Teleport>", ""]
                 + [cases[0].replace('v-else-if="activeView', 'v-if="activeView', 1)] + cases[1:]
                 + [""] + detail + create + ["</template>", ""])

REMINDERS_TAB = """<template v-else-if="caseDetailTab === 'reminders' && selectedCase">
                <div class="overview-stack" v-loading="remindersLoading">
                  <section class="overview-card">
                    <div class="section-heading">
                      <div><span class="pending-badge">Automated reminders</span><h2>Reminders — {{ selectedCase.twRef || 'Draft' }}</h2><p>Signed Slip reminders run every day at 09:00 and payment reminders at 09:30 (Taiwan time) for Announced and Confirmed cases.</p></div>
                      <el-button class="secondary-button" :loading="remindersLoading" @click="loadCaseReminders">Refresh</el-button>
                    </div>
                    <el-alert v-if="caseReminders && !caseReminders.emailEnabled" type="warning" :closable="false" show-icon title="Reminder e-mail is not enabled on the VM" description="Reminders are still generated on schedule and recorded as Suppressed; no e-mail is sent. The preview shows exactly what would be sent."></el-alert>
                  </section>
                  <section class="overview-card">
                    <div class="section-heading"><div><h2>Signed Slip reminders</h2><p>Sent to the AE and the AE's supervisor while Reinsurer Signed Slips remain missing (from day 60, then every 7 days).</p></div></div>
                    <div class="overview-table-wrap">
                      <el-table :data="caseReminders ? caseReminders.signedSlip : []" row-key="id" empty-text="No Signed Slip reminders for this case.">
                        <el-table-column prop="alertOn" label="Date" width="120"></el-table-column>
                        <el-table-column label="Status" width="170"><template #default="{ row }"><el-tag :type="reminderStatusType(row.status)" effect="plain">{{ reminderStatusLabel(row.status) }}</el-tag></template></el-table-column>
                        <el-table-column label="Missing Signed Slips" min-width="220"><template #default="{ row }">{{ (row.missingReinsurers || []).join(', ') || '—' }}</template></el-table-column>
                        <el-table-column label="Recipients" min-width="260"><template #default="{ row }">{{ (row.recipients || []).join(', ') }}</template></el-table-column>
                        <el-table-column label="" width="110" align="right"><template #default="{ row }"><el-button link type="primary" @click="openReminderPreview(row)">Preview</el-button></template></el-table-column>
                      </el-table>
                    </div>
                  </section>
                  <section class="overview-card">
                    <div class="section-heading"><div><h2>Payment reminders</h2><p>Sent to the AE, the AE's supervisor and Finance: 7 days before the due date, on the due date, then weekly while overdue.</p></div></div>
                    <div class="overview-table-wrap">
                      <el-table :data="caseReminders ? caseReminders.payment : []" row-key="id" empty-text="No payment reminders for this case.">
                        <el-table-column prop="alertDate" label="Date" width="120"></el-table-column>
                        <el-table-column prop="alertLabel" label="Reminder" width="140"></el-table-column>
                        <el-table-column label="Status" width="170"><template #default="{ row }"><el-tag :type="reminderStatusType(row.status)" effect="plain">{{ reminderStatusLabel(row.status) }}</el-tag></template></el-table-column>
                        <el-table-column label="Recipients" min-width="300"><template #default="{ row }">{{ (row.recipients || []).join(', ') }}</template></el-table-column>
                        <el-table-column label="" width="110" align="right"><template #default="{ row }"><el-button link type="primary" @click="openReminderPreview(row)">Preview</el-button></template></el-table-column>
                      </el-table>
                    </div>
                  </section>
                  <section class="overview-card">
                    <div class="section-heading"><div><h2>Configuration errors</h2><p>A reminder was due but nothing was sent because contact details are incomplete (AE, supervisor or Finance e-mail). Fix them in Personnel &amp; Accounts.</p></div></div>
                    <div class="overview-table-wrap">
                      <el-table :data="caseReminders ? caseReminders.configurationErrors : []" empty-text="No configuration errors.">
                        <el-table-column prop="alertDate" label="Date" width="120"></el-table-column>
                        <el-table-column label="Reminder" width="160"><template #default="{ row }">{{ row.reminder === 'payment' ? 'Payment' + (row.alertKind ? ' · ' + paymentReminderLabel(row.alertKind) : '') : 'Signed Slip' }}</template></el-table-column>
                        <el-table-column prop="error" label="Problem" min-width="360"></el-table-column>
                      </el-table>
                    </div>
                  </section>
                  <el-dialog v-model="reminderPreviewVisible" title="Reminder preview" width="760px" class="master-dialog">
                    <template v-if="reminderPreview">
                      <dl class="overview-kv" style="margin-bottom:12px;">
                        <dt>Subject</dt><dd>{{ reminderPreview.subject || '—' }}</dd>
                        <dt>Recipients</dt><dd>{{ (reminderPreview.recipients || []).join(', ') }}</dd>
                        <dt>Status</dt><dd>{{ reminderStatusLabel(reminderPreview.status) }}<span v-if="reminderPreview.error || reminderPreview.errorMessage"> · {{ reminderPreview.error || reminderPreview.errorMessage }}</span></dd>
                      </dl>
                      <iframe class="reminder-preview-frame" sandbox="" :srcdoc="reminderPreview.bodyHtml || ''" title="E-mail preview" style="width:100%;height:360px;border:1px solid var(--border-subtle, #ddd);border-radius:8px;background:#fff;"></iframe>
                    </template>
                  </el-dialog>
                </div>
              </template>
"""

REPLACEMENTS = [
    # 文件上限：VM 10 MB（Alpha 5 MB）
    ("Supported: PDF, DOCX, PNG, JPG, EML and MSG. Maximum 5 MB per file.", "Supported: PDF, DOCX, PNG, JPG, EML and MSG. Maximum 10 MB per file.", 1),
    # VM 已啟用 Audit（Alpha 是暫停中），如實描述
    ("Announce assigns the TW Reference. Audit recording will begin after migration to the VM.", "Announce assigns the TW Reference and is recorded in the Audit Log.", 1),
    # 提醒信（#9、#10）：VM 才有的 Reminders 分頁（2026-09-26 你的決定：放在案件明細）
    ('<el-tab-pane label="Endorsements" name="endorsements"></el-tab-pane>',
     '<el-tab-pane label="Endorsements" name="endorsements"></el-tab-pane>\n'
     '                <el-tab-pane label="Reminders" name="reminders"></el-tab-pane>', 1),
    ('<section v-else class="overview-card overview-empty">', REMINDERS_TAB + '\n              <section v-else class="overview-card overview-empty">', 1),
]
# Preserve prior VM transaction aliases and paused-audit wording when regenerating.
REPLACEMENTS += [
    ("Announce assigns the TW Reference and is recorded in the Audit Log.", "Announce assigns the TW Reference.", 1),
    ("{{ row.txNo }}", "{{ row.displayTxNo }}", 1),
    ('prop="label" label="Recipient"', 'prop="displayLabel" label="Recipient"', 1),
    ('prop="reinsurer" label="Reinsurer / R/I Broker" min-width="210"',
     'prop="displayParty" label="Reinsurer / R/I Broker / Cedant" min-width="240"', 1),
    ('v-model="draft.policyFrom" type="date"', 'v-model="draft.policyFrom" @change="onPolicyFromChange" type="date"', 1),
]
# Endorsement premium changes remain editable while copied risk fields stay locked.
REPLACEMENTS += [('<el-table-column prop="legType" label="Leg" width="120"></el-table-column>',
  '<el-table-column prop="legType" label="Leg" min-width="140"><template #default="{ row }">{{ row.legType '
  '}}<br><small>{{ row.paymentDirection }}</small></template></el-table-column>',
  1),
 ('<el-table-column prop="sourceLabel" label="Type" width="100">',
  '<el-table-column prop="sourceLabel" label="Type" min-width="130">',
  1),
 ('                <el-collapse-item name="cedantPremium" title="Cedant Premium">',
  '              </el-collapse>\n'
  '              </fieldset>\n'
  '              <el-collapse v-model="openSections">\n'
  '                <el-collapse-item name="cedantPremium" title="Cedant Premium">\n'
  '                  <p v-if="isEndorsementDraft" class="document-help">Enter this endorsement\'s premium change: '
  'positive for additional premium, negative for return premium. The original policy premium remains '
  'unchanged.</p>',
  1),
 ('                <el-collapse-item name="conditions" title="Reinsurance Conditions">',
  '              </el-collapse>\n'
  '              <fieldset class="case-fieldset" :disabled="isEndorsementDraft && !endorsementFieldsUnlocked">\n'
  '              <el-collapse v-model="openSections">\n'
  '                <el-collapse-item name="conditions" title="Reinsurance Conditions">',
  1)]
# Read-only roles can inspect notification history without recording notifications.
REPLACEMENTS += [('v-if="caseWorkflow?.actions?.canNotifyAccounting"',
                  'v-if="caseWorkflow?.actions?.canNotifyAccounting && can(\'cases.write\')"', 1)]
# The status of a draft must remain Draft when a reader has no Announce permission.
REPLACEMENTS += [('<span v-else class="status-badge status-posted">Announced</span>',
                  '<span v-else class="status-badge" :class="\'status-\' + selectedCase.status">{{ statusLabel(selectedCase.status) }}</span>', 1)]
for old, new, count in REPLACEMENTS:
    found = body.count(old)
    assert found == count, (old[:70], found, count)
    body = body.replace(old, new)

# Group only monetary inputs; keep percentage/day input constraints unchanged.
MONEY_INPUTS = {
    'claimForm.outstandingReserve': 1, 'claim.outstandingReserve': 1, 'paymentForm.amount': 1,
    'draft.limitOfLiability': 1, 'draft.aggregateLimit': 1, 'row.amount': 1,
    'row.lossPaid': 1, 'draft.originalPremium': 1, 'row.premium': 2,
}
for model, count in MONEY_INPUTS.items():
    pattern = r'<el-input-number\b[^>]*v-model="' + re.escape(model) + r'"[^>]*>'
    body, found = re.subn(pattern, lambda match: match.group().replace('<el-input-number',
        '<el-input-number :formatter="formatMoneyInput" :parser="parseMoneyInput"', 1), body)
    assert found == count, (model, found, count)

for model, count in {'draft.originalPremium': 1, 'row.premium': 2}.items():
    pattern = r'(<el-input-number\b[^>]*v-model="' + re.escape(model) + r'"[^>]*):min="0"'
    body, found = re.subn(pattern, r'\1:min="isEndorsementDraft ? undefined : 0"', body)
    assert found == count, (model, found, count)


# VM: additional manual TW Ref. for the specific 0609 AUW Facility.
MANUAL_REF_REPLACEMENTS = [('<el-form label-position="top" class="case-form" @submit.prevent>', '<el-form label-position="top" class="case-form" @submit.prevent>\n              <section v-if="hasManualTwRefReinsurer" class="overview-card" data-testid="manual-tw-ref-section">\n                <el-form-item label="TW Ref. (for AUW)" required :class="{ \'is-required-error\': fieldInvalid(\'manualTwRef\') }">\n                  <el-input v-model="draft.manualTwRef" :disabled="auwRefLocked" maxlength="160" placeholder="Enter additional TW Ref." data-testid="manual-tw-ref-input"></el-input>\n                  <p class="document-help">Enter TW Ref. (for AUW). Required before saving Draft and unique across cases. Pure AUW uses this as its only TW reference; mixed placements also receive an automatic reference.</p>\n                </el-form-item>\n              </section>'), ('<dt>Type</dt><dd>{{ selectedPayload.type', '<template v-if="requiresManualTwRef(selectedPayload)"><dt>TW Ref. (for AUW)</dt><dd>{{ selectedPayload.manualTwRef || \'—\' }}</dd></template>\n                        <dt>Type</dt><dd>{{ selectedPayload.type'), ('<el-table-column prop="twRef" label="TW Ref. No." min-width="145" sortable><template #default="{ row }"><span class="case-ref">{{ row.twRef || \'—\' }}</span></template></el-table-column>', '<el-table-column prop="twRef" label="TW Ref. No." min-width="145" sortable><template #default="{ row }"><span class="case-ref">{{ row.twRef || \'—\' }}</span></template></el-table-column>\n                <el-table-column prop="manualTwRef" label="TW Ref. (for AUW)" min-width="175"><template #default="{ row }">{{ row.manualTwRef || \'—\' }}</template></el-table-column>'), ('<div class="case-preview-item"><span>TW Ref. No.</span><strong>{{ casePreview.twRef || \'—\' }}</strong></div>', '<div class="case-preview-item"><span>TW Ref. No.</span><strong>{{ casePreview.twRef || \'—\' }}</strong></div>\n                <div v-if="casePreview.manualTwRef" class="case-preview-item"><span>TW Ref. (for AUW)</span><strong>{{ casePreview.manualTwRef }}</strong></div>'), ('<h3>Case summary</h3>', '<h3>Case summary</h3>\n                <p v-if="requiresManualTwRef(selectedPayload)">TW Ref. (for AUW): <strong>{{ selectedPayload.manualTwRef || \'—\' }}</strong></p>'), ('<h3>Schedule of security</h3><span>Total order:', '<h3>Schedule of security</h3><span v-if="hasManualTwRefReinsurer">TW Ref. (for AUW): {{ draft.manualTwRef }}</span><span>Total order:')]
for old, new in MANUAL_REF_REPLACEMENTS:
    assert body.count(old) == 1, (old[:100], body.count(old))
    body = body.replace(old, new)


# VM: display the automatic reference first, followed by the AUW reference.
COMBINED_REF_REPLACEMENTS = [('<el-table-column prop="twRef" label="TW Ref. No." min-width="145" sortable><template #default="{ row }"><span class="case-ref">{{ row.twRef || \'—\' }}</span></template></el-table-column>\n                <el-table-column prop="manualTwRef" label="TW Ref. (for AUW)" min-width="175"><template #default="{ row }">{{ row.manualTwRef || \'—\' }}</template></el-table-column>', '<el-table-column prop="twRef" label="TW Ref. No." min-width="300" sortable><template #default="{ row }"><span class="case-ref">{{ displayTwRef(row) }}</span></template></el-table-column>'), ('<div class="case-preview-item"><span>TW Ref. No.</span><strong>{{ casePreview.twRef || \'—\' }}</strong></div>\n                <div v-if="casePreview.manualTwRef" class="case-preview-item"><span>TW Ref. (for AUW)</span><strong>{{ casePreview.manualTwRef }}</strong></div>', '<div class="case-preview-item"><span>TW Ref. No.</span><strong>{{ displayTwRef(casePreview) }}</strong></div>'), ('<template v-if="requiresManualTwRef(selectedPayload)"><dt>TW Ref. (for AUW)</dt><dd>{{ selectedPayload.manualTwRef || \'—\' }}</dd></template>', '<dt>TW Ref.</dt><dd>{{ displayTwRef(selectedCase) }}</dd>')]
for old, new in COMBINED_REF_REPLACEMENTS:
    assert body.count(old) == 1, (old[:100], body.count(old))
    body = body.replace(old, new)
for old, new, count in [
    ("{{ selectedCase.twRef || 'DRAFT' }}", "{{ displayTwRef(selectedCase, 'DRAFT') }}", 2),
    ("{{ selectedCase.twRef || 'Draft' }}", "{{ displayTwRef(selectedCase, 'Draft') }}", 2),
    ("{{ selectedCase.twRef }}", "{{ displayTwRef(selectedCase) }}", 2),
    ("{{ row.twRef || 'Draft · not assigned' }}", "{{ displayTwRef(row, 'Draft · not assigned') }}", 1),
]:
    assert body.count(old) == count, (old, body.count(old), count)
    body = body.replace(old, new)

# VM: AUW Foreign RI Broker is always Howden and cannot be edited.
old = 'v-model="row.foreignBroker" filterable clearable'
assert body.count(old) == 1, body.count(old)
body = body.replace(old, 'v-model="row.foreignBroker" :disabled="isAuwReinsurer(row.name)" filterable clearable')
old = '</el-option></el-select></el-form-item>\n                      <el-form-item label="Reinsurer Ref.">'
assert body.count(old) == 1, body.count(old)
body = body.replace(old, '</el-option></el-select><small v-if="isAuwReinsurer(row.name)">AUW is bound to Howden Specialty Limited.</small></el-form-item>\n                      <el-form-item label="Reinsurer Ref.">')

# VM: AUW deductions default only when its row is selected; reinsurer tax remains zero.
old = '@change="onReinsurerSelected"'
assert body.count(old) == 1, body.count(old)
body = body.replace(old, '@change="onReinsurerSelected(row)"')
for model in ['row.taxPct']:
    old = 'v-model="' + model + '" :min="0"'
    assert body.count(old) == 1, (model, body.count(old))
    body = body.replace(old, 'v-model="' + model + '" :disabled="isAuwReinsurer(row.name)" :min="0"')

# AUW settlement terms are fixed; Cedant remains an editable case default.
old = 'label="Payment terms override (days)"'
assert body.count(old) == 1, body.count(old)
body = body.replace(old, ':label="isAuwReinsurer(row.name) ? \'AUW payment terms (days)\' : \'Payment terms override (days)\'"')
old = '<el-input-number v-model="row.paymentTermsDays" :min="15" :precision="0" :controls="false" placeholder="Use Case default"></el-input-number>'
assert body.count(old) == 2, body.count(old)
first = body.index(old)
body = body[:first] + body[first:].replace(old,
    '<el-input-number v-model="row.paymentTermsDays" :disabled="isAuwReinsurer(row.name)" :min="15" :precision="0" :controls="false" placeholder="Use Case default"></el-input-number><small v-if="isAuwReinsurer(row.name)">Month-end + 120 calendar days. Accounting date is 10 days earlier.</small>', 1)
old = '<el-input-number v-model="row.reinsurerPaymentTerms[\'r\' + (reinsurerIndex + 1)]" :min="15" :precision="0" :controls="false" placeholder="Use higher-level default"></el-input-number>'
assert body.count(old) == 1, body.count(old)
body = body.replace(old, '<el-input-number v-if="isAuwReinsurer(reinsurer.name)" :model-value="120" disabled :controls="false"></el-input-number><el-input-number v-else v-model="row.reinsurerPaymentTerms[\'r\' + (reinsurerIndex + 1)]" :min="15" :precision="0" :controls="false" placeholder="Use higher-level default"></el-input-number>')
old = 'Calendar days. Cedant due = Terms − 15; Reinsurer due = Terms − 10.'
assert body.count(old) == 1, body.count(old)
body = body.replace(old, 'Calendar days. Cedant accounting date is 15 days before collection. AUW payment is month-end + 120 days, with accounting 10 days earlier; other reinsurers use Terms − 10.')

script = """<script setup>
// 由 scripts/build_case_workspace.py 產生：模板按行號切自 Alpha public/index.html（v63）；請勿直接修改模板，
// 要改就改產生程式（或 Alpha 更新後重新產生）。邏輯在 case-workspace.script.js。
import { useCaseWorkspace } from './case-workspace.script'
import vSyncInputNumberAria from '../directives/syncInputNumberAria'
import { displayAccountExecutiveText } from '../alpha/format'

const {
%s
} = useCaseWorkspace()
</script>

"""
exported = """can, activeView, currentHeader, loading, saving, saveMessage,
displayTwRef, isAuwReinsurer, isPureAuwCase, requiresManualTwRef, hasManualTwRefReinsurer, filters, filteredCases, draft, openSections, startNewCase, cancelNewCase, onPolicyFromChange,
recycleSaving, recycleDraft,
addSituation, removeSituation, addReinsurer, removeReinsurer, addSumInsured, removeSumInsured,
isEditing, isEndorsementDraft, auwRefLocked, editingRowVersion, editingOriginalStatus, endorsementFieldsUnlocked, startEditCase, startViewCase,
casePreviewVisible, casePreview, openCasePreview, openPreviewFullCase, formatPolicyDateTime, formatPolicyPeriod,
selectedCase, selectedPayload, selectedSumInsuredIssues, selectedSumInsuredWarning, selectedOverview, selectedCaseTransactions, caseDetailLoading, caseDetailTab, caseDetailTabLabel, backToCases, editSelectedCase,
caseWorkflow, workflowLoading, workflowSaving, loadCaseWorkflow, createEndorsement, createRenewal, reverseSelectedCase, viewWorkflowCase,
accountingDialogVisible, accountingForm, openAccountingNotification, saveAccountingNotification,
claimsLoading, claimsSaving, claimsState, claimForm, paymentDialogVisible, paymentForm, createClaim, updateClaimReserve, openClaimPayment, recordClaimPayment, claimTotalPaid, loadClaims,
documentsLoading, documentsSaving, documentGenerating, generatedDocumentCase, isTreatyDocumentCase, missingDebitPaymentTerms, missingDebitInstallmentBaseDates, missingDebitInstallmentPaymentTerms, missingDebitInstallmentAllocation, invalidDebitInstallmentAllocation, caseDocuments, documentCoverage, signedSlipReminder, documentForm, documentFileList, selectedReinsurers, documentReadinessText, selectedAnnounceIssues,
downloadGeneratedDocument, loadCaseDocuments, onCaseDetailTabChange, onDocumentKindChange, onDocumentFileChange, onDocumentFileRemove, uploadCaseDocument,
toggleDocumentSelection, downloadCaseDocument, deleteCaseDocument, documentKindLabel, displayReinsurerName, formatFileSize, formatDateTime,
announceDialogVisible, announceConfirmed, announcing, openAnnounceReview, announceSelectedCase,
personnelRecords, onOwnerSelected, departmentLabel,
masterOptions, onClassSelected, structureLabel, recomputeType, onStructureSelected, onReinsurerSelected,
caseClauseDraft, addCaseClause, removeCaseClause, isManualClause, clauseSourceLabel,
reviewAttempted, reviewReady, validationMessage, fieldInvalid, rowInvalid, reviewAndConfirm,
reviewDialogVisible, totalOrderHereon, totalSumInsured, draftSumInsuredWarning, sumInsuredGroups, unassignedSumInsured, sumGroupInvalid, allFacilityReinsurers, hasNonFacilityReinsurer, lossRecordSummary, lossRecordYearsMin, installmentAllocations, installmentStatus,
addInstallment, removeInstallment, onInstallmentToggle, installmentRowInvalid,
splitStatus, onSplitToggle, splitPartyInvalid, splitPersonOptions, onSplitPersonSelected,
formatAmount, formatMoney, formatCurrency, formatMoneyInput, parseMoneyInput, saveReviewedDraft,
addLossRecord, removeLossRecord, lossRowInvalid,
statusLabel, loadData, saveDraft,
caseReminders, remindersLoading, loadCaseReminders, reminderPreview, reminderPreviewVisible, openReminderPreview, reminderStatusLabel, reminderStatusType, paymentReminderLabel"""
# AUW endorsement controls: every endorsement is single settlement and inherits Cedant days.
body = body.replace('v-model="draft.paymentTermsDays" :min="15"', 'v-model="draft.paymentTermsDays" :disabled="isEndorsementDraft" :min="15"')
body = body.replace('v-model="draft.installmentEnabled" inline-prompt', 'v-model="draft.installmentEnabled" :disabled="isEndorsementDraft" data-testid="premium-installments-toggle" inline-prompt')
body = body.replace('<div class="repeat-heading"><div><h3>Premium Installments</h3>', '<p v-if="isEndorsementDraft" class="document-help">Endorsements use one premium settlement. Cedant payment terms follow the original policy; the collection base date is the later of Announce and endorsement effective dates.</p><div class="repeat-heading"><div><h3>Premium Installments</h3>')


# Claim records create obligations; actual cash is recorded separately in Accounting.
assert body.count('Immediate accounting entry') == 1
body = body.replace('Immediate accounting entry', 'Claim receivable / payable')
assert body.count('Record claim payment') == 1
body = body.replace('Record claim payment', 'Record claim obligation')
assert body.count('This creates Claim Leg 1/2 transactions immediately. Recorded payments are not deleted; use an offsetting payment to correct an error.') == 1
body = body.replace('This creates Claim Leg 1/2 transactions immediately. Recorded payments are not deleted; use an offsetting payment to correct an error.', 'This creates Claim Leg 1/2 receivable and payable transactions. Record actual cash receipts and payments separately in Accounting. Correct an obligation with an offsetting entry; history is retained.')
assert body.count('>Add payment</el-button>') == 1
body = body.replace('>Add payment</el-button>', '>Add claim obligation</el-button>')
assert body.count('Cumulative Loss Paid') == 1
body = body.replace('Cumulative Loss Paid', 'Cumulative claim obligations')
assert body.count('No claim payments recorded.') == 1
body = body.replace('No claim payments recorded.', 'No claim obligations recorded.')
assert body.count('label="Payment date"') == 2
body = body.replace('label="Payment date"', 'label="Obligation date"')

assert body.count('@click="recordClaimPayment">Record payment') == 1
body = body.replace('@click="recordClaimPayment">Record payment', '@click="recordClaimPayment">Record obligation')

# Rename the case documentation tab while preserving its route and permissions.
assert body.count('label="Cover & Debit Note"') == 1
body = body.replace('label="Cover & Debit Note"', 'label="Documentation"')

# Overview shares evidence uploads and becomes the only entry point for Announce.
upload_match = re.search(r'                    <section v-if="can\(\'documents.write\'\)" class="overview-card document-upload-card">.*?                    </section>', body, re.S)
assert upload_match is not None
upload_card = upload_match.group(0)
assert body.count(upload_card) == 1
announce_match = re.search(r'                    <section class="overview-card">\n                      <h2>Review & Announce</h2>.*?                    </section>', body, re.S)
assert announce_match is not None
announce_card = announce_match.group(0)
assert body.count(announce_card) == 1
body = body.replace(announce_card, '')
announce_card = announce_card.replace('<section class="overview-card">', '<section class="overview-card" data-testid="overview-announce-card">', 1)
announce_card = announce_card.replace(':disabled="!documentCoverage.ready || selectedAnnounceIssues.length > 0 || documentsLoading"', ':disabled="!documentCoverage.ready || selectedAnnounceIssues.length > 0 || documentsLoading || documentsSaving"')
review_details = """
                      <el-alert :title="documentReadinessText" :type="documentCoverage.ready ? 'success' : 'warning'" :closable="false" show-icon></el-alert>
                      <el-alert v-if="selectedCase.status === 'draft' && selectedAnnounceIssues.length" class="case-readiness-alert" :title="`Complete ${selectedAnnounceIssues.length} required case fields before Announce.`" :description="selectedAnnounceIssues.join(', ')" type="warning" :closable="false" show-icon></el-alert>
                      <div class="document-summary">
                        <article><span>Offer Slip</span><strong>{{ documentCoverage.offer ? 'Available' : 'Missing' }}</strong></article>
                        <article><span>Reinsurer coverage</span><strong>{{ (documentCoverage.covered || []).length }} / {{ (documentCoverage.required || []).length }}</strong></article>
                        <article><span>Announce readiness</span><strong>{{ documentCoverage.ready ? 'Ready' : 'Not ready' }}</strong></article>
                      </div>
                      <div v-if="caseDocuments.some(file => file.is_selected)" class="review-list">
                        <div v-for="file in caseDocuments.filter(row => row.is_selected)" :key="'overview-evidence-' + file.id"><strong>{{ documentKindLabel(file.kind) }}</strong><span>{{ file.filename }}<template v-if="file.kind !== 'offer'"> · {{ (file.reinsurers || []).map(displayReinsurerName).join(', ') }}</template></span></div>
                      </div>
"""
announce_card = announce_card.replace('                      <el-button v-if="selectedCase.status', review_details + '                      <el-button v-if="selectedCase.status', 1)
actions = ('\n                <div v-if="can(\'documents.read\') &amp;&amp; (can(\'documents.write\') || can(\'cases.announce\'))" class="case-placement-actions" data-testid="overview-placement-actions" v-loading="documentsLoading">\n' + upload_card + '\n' + announce_card + '\n                </div>')
overview_start = '<template v-if="caseDetailTab === \'overview\' && selectedCase">'
assert body.count(overview_start) == 1
body = body.replace(overview_start, overview_start + actions, 1)
assert body.count('Upload evidence') == 4
body = body.replace('Upload evidence', 'Upload Evidence')
assert body.count('<h2>Review & Announce</h2>') == 1
assert body.count('@click="openAnnounceReview"') == 1

# Risk Details: Type spans two columns; editable text grows to display its full value.
old_type = '<el-form-item label="Type" required :class='
assert body.count(old_type) == 1
body = body.replace(old_type, '<el-form-item label="Type" class="risk-type-field" required :class=')
old_controls = '<div style="display:flex;width:100%;gap:6px;align-items:stretch;"><el-input v-model="draft.typePrefix" style="min-width:0;flex:1;" maxlength="120"'
assert body.count(old_controls) == 1
body = body.replace(old_controls, '<div class="risk-type-controls"><el-input v-model="draft.typePrefix" class="risk-type-prefix" type="textarea" :autosize="{ minRows: 1 }" maxlength="120"')
old_suffix = '<span style="flex:0 0 160px;display:flex;align-items:center;padding:6px 9px;border:1px solid var(--border);border-radius:8px;background:var(--surface-card);color:var(--muted);font-size:12px;line-height:1.25;">'
assert body.count(old_suffix) == 1
body = body.replace(old_suffix, '<span class="risk-type-suffix" style="display:flex;align-items:center;padding:6px 9px;border:1px solid var(--border);border-radius:8px;background:var(--surface-card);color:var(--muted);font-size:12px;line-height:1.25;">')

# The Chinese name is stored with the Case and shown in its overview, so let
# sales edit it beside the English name. Keep both policy dates on the next row.
insured_en = '                    <el-form-item label="Original insured (EN)" required :class="{ \'is-required-error\': fieldInvalid(\'originalInsured\') }"><el-input v-model="draft.originalInsured" maxlength="240"></el-input></el-form-item>'
assert body.count(insured_en) == 1, body.count(insured_en)
insured_cn = '                    <el-form-item label="Original insured (CN)"><el-input v-model="draft.originalInsuredCn" maxlength="240"></el-input></el-form-item>'
body = body.replace(insured_en, insured_en + '\n' + insured_cn, 1)
effective_date = '<el-form-item label="Effective date" required :class="{ \'is-required-error\': fieldInvalid(\'policyFrom\') }">'
assert body.count(effective_date) == 1, body.count(effective_date)
body = body.replace(effective_date, effective_date.replace('<el-form-item ', '<el-form-item class="risk-effective-date" ', 1), 1)
expiration_date = '<el-form-item label="Expiration date" required :class="{ \'is-required-error\': fieldInvalid(\'policyTo\') }">'
assert body.count(expiration_date) == 1, body.count(expiration_date)
body = body.replace(expiration_date, expiration_date.replace('<el-form-item ', '<el-form-item class="risk-expiration-date" ', 1), 1)

risk_type_style = """
<style scoped>
.case-placement-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
  margin-bottom: 18px;
}
.case-placement-actions > * { min-width: 0; }
@media (max-width: 980px) {
  .case-placement-actions { grid-template-columns: 1fr; }
}
.risk-type-field {
  grid-column: span 2;
  min-width: 0;
}
.risk-effective-date { grid-column: 1 / span 2; min-width: 0; }
.risk-expiration-date { grid-column: 3 / span 2; min-width: 0; }
@media (max-width: 1120px) {
  .risk-effective-date { grid-column: 1; }
  .risk-expiration-date { grid-column: 2; }
}
.risk-type-controls {
  display: flex;
  width: 100%;
  gap: 6px;
  align-items: stretch;
}
.risk-type-prefix {
  flex: 1;
  min-width: 0;
}
.risk-type-suffix {
  flex: 0 0 160px;
  min-width: 0;
  overflow-wrap: anywhere;
}
@media (max-width: 760px) {
  .risk-type-field { grid-column: span 1; }
  .risk-expiration-date { grid-column: 1; }
  .risk-type-controls { flex-direction: column; }
  .risk-type-suffix { flex: 0 0 auto; }
}
.sum-insured-group { border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 12px; }
.sum-location-heading { display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap; margin-bottom: 10px; }
.sum-location-heading span { color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
.sum-insured-group .sum-row { display: grid; grid-template-columns: 28px minmax(0, 1fr) minmax(150px, 240px) auto; gap: 8px; align-items: start; }
.pending-sum-items .sum-row { grid-template-columns: 28px minmax(0, 1fr) minmax(130px, 200px) minmax(180px, 1fr) auto; }
.pending-sum-items .el-alert { margin-bottom: 12px; }
.sum-location-error { color: var(--el-color-danger); }
.sum-insured-total { display: flex; justify-content: space-between; gap: 12px; padding: 8px 12px; }
.sum-review-group { width: 100%; }
.sum-review-group > div { display: flex; justify-content: space-between; gap: 12px; padding: 4px 0; }
@media (max-width: 780px) { .sum-insured-group .sum-row { grid-template-columns: 28px minmax(0, 1fr) auto; } .sum-insured-group .sum-row > .el-input-number, .pending-sum-items .sum-row > .el-select { grid-column: 2; width: 100%; } }
.sum-limit-warning { margin-top: 10px; margin-bottom: 10px; }
</style>
"""
# Pure AUW uses the manual primary reference; all existing evidence checks remain.
body = body.replace("After Announce, the case receives a TW Reference and can no longer be edited as a Draft.", "{{ isPureAuwCase(selectedPayload) ? 'After Announce, the entered AUW reference becomes the only primary TW Reference; no automatic reference is generated.' : 'After Announce, the case receives an automatic TW Reference and can no longer be edited as a Draft.' }}")

# Cover Note requires the primary TW Reference assigned by Announce, including
# pure AUW cases whose entered manual reference becomes primary at Announce.
cover_replacements = [
    ("(selectedCase.status === 'draft' ? 'Cover Note' : 'Cover + Debit Note')", "(!selectedCase.twRef ? 'Awaiting TW Reference' : 'Cover + Debit Note')"),
    ("{{ displayTwRef(selectedCase, 'DRAFT') }} · {{ selectedPayload.reinsuranceStructure || 'Property' }}", "{{ selectedCase.twRef || 'Awaiting TW Reference' }} · {{ selectedPayload.reinsuranceStructure || 'Property' }}"),
    (":disabled=\"Boolean(documentGenerating)\" @click=\"downloadGeneratedDocument('cover', 'docx')\"", ":disabled=\"Boolean(documentGenerating) || !selectedCase.twRef\" @click=\"downloadGeneratedDocument('cover', 'docx')\""),
    (":disabled=\"Boolean(documentGenerating)\" @click=\"downloadGeneratedDocument('cover', 'pdf')\"", ":disabled=\"Boolean(documentGenerating) || !selectedCase.twRef\" @click=\"downloadGeneratedDocument('cover', 'pdf')\""),
    ('Cover Note is available while the case is Draft. Debit Note becomes available after Announce assigns the TW Reference.', 'Cover Note and Debit Note are available after Announce assigns the TW Reference.'),
]
for old, new in cover_replacements:
    assert body.count(old) == 1, (old, body.count(old))
    body = body.replace(old, new)

# Reinsured is required for both formal documents. Show the missing field
# alongside the downloads; the shared click handler and APIs enforce it.
old = '                      <p class="document-help">{{ selectedPayload.parentTwRef ?'
assert body.count(old) == 1, body.count(old)
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; !String(selectedPayload.reinsured || \'\').trim()" type="warning" :closable="false" show-icon title="Complete Reinsured in the case before generating a Cover Note or Debit Note."></el-alert>\n' + old, 1)

# Original Insured is independently required; the Chinese-name field is not
# a substitute for the name printed on these documents.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; !String(selectedPayload.originalInsured || \'\').trim()" type="warning" :closable="false" show-icon title="Complete Original Insured in the case before generating a Cover Note or Debit Note."></el-alert>\n' + old, 1)

# Require the stored Type that both templates print.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; !String(selectedPayload.type || \'\').trim()" type="warning" :closable="false" show-icon title="Complete Type in the case before generating a Cover Note or Debit Note."></el-alert>\n' + old, 1)

# Both policy dates are required for formal Cover/Debit Word documents.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; (!String(selectedPayload.policyFrom || \'\').trim() || !String(selectedPayload.policyTo || \'\').trim())" type="warning" :closable="false" show-icon title="Complete the policy start and end dates in the case before generating a Cover Note or Debit Note."></el-alert>\n' + old, 1)

# The selected Case AE is required for every generated Word document.
body = body.replace(old, '                      <el-alert v-if="!String(selectedPayload.ae || \'\').trim()" type="warning" :closable="false" show-icon title="Select an AE in the case before generating a document."></el-alert>\n' + old, 1)

# Require a resolved AE Email, including the active Personnel fallback.
body = body.replace(old, '                      <el-alert v-if="String(selectedPayload.ae || \'\').trim() &amp;&amp; !String(generatedDocumentCase.aeEmail || \'\').trim()" type="warning" :closable="false" show-icon title="Complete the AE Email in the case or Personnel before generating a document."></el-alert>\n' + old, 1)

# Interest is required on Cover Note only.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; !String(selectedPayload.interest || \'\').trim()" type="warning" :closable="false" show-icon title="Complete Interest in the case before generating a Cover Note."></el-alert>\n' + old, 1)

# Require Limit of Liability on Cover Note; a numeric zero is present.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; !String(selectedPayload.limitOfLiability ?? \'\').trim()" type="warning" :closable="false" show-icon title="Complete Limit of Liability in the case before generating a Cover Note."></el-alert>\n' + old, 1)

# Non-QS Cover Notes require the underlying primary-layer terms.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; String(selectedPayload.reinsuranceStructure || \'\').trim() === \'XOL\' &amp;&amp; !String(selectedPayload.underlyingLimits || \'\').trim()" type="warning" :closable="false" show-icon title="Complete Underlying Limits in the case before generating a Cover Note."></el-alert>\n' + old, 1)

# Deductibles is required on QS/XOL Cover Notes only.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; [\'QS\', \'XOL\'].includes(String(selectedPayload.reinsuranceStructure || \'\').trim()) &amp;&amp; !String(selectedPayload.deductibles || \'\').trim()" type="warning" :closable="false" show-icon title="Complete Deductibles in the case before generating a Cover Note."></el-alert>\n' + old, 1)

# Reinsured’s Retention is required on QS/XOL Cover Notes only.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; [\'QS\', \'XOL\'].includes(String(selectedPayload.reinsuranceStructure || \'\').trim()) &amp;&amp; !String(selectedPayload.reinsuredRetention || \'\').trim()" type="warning" :closable="false" show-icon title="Complete Reinsured’s Retention in the case before generating a Cover Note."></el-alert>\n' + old, 1)

# Every QS/XOL Cover Note Situation requires a saved Risk Address.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; [\'QS\', \'XOL\'].includes(String(selectedPayload.reinsuranceStructure || \'\').trim()) &amp;&amp; (!Array.isArray(selectedPayload.situations) || !selectedPayload.situations.length || selectedPayload.situations.some(row =&gt; !String(row?.address || \'\').trim()))" type="warning" :closable="false" show-icon title="Complete Risk Address for every Situation in the case before generating a Cover Note."></el-alert>\n' + old, 1)

# QS/XOL Cover Note postcodes follow the existing 3–6 digit Case rule.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; [\'QS\', \'XOL\'].includes(String(selectedPayload.reinsuranceStructure || \'\').trim()) &amp;&amp; (!Array.isArray(selectedPayload.situations) || !selectedPayload.situations.length || selectedPayload.situations.some(row =&gt; !/^[0-9]{3,6}$/.test(String(row?.postcode ?? \'\').trim())))" type="warning" :closable="false" show-icon title="Complete a 3–6 digit Postcode for every Situation in the case before generating a Cover Note."></el-alert>\n' + old, 1)

# Blank 100% Premium blocks QS/XOL Cover/Debit; zero remains valid.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; [\'QS\', \'XOL\'].includes(String(selectedPayload.reinsuranceStructure || \'\').trim()) &amp;&amp; !String(selectedPayload.originalPremium ?? \'\').trim()" type="warning" :closable="false" show-icon title="Complete 100% Premium in the case before generating a Cover Note or Debit Note."></el-alert>\n' + old, 1)

# Every QS/XOL Cover/Debit requires at least one saved Reinsurer share.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; [\'QS\', \'XOL\'].includes(String(selectedPayload.reinsuranceStructure || \'\').trim()) &amp;&amp; (!Array.isArray(selectedPayload.reinsurers) || !selectedPayload.reinsurers.length || selectedPayload.reinsurers.some(row =&gt; !String(row?.sharePct ?? \'\').trim()))" type="warning" :closable="false" show-icon title="Add at least one Reinsurer and complete Order hereon for every Reinsurer in the case before generating a Cover Note or Debit Note."></el-alert>\n' + old, 1)

# Every QS/XOL Cover Note Sum Insured entry requires a saved name.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; [\'QS\', \'XOL\'].includes(String(selectedPayload.reinsuranceStructure || \'\').trim()) &amp;&amp; (!Array.isArray(selectedPayload.sumInsured) || !selectedPayload.sumInsured.length || selectedPayload.sumInsured.some(row =&gt; !String(row?.category ?? \'\').trim()))" type="warning" :closable="false" show-icon title="Add at least one Sum Insured entry and complete Interest insured for every entry before generating a Cover Note."></el-alert>\n' + old, 1)

# QS/XOL Cover Note requires every Sum Insured amount to be positive.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; [\'QS\', \'XOL\'].includes(String(selectedPayload.reinsuranceStructure || \'\').trim()) &amp;&amp; (!Array.isArray(selectedPayload.sumInsured) || !selectedPayload.sumInsured.length || selectedPayload.sumInsured.some(row =&gt; !Number.isFinite(Number(row?.amount)) || Number(row?.amount) &lt;= 0))" type="warning" :closable="false" show-icon title="Enter an Amount greater than 0 for every Sum Insured entry before generating a Cover Note."></el-alert>\n' + old, 1)

body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; [\'QS\', \'XOL\'].includes(String(selectedPayload.reinsuranceStructure || \'\').trim()) &amp;&amp; selectedSumInsuredIssues.some(issue =&gt; issue.kind === \'location\')" type="warning" :closable="false" show-icon title="Assign every Sum Insured entry to a valid Location and add at least one entry for every Location before generating a Cover Note."></el-alert>\n                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; [\'QS\', \'XOL\'].includes(String(selectedPayload.reinsuranceStructure || \'\').trim()) &amp;&amp; selectedSumInsuredIssues.some(issue =&gt; issue.kind === \'duplicate\')" type="warning" :closable="false" show-icon title="Use unique Interest insured names within each Location or the Facility items before generating a Cover Note."></el-alert>\n' + old, 1)

# QS/XOL Cover Note requires the saved Loss Record advised date.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; [\'QS\', \'XOL\'].includes(String(selectedPayload.reinsuranceStructure || \'\').trim()) &amp;&amp; !String(selectedPayload.lossAdvisedDate ?? \'\').trim()" type="warning" :closable="false" show-icon title="Complete the Loss Record advised date in the case before generating a Cover Note."></el-alert>\n' + old, 1)

# QS/XOL Cover Note requires saved history years; numerical zero is present.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; [\'QS\', \'XOL\'].includes(String(selectedPayload.reinsuranceStructure || \'\').trim()) &amp;&amp; !String(selectedPayload.lossRecordYears ?? \'\').trim()" type="warning" :closable="false" show-icon title="Complete Past year(s) in the Loss Record section of the case before generating a Cover Note."></el-alert>\n' + old, 1)

# Existing QS/XOL loss entries require a saved date; clean histories stay valid.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; [\'QS\', \'XOL\'].includes(String(selectedPayload.reinsuranceStructure || \'\').trim()) &amp;&amp; Array.isArray(selectedPayload.lossRecord) &amp;&amp; selectedPayload.lossRecord.some(row =&gt; !String(row?.date ?? \'\').trim())" type="warning" :closable="false" show-icon title="Complete Date of Loss for every Loss Record entry in the case before generating a Cover Note."></el-alert>\n' + old, 1)

# Existing QS/XOL loss entries require a saved cause; clean histories stay valid.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; [\'QS\', \'XOL\'].includes(String(selectedPayload.reinsuranceStructure || \'\').trim()) &amp;&amp; Array.isArray(selectedPayload.lossRecord) &amp;&amp; selectedPayload.lossRecord.some(row =&gt; !String(row?.cause ?? \'\').trim())" type="warning" :closable="false" show-icon title="Complete Cause for every Loss Record entry in the case before generating a Cover Note."></el-alert>\n' + old, 1)

# Existing QS/XOL loss entries require a saved Loss Paid; zero and clean histories stay valid.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; [\'QS\', \'XOL\'].includes(String(selectedPayload.reinsuranceStructure || \'\').trim()) &amp;&amp; Array.isArray(selectedPayload.lossRecord) &amp;&amp; selectedPayload.lossRecord.some(row =&gt; !String(row?.lossPaid ?? \'\').trim())" type="warning" :closable="false" show-icon title="Complete Loss Paid for every Loss Record entry in the case before generating a Cover Note."></el-alert>\n' + old, 1)

# Cover Notes use each saved Reinsurer name, never the Foreign RI Broker.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; [\'QS\', \'XOL\'].includes(String(selectedPayload.reinsuranceStructure || \'\').trim()) &amp;&amp; Array.isArray(selectedPayload.reinsurers) &amp;&amp; selectedPayload.reinsurers.some(row =&gt; !String(row?.name ?? \'\').trim())" type="warning" :closable="false" show-icon title="Complete the Reinsurer name for every Schedule of Security entry in the case before generating a Cover Note."></el-alert>\n' + old, 1)

# Every non-installment Debit Note reinsurer needs an effective payment term.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; missingDebitPaymentTerms(selectedPayload)" type="warning" :closable="false" show-icon title="Complete valid Payment Terms Days (an integer of at least 15) for every Reinsurer, using the Case default when needed, before generating a Debit Note."></el-alert>\n' + old, 1)

# Installment Debit Notes require an actual date in every saved row.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; missingDebitInstallmentBaseDates(selectedPayload)" type="warning" :closable="false" show-icon title="Add at least one installment and complete a valid Payment Base Date for every installment before generating a Debit Note."></el-alert>\n' + old, 1)

# Each installment/reinsurer pair must resolve a valid payment term.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; missingDebitInstallmentPaymentTerms(selectedPayload)" type="warning" :closable="false" show-icon title="Complete valid Payment Terms Days (an integer of at least 15) for every Reinsurer in every installment before generating a Debit Note."></el-alert>\n' + old, 1)

# Every installment must have a saved Premium or Ratio allocation.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; missingDebitInstallmentAllocation(selectedPayload)" type="warning" :closable="false" show-icon title="Complete Premium or Ratio for every installment before generating a Debit Note."></el-alert>\n' + old, 1)

# Each effective Word allocation weight must be finite and positive.
body = body.replace(old, '                      <el-alert v-if="!selectedPayload.parentTwRef &amp;&amp; !missingDebitInstallmentAllocation(selectedPayload) &amp;&amp; invalidDebitInstallmentAllocation(selectedPayload)" type="warning" :closable="false" show-icon title="Use a Premium or Ratio greater than 0 for every installment before generating a Debit Note."></el-alert>\n' + old, 1)

# Treaty documents temporarily bypass business-field requirements.
body = re.sub(r'(<el-alert v-if=")([^"\n]+)("[^\n]*title="(?:Complete|Select|Add|Enter|Assign|Use)[^"\n]+(?:generating)[^"\n]+")', r'\1!isTreatyDocumentCase &amp;&amp; (\2)\3', body)
body = body.replace(':disabled="Boolean(documentGenerating) || !selectedCase.twRef"', ':disabled="Boolean(documentGenerating) || (!isTreatyDocumentCase &amp;&amp; !selectedCase.twRef)"')
body = body.replace('v-if="!selectedPayload.parentTwRef && selectedCase.status !== \'draft\'"', 'v-if="!selectedPayload.parentTwRef &amp;&amp; (isTreatyDocumentCase || selectedCase.status !== \'draft\')"')
body = body.replace("(!selectedCase.twRef ? 'Awaiting TW Reference' : 'Cover + Debit Note')", "(isTreatyDocumentCase ? 'Cover + Debit Note' : (!selectedCase.twRef ? 'Awaiting TW Reference' : 'Cover + Debit Note'))")
body = body.replace("{{ selectedCase.twRef || 'Awaiting TW Reference' }}", "{{ selectedCase.twRef || (isTreatyDocumentCase ? 'DRAFT' : 'Awaiting TW Reference') }}")

# All generated documents use Word; uploaded placement evidence keeps its formats.
for kind in ('cover', 'debit'):
    pattern = r'^.*<el-button[^\n]*downloadGeneratedDocument\(\'' + kind + r'\', \'pdf\'\)[^\n]*\n'
    body, count = re.subn(pattern, '', body, flags=re.MULTILINE)
    assert count == 1, (kind, count)
word_replacements = [
    ('Development-compatible templates and filenames', 'Download Word documents; export to PDF in Word if needed.'),
    ('Endorsement PDF', 'Endorsement Word'),
    ("documentGenerating === 'endorsement-pdf'", "documentGenerating === 'endorsement-docx'"),
    ("downloadGeneratedDocument('endorsement', 'pdf')\">Download PDF", "downloadGeneratedDocument('endorsement', 'docx')\">Download Word (.docx)"),
    ('Endorsement output follows Development behavior: PDF only.', 'Endorsement is available as a Word document. Export to PDF in Word if needed.'),
]
for previous, replacement in word_replacements:
    assert body.count(previous) == 1, (previous, body.count(previous))
    body = body.replace(previous, replacement)

treaty_help = "{{ selectedPayload.parentTwRef ? 'Endorsement is available as a Word document. Export to PDF in Word if needed.' : 'Cover Note and Debit Note are available after Announce assigns the TW Reference.' }}"
assert body.count(treaty_help) == 1
body = body.replace(treaty_help, "{{ isTreatyDocumentCase ? 'Treaty documents are available as Word files, including Draft cases.' : selectedPayload.parentTwRef ? 'Endorsement is available as a Word document. Export to PDF in Word if needed.' : 'Cover Note and Debit Note are available after Announce assigns the TW Reference.' }}")

# Case-level Ceding Commission is optional before Review and Announce.
commission_control = '<el-form-item label="Ceding commission (%)" required :class="{ \'is-required-error\': fieldInvalid(\'riCommPct\') }">'
assert body.count(commission_control) == 1
body = body.replace(commission_control, '<el-form-item label="Ceding commission (%)">', 1)

# Case-level Tax is optional; the New Case 1% default is retained.
tax_control = '<el-form-item label="Tax (%)" required :class="{ \'is-required-error\': fieldInvalid(\'taxPct\') }">'
assert body.count(tax_control) == 1
body = body.replace(tax_control, '<el-form-item label="Tax (%)">', 1)

# Highlight zero and invalid Sum Insured amounts on Review.
assert body.count("rowInvalid('sumInsured', index, 'amount')") == 1
body = body.replace("rowInvalid('sumInsured', index, 'amount')", "rowInvalid('sumInsured', index, 'amount', 'sumInsuredAmount')", 1)
body = body.replace('placeholder="Amount *"', 'placeholder="Amount > 0 *"', 1)

GROUP_TEMPLATE = '                <el-collapse-item name="sumInsured" title="Breakdown of Sum Insured">\n                  <section v-if="unassignedSumInsured.length" class="sum-insured-group pending-sum-items">\n                    <el-alert type="warning" :closable="false" show-icon title="Unassigned items" description="Assign every item to a Location. Split the amount between Locations when needed."></el-alert>\n                    <div v-for="item in unassignedSumInsured" :key="item.row.clientKey" class="repeat-row sum-row">\n                      <span class="row-number">{{ item.index + 1 }}.</span>\n                      <el-input v-model="item.row.category" class="required-control" :class="{ \'required-invalid\': rowInvalid(\'sumInsured\', item.index, \'category\') }" maxlength="240" placeholder="Interest insured *"></el-input>\n                      <el-input-number :formatter="formatMoneyInput" :parser="parseMoneyInput" v-model="item.row.amount" class="required-control" :class="{ \'required-invalid\': rowInvalid(\'sumInsured\', item.index, \'amount\', \'sumInsuredAmount\') }" :min="0" :controls="false" placeholder="Amount > 0 *"></el-input-number>\n                      <el-select v-model="item.row.locationIndex" class="required-control" :class="{ \'required-invalid\': rowInvalid(\'sumInsured\', item.index, \'locationIndex\', \'sumInsuredLocation\') }" placeholder="Assign Location"><el-option v-for="(situation,index) in draft.situations" :key="situation.clientKey" :label="\'Location \' + (index + 1) + (situation.address ? \' · \' + situation.address : \'\') + (situation.postcode ? \' · \' + situation.postcode : \'\')" :value="index"></el-option></el-select>\n                      <el-button text type="danger" :disabled="draft.sumInsured.length === 1" @click="removeSumInsured(item.index)">Remove</el-button>\n                    </div>\n                  </section>\n                  <section v-for="group in sumInsuredGroups" :key="group.key" class="sum-insured-group" :class="{ \'required-invalid\': !allFacilityReinsurers &amp;&amp; sumGroupInvalid(group.locationIndex) }">\n                    <div class="sum-location-heading"><strong>{{ group.label }}</strong><span v-if="!allFacilityReinsurers">{{ [group.address, group.postcode].filter(Boolean).join(\' · \') }}</span></div>\n                    <div v-for="(item,itemIndex) in group.rows" :key="item.row.clientKey" class="repeat-row sum-row">\n                      <span class="row-number">{{ itemIndex + 1 }}.</span>\n                      <el-input v-model="item.row.category" class="required-control" :class="{ \'required-invalid\': rowInvalid(\'sumInsured\', item.index, \'category\') }" maxlength="240" placeholder="Interest insured *"></el-input>\n                      <el-input-number :formatter="formatMoneyInput" :parser="parseMoneyInput" v-model="item.row.amount" class="required-control" :class="{ \'required-invalid\': rowInvalid(\'sumInsured\', item.index, \'amount\', \'sumInsuredAmount\') }" :min="0" :controls="false" placeholder="Amount > 0 *"></el-input-number>\n                      <el-button text type="danger" :disabled="draft.sumInsured.length === 1" @click="removeSumInsured(item.index)">Remove</el-button>\n                    </div>\n                    <p v-if="!allFacilityReinsurers &amp;&amp; sumGroupInvalid(group.locationIndex)" class="sum-location-error">Enter at least one item for this Location.</p>\n                    <el-button class="secondary-button" @click="addSumInsured(group.locationIndex)">+ Add item</el-button>\n                  </section>\n                  <div class="sum-insured-total"><strong>Total</strong><span>{{ draft.currency }} {{ formatAmount(totalSumInsured) }}</span></div>\n                </el-collapse-item>'
REVIEW_TEMPLATE = '<div class="review-list"><section v-for="group in sumInsuredGroups" :key="\'review-sum-\' + group.key" class="sum-review-group"><div class="sum-location-heading"><strong>{{ group.label }}</strong><span v-if="!allFacilityReinsurers">{{ [group.address, group.postcode].filter(Boolean).join(\' · \') }}</span></div><div v-for="item in group.rows" :key="item.row.clientKey"><strong>{{ item.row.category }}</strong><span>{{ draft.currency }} {{ formatAmount(item.row.amount) }}</span></div></section></div>'
# Group Sum Insured by Location in the Case form and review.
group_start = body.index('                <el-collapse-item name="sumInsured"')
group_end = body.index('                </el-collapse-item>', group_start) + len('                </el-collapse-item>')
body = body[:group_start] + GROUP_TEMPLATE + body[group_end:]
old_review = '<div class="review-list"><div v-for="(row,index) in draft.sumInsured" :key="\'review-sum-\' + row.clientKey"><strong>{{ row.category }}</strong><span>{{ draft.currency }} {{ formatAmount(row.amount) }}<template v-if="!allFacilityReinsurers"> · Situation {{ Number(row.locationIndex || 0) + 1 }}</template></span></div></div>'
assert body.count(old_review) == 1
body = body.replace(old_review, REVIEW_TEMPLATE, 1)

# Sum Insured vs Limit is advisory, independently of all required-field gates.
sum_total = '<div class="sum-insured-total"><strong>Total</strong><span>{{ draft.currency }} {{ formatAmount(totalSumInsured) }}</span></div>'
assert body.count(sum_total) == 1
body = body.replace(sum_total, sum_total + '\n                  ' + '<el-alert v-if="draftSumInsuredWarning" class="sum-limit-warning" type="warning" :closable="false" show-icon title="Total Sum Insured differs from Limit of Liability" :description="draftSumInsuredWarning.message"></el-alert>', 1)
sum_review = '<div class="review-section-heading"><h3>Sum insured & premium</h3><span>Total sum insured: {{ draft.currency }} {{ formatAmount(totalSumInsured) }}</span></div>'
assert body.count(sum_review) == 1
body = body.replace(sum_review, sum_review + '\n                ' + '<el-alert v-if="draftSumInsuredWarning" class="sum-limit-warning" type="warning" :closable="false" show-icon title="Total Sum Insured differs from Limit of Liability" :description="draftSumInsuredWarning.message"></el-alert>', 1)
announce_anchor = '<el-alert title="There is no second-person reviewer in Phase 1. Check the case and selected evidence carefully before continuing." type="warning" :closable="false" show-icon></el-alert>'
assert body.count(announce_anchor) == 1
body = body.replace(announce_anchor, announce_anchor + '\n              ' + '<el-alert v-if="selectedSumInsuredWarning" class="sum-limit-warning" type="warning" :closable="false" show-icon title="Total Sum Insured differs from Limit of Liability" :description="selectedSumInsuredWarning.message"></el-alert>', 1)
cover_anchor = '<strong>Cover Note</strong>'
cover_start = body.index(cover_anchor)
cover_end = body.index('<div class="generated-document-actions">', cover_start)
body = body[:cover_end] + '<el-alert v-if="!isTreatyDocumentCase &amp;&amp; !selectedPayload.parentTwRef &amp;&amp; [\'QS\', \'XOL\'].includes(String(selectedPayload.reinsuranceStructure || \'\').trim()) &amp;&amp; selectedSumInsuredWarning" class="sum-limit-warning" type="warning" :closable="false" show-icon title="Total Sum Insured differs from Limit of Liability" :description="selectedSumInsuredWarning.message"></el-alert>' + '\n                      ' + body[cover_end:]

# Keep reserve ARIA metadata aligned across claimsSaving transitions.
reserve_control = '<el-input-number :formatter="formatMoneyInput" :parser="parseMoneyInput" v-if="claimsState.actions?.canWrite && can(\'cases.write\')"'
assert body.count(reserve_control) == 1, body.count(reserve_control)
body = body.replace(reserve_control, '<el-input-number v-sync-input-number-aria' + reserve_control[len('<el-input-number'):], 1)

# Show the full role name in all Case screens. Keep API field names and the
# immutable Alpha reference unchanged.
old_problem = '<el-table-column prop="error" label="Problem" min-width="360"></el-table-column>'
assert body.count(old_problem) == 1, body.count(old_problem)
body = body.replace(old_problem, '<el-table-column label="Problem" min-width="360"><template #default="{ row }">{{ displayAccountExecutiveText(row.error) }}</template></el-table-column>', 1)
old_preview_error = '{{ reminderPreview.error || reminderPreview.errorMessage }}'
assert body.count(old_preview_error) == 1, body.count(old_preview_error)
body = body.replace(old_preview_error, '{{ displayAccountExecutiveText(reminderPreview.error || reminderPreview.errorMessage) }}', 1)
body = re.sub(r'\bAE\b', 'Account Executive', body)

# Match the existing New/renewal validation and preserve loss rows when years changes.
old = '<el-form-item label="Past year(s)" required :class="{ \'is-required-error\': fieldInvalid(\'lossRecordYears\', \'positiveInteger\') }"><el-input-number v-model="draft.lossRecordYears" :min="1" :precision="0" :controls="false"></el-input-number></el-form-item>'
new = '<el-form-item label="Past year(s)" required :class="{ \'is-required-error\': fieldInvalid(\'lossRecordYears\', \'lossRecordYears\') }"><el-input-number v-model="draft.lossRecordYears" :min="lossRecordYearsMin" :precision="0" :controls="false"></el-input-number><small>{{ lossRecordYearsMin === 0 ? \'New cases may use 0 only when no losses are recorded.\' : \'Renewal cases require at least 1 year.\' }}</small></el-form-item>'
assert body.count(old) == 1, body.count(old)
body = body.replace(old, new, 1)

# Additional loss notes remain optional and are printed on Cover Notes.
old = '<el-form-item label="Additional loss record notes"><el-input v-model="draft.lossRecordText" type="textarea" :rows="3" maxlength="5000" placeholder="Optional notes"></el-input></el-form-item>'
new = '<el-form-item label="Additional loss record notes"><el-input v-model="draft.lossRecordText" type="textarea" :rows="3" maxlength="5000" placeholder="Optional notes"></el-input><small>Included below Loss Record in the Cover Note when completed.</small></el-form-item>'
assert body.count(old) == 1, body.count(old)
body = body.replace(old, new, 1)


# Swiss Facility Property fixed dates and form bindings.
exported = exported.replace("reviewDialogVisible, totalOrderHereon,", "isSwissProperty, isSwissFacility, reviewDialogVisible, totalOrderHereon,", 1)
assert body.count('v-model="row.paymentTermsDays" :disabled="isAuwReinsurer(row.name)"') == 1
body = body.replace('v-model="row.paymentTermsDays" :disabled="isAuwReinsurer(row.name)"', 'v-model="row.paymentTermsDays" :disabled="isAuwReinsurer(row.name) || (isSwissProperty && isSwissFacility(row.name))"', 1)
assert body.count('<small v-if="isAuwReinsurer(row.name)">Month-end + 120 calendar days. Accounting date is 10 days earlier.</small>') == 1
body = body.replace('<small v-if="isAuwReinsurer(row.name)">Month-end + 120 calendar days. Accounting date is 10 days earlier.</small>', '<small v-if="isAuwReinsurer(row.name)">Month-end + 120 calendar days. Accounting date is 10 days earlier.</small><small v-else-if="isSwissProperty && isSwissFacility(row.name)">Swiss settlement dates: 02/14, 05/14, 08/14 and 11/14.</small>', 1)
assert body.count(':disabled="isEndorsementDraft" :min="15"') == 1
body = body.replace(':disabled="isEndorsementDraft" :min="15"', ':disabled="isEndorsementDraft || isSwissProperty" :min="15"', 1)
assert body.count('<small>Calendar days. Cedant accounting date is 15 days before collection. AUW payment is month-end + 120 days, with accounting 10 days earlier; other reinsurers use Terms − 10.</small>') == 1
body = body.replace('<small>Calendar days. Cedant accounting date is 15 days before collection. AUW payment is month-end + 120 days, with accounting 10 days earlier; other reinsurers use Terms − 10.</small>', '<small v-if="isSwissProperty">Fixed 90 calendar days; Accounting displays day 75. Swiss uses quarterly settlement dates and month-end confirmation cutoffs.</small><small v-else>Calendar days. Cedant accounting date is 15 days before collection. AUW payment is month-end + 120 days, with accounting 10 days earlier; other reinsurers use Terms − 10.</small>', 1)
assert body.count('<el-input-number v-model="row.paymentTermsDays" :min="15"') == 1
body = body.replace('<el-input-number v-model="row.paymentTermsDays" :min="15"', '<el-input-number v-model="row.paymentTermsDays" :disabled="isSwissProperty" :min="15"', 1)
assert body.count('<el-input-number v-else v-model="row.reinsurerPaymentTerms') == 1
body = body.replace('<el-input-number v-else v-model="row.reinsurerPaymentTerms', '<el-input-number v-else-if="isSwissProperty && isSwissFacility(reinsurer.name)" :model-value="90" disabled :controls="false"></el-input-number><el-input-number v-else v-model="row.reinsurerPaymentTerms', 1)

# Facility reconciliation is explicitly confirmed by Accounting.
body = body.replace("open: 'Open', not_tracked", "open: 'Open', pending_confirmation: 'Awaiting confirmation', not_tracked")

TARGET.write_text(script % "\n".join("  " + l for l in exported.split("\n")) + body + risk_type_style, encoding="utf-8")
print("wrote", TARGET, len(body.split("\n")), "template lines")
