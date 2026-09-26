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

# Claim 分頁（第 502–555 行）與記錄理賠付款的對話框（第 579–588 行）：Claims 的後端尚未移植，
# 拿掉之後 Claim 分頁會落到 Alpha 自己的 v-else（「will be converted … in a later milestone」）
claims_first, claims_last = 502 - 217, 555 - 217
assert detail[claims_first].strip().startswith("<template v-else-if=\"caseDetailTab === 'claims'")
assert detail[claims_last + 1].strip().startswith("<template v-else-if=\"caseDetailTab === 'endorsements'")
payment_first, payment_last = 579 - 217, 588 - 217
assert detail[payment_first].strip().startswith('<el-dialog v-model="paymentDialogVisible"')
assert detail[payment_last - 1].strip() == "</el-dialog>" and detail[payment_last].strip() == ""
detail = detail[:claims_first] + detail[claims_last + 1:payment_first] + detail[payment_last + 1:]

body = "\n".join(["<template>", "  <Teleport defer to=\"#page-header-actions\">"]
                 + [l.replace('v-else-if="activeView === \'case-create\'"', 'v-if="activeView === \'case-create\'"', 1) if i == 0 else l
                    for i, l in enumerate(header_actions)]
                 + ["  </Teleport>", ""]
                 + [cases[0].replace('v-else-if="activeView', 'v-if="activeView', 1)] + cases[1:]
                 + [""] + detail + create + ["</template>", ""])

REPLACEMENTS = [
    # 文件上限：VM 10 MB（Alpha 5 MB）
    ("Supported: PDF, DOCX, PNG, JPG, EML and MSG. Maximum 5 MB per file.", "Supported: PDF, DOCX, PNG, JPG, EML and MSG. Maximum 10 MB per file.", 1),
    # VM 已啟用 Audit（Alpha 是暫停中），如實描述
    ("Announce assigns the TW Reference. Audit recording will begin after migration to the VM.", "Announce assigns the TW Reference and is recorded in the Audit Log.", 1),
    # 產生 Word／PDF 的程式尚未移植：按鈕停用並說明
    (':disabled="Boolean(documentGenerating)"', ':disabled="true"', 5),
    ("<p class=\"document-help\">{{ selectedPayload.parentTwRef ? 'Endorsement output follows Development behavior: PDF only.' : 'Cover Note is available while the case is Draft. Debit Note becomes available after Announce assigns the TW Reference.' }}</p>",
     "<p class=\"document-help\">{{ selectedPayload.parentTwRef ? 'Endorsement output follows Development behavior: PDF only.' : 'Cover Note is available while the case is Draft. Debit Note becomes available after Announce assigns the TW Reference.' }}</p>\n"
     "                      <el-alert type=\"info\" :closable=\"false\" show-icon title=\"Document generation is not available on the VM yet\" description=\"The Word and PDF generators are migrated in a later step. Placement documents below can be uploaded and reviewed now.\"></el-alert>", 1),
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
statusLabel, loadData, saveDraft"""
TARGET.write_text(script % "\n".join("  " + l for l in exported.split("\n")) + body, encoding="utf-8")
print("wrote", TARGET, len(body.split("\n")), "template lines")
