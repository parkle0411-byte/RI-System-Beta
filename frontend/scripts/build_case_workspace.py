"""
從 Alpha 的 index.html（alpha-reference/，雜湊已核對）按行號切出案件工作區的模板，產生 src/views/CaseWorkspace.vue。
每一處替換都寫在 REPLACEMENTS，並要求「剛好出現指定次數」，Alpha 改版時不會悄悄失效。

  python3 scripts/build_case_workspace.py
"""
import hashlib
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "alpha-reference" / "index.html"
TARGET = ROOT / "src" / "views" / "CaseWorkspace.vue"
EXPECTED_SHA256 = "72de4a046c42d0dc6acc3eae3773975f8bfea8aa675e639fc50c29efe8383e00"

text = SOURCE.read_text(encoding="utf-8")
assert hashlib.sha256(text.encode()).hexdigest() == EXPECTED_SHA256, "alpha-reference/index.html 與記錄的 Alpha v53 不同"
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
    # 理賠：出險日與付款日期必填（VM 的決定，Alpha 可留空）
    ("<p>Development-compatible loss details. Blank optional fields can be completed later through the reserve workflow.</p>",
     "<p>Development-compatible loss details. Date of Loss is required; the Outstanding Reserve can be updated later.</p>", 1),
    ('<el-form-item label="Date of Loss"><el-date-picker v-model="claimForm.dateOfLoss"', '<el-form-item label="Date of Loss" required><el-date-picker v-model="claimForm.dateOfLoss"', 1),
    ('<el-form-item label="Payment date"><el-date-picker v-model="paymentForm.date"', '<el-form-item label="Payment date" required><el-date-picker v-model="paymentForm.date"', 1),
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
for old, new, count in REPLACEMENTS:
    found = body.count(old)
    assert found == count, (old[:70], found, count)
    body = body.replace(old, new)

script = """<script setup>
// 由 scripts/build_case_workspace.py 產生：模板按行號切自 Alpha public/index.html（v53）；請勿直接修改模板，
// 要改就改產生程式（或 Alpha 更新後重新產生）。邏輯在 case-workspace.script.js。
import { useCaseWorkspace } from './case-workspace.script'

const {
%s
} = useCaseWorkspace()
</script>

"""
exported = """can, activeView, currentHeader, loading, saving, saveMessage,
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
statusLabel, loadData, saveDraft,
caseReminders, remindersLoading, loadCaseReminders, reminderPreview, reminderPreviewVisible, openReminderPreview, reminderStatusLabel, reminderStatusType, paymentReminderLabel"""
TARGET.write_text(script % "\n".join("  " + l for l in exported.split("\n")) + body, encoding="utf-8")
print("wrote", TARGET, len(body.split("\n")), "template lines")
