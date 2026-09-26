<script setup>
// 由 scripts/build_case_workspace.py 產生：模板按行號切自 Alpha public/index.html（v53）；請勿直接修改模板，
// 要改就改產生程式（或 Alpha 更新後重新產生）。邏輯在 case-workspace.script.js。
import { useCaseWorkspace } from './case-workspace.script'

const {
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
} = useCaseWorkspace()
</script>

<template>
  <Teleport defer to="#page-header-actions">
            <div v-if="activeView === 'case-create'" class="header-action-group">
              <el-button class="header-secondary-button" @click="cancelNewCase">Cancel</el-button>
              <el-button class="primary-button" :loading="saving" @click="saveDraft">{{ isEditing ? 'Save changes' : 'Save draft' }}</el-button>
            </div>
            <div v-else-if="activeView === 'case-detail'" class="detail-header-actions">
              <el-button class="header-secondary-button" @click="backToCases">Back to Account List</el-button>
              <el-button v-if="['draft', 'posted', 'reversed'].includes(selectedCase?.status) && can('cases.write')" class="primary-button" @click="editSelectedCase">{{ selectedCase?.status === 'reversed' ? 'Correct reversed case' : selectedCase?.status === 'posted' ? 'Edit announced case' : 'Edit draft' }}</el-button>
              <el-button v-if="caseWorkflow?.actions?.canReverse && can('cases.write')" class="secondary-button" :loading="workflowSaving" @click="reverseSelectedCase">Reverse case</el-button>
              <el-button v-if="caseWorkflow?.actions?.canRenew && can('cases.write')" class="secondary-button" :loading="workflowSaving" @click="createRenewal">Create renewal</el-button>
            </div>
  </Teleport>

          <template v-if="activeView === 'cases'">
            <section class="table-card account-list-panel">
              <div class="account-list-head">
                <h2>All cases</h2>
                <el-button v-if="can('cases.write')" class="primary-button" @click="startNewCase">+ New case</el-button>
              </div>
              <div class="list-toolbar">
                <el-input v-model="filters.search" clearable placeholder="Search insured, TW Ref, reinsurer, cedant, class…" class="search-field"></el-input>
                <el-select v-model="filters.status" class="status-filter" aria-label="Status filter">
                  <el-option label="All statuses" value="all"></el-option><el-option label="Draft" value="draft"></el-option>
                  <el-option label="Announced" value="posted"></el-option><el-option label="Confirmed" value="closed"></el-option>
                  <el-option label="Reversed" value="reversed"></el-option>
                </el-select>
              </div>
              <el-table :data="filteredCases" class="case-table development-case-table" empty-text="No cases yet. Select + New case to create the first draft." row-key="id" @row-click="openCasePreview">
                <el-table-column prop="originalInsured" label="Insured (EN)" min-width="220" sortable><template #default="{ row }"><el-button link type="primary" class="insured-preview-link" @click.stop="openCasePreview(row)">{{ row.originalInsured || 'Unnamed case' }}</el-button></template></el-table-column>
                <el-table-column prop="originalInsuredCn" label="Insured (CN)" min-width="180" sortable><template #default="{ row }">{{ row.originalInsuredCn || '—' }}</template></el-table-column>
                <el-table-column label="Year" width="90" sortable :sort-method="(a,b) => String(a.effectiveDate || '').localeCompare(String(b.effectiveDate || ''))"><template #default="{ row }">{{ String(row.effectiveDate || '').slice(0,4) || '—' }}</template></el-table-column>
                <el-table-column prop="className" label="Class" min-width="130" sortable><template #default="{ row }">{{ row.className || '—' }}</template></el-table-column>
                <el-table-column prop="twRef" label="TW Ref. No." min-width="145" sortable><template #default="{ row }"><span class="case-ref">{{ row.twRef || '—' }}</span></template></el-table-column>
                <el-table-column label="Reinsurer" min-width="180"><template #default="{ row }">{{ Array.isArray(row.reinsurerDisplayNames) && row.reinsurerDisplayNames.length ? row.reinsurerDisplayNames.join(', ') : '—' }}</template></el-table-column>
                <el-table-column prop="reinsuredDisplayName" label="Cedant" min-width="150" sortable><template #default="{ row }">{{ row.reinsuredDisplayName || '—' }}</template></el-table-column>
                <el-table-column label="Policy Period" min-width="300"><template #default="{ row }">{{ formatPolicyPeriod(row) }}</template></el-table-column>
                <el-table-column label="Status" width="125"><template #default="{ row }"><span class="status-badge" :class="'status-' + row.status">{{ statusLabel(row.status) }}</span></template></el-table-column>
              </el-table>
            </section>

            <el-dialog v-model="casePreviewVisible" title="Case Preview" width="min(820px, 94vw)" class="case-preview-dialog" destroy-on-close>
              <div v-if="casePreview" class="case-preview-grid">
                <div class="case-preview-item"><span>Insured (EN)</span><strong>{{ casePreview.originalInsured || '—' }}</strong></div>
                <div class="case-preview-item"><span>Insured (CN)</span><strong>{{ casePreview.originalInsuredCn || '—' }}</strong></div>
                <div class="case-preview-item"><span>Year</span><strong>{{ String(casePreview.effectiveDate || '').slice(0,4) || '—' }}</strong></div>
                <div class="case-preview-item"><span>Class</span><strong>{{ casePreview.className || '—' }}</strong></div>
                <div class="case-preview-item"><span>TW Ref. No.</span><strong>{{ casePreview.twRef || '—' }}</strong></div>
                <div class="case-preview-item"><span>Reinsurer</span><strong>{{ Array.isArray(casePreview.reinsurers) && casePreview.reinsurers.length ? casePreview.reinsurers.join(', ') : '—' }}</strong></div>
                <div class="case-preview-item"><span>Cedant</span><strong>{{ casePreview.reinsured || '—' }}</strong></div>
                <div class="case-preview-item"><span>Effective Date</span><strong>{{ formatPolicyDateTime(casePreview.effectiveDate, casePreview.effectiveTime) }}</strong></div>
                <div class="case-preview-item"><span>Expiry Date</span><strong>{{ formatPolicyDateTime(casePreview.expirationDate, casePreview.expirationTime) }}</strong></div>
                <div class="case-preview-item"><span>AE</span><strong>{{ casePreview.aeName || '—' }}</strong></div>
                <div class="case-preview-item"><span>Our Share Premium</span><strong>{{ casePreview.currency || '' }} {{ formatMoney(casePreview.ourSharePremium || 0) }}</strong></div>
                <div class="case-preview-item"><span>Brokerage</span><strong>{{ casePreview.currency || '' }} {{ formatMoney(casePreview.brokerage || 0) }}</strong></div>
                <div class="case-preview-item"><span>Status</span><strong><span class="status-badge" :class="'status-' + casePreview.status">{{ statusLabel(casePreview.status) }}</span></strong></div>
              </div>
              <template #footer><div class="case-preview-actions"><el-button v-if="casePreview?.status === 'draft' && can('recycle.write')" type="danger" plain :disabled="recycleSaving" @click="casePreviewVisible = false; recycleDraft(casePreview)">Recycle Draft</el-button><span></span><el-button @click="casePreviewVisible = false">Close</el-button><el-button class="primary-button" @click="openPreviewFullCase">Open full case</el-button></div></template>
            </el-dialog>
          </template>

          <template v-else-if="activeView === 'case-detail'">
            <div v-loading="caseDetailLoading">
              <el-tabs v-model="caseDetailTab" class="case-detail-tabs" @tab-change="onCaseDetailTabChange">
                <el-tab-pane label="Overview" name="overview"></el-tab-pane>
                <el-tab-pane v-if="can('documents.read')" label="Cover & Debit Note" name="documents"></el-tab-pane>
                <el-tab-pane label="SOA / Transactions" name="soa"></el-tab-pane>
                <el-tab-pane label="Claim" name="claims"></el-tab-pane>
                <el-tab-pane label="Endorsements" name="endorsements"></el-tab-pane>
              </el-tabs>

              <template v-if="caseDetailTab === 'overview' && selectedCase">
                <div class="overview-grid">
                  <div class="overview-stack">
                    <section class="overview-card">
                      <div class="section-heading"><div><h2>Risk details</h2><p>Current saved case snapshot · version {{ selectedCase.rowVersion }}</p></div><span class="status-badge" :class="'status-' + selectedCase.status">{{ statusLabel(selectedCase.status) }}</span></div>
                      <dl class="overview-kv">
                        <dt>Type</dt><dd>{{ selectedPayload.type || '—' }}</dd>
                        <dt>Original insured (EN)</dt><dd>{{ selectedPayload.originalInsured || '—' }}</dd>
                        <dt>Original insured (CN)</dt><dd>{{ selectedPayload.originalInsuredCn || '—' }} <small v-if="selectedPayload.originalInsuredCn">(internal only)</small></dd>
                        <dt>Reinsured</dt><dd>{{ selectedPayload.reinsured || '—' }}</dd>
                        <dt>Structure</dt><dd>{{ structureLabel(selectedPayload.reinsuranceStructure) }}</dd>
                        <dt>Class</dt><dd>{{ selectedPayload.classOfBusiness || '—' }}<span v-if="selectedPayload.classCode"> · {{ selectedPayload.classCode }}</span></dd>
                        <dt>Policy period</dt><dd>{{ formatPolicyDateTime(selectedPayload.policyFrom, selectedPayload.policyFromTime) }} ~ {{ formatPolicyDateTime(selectedPayload.policyTo, selectedPayload.policyToTime) }}</dd>
                        <template v-if="selectedPayload.parentTwRef">
                          <dt>Endorsement of</dt><dd>{{ selectedPayload.parentTwRef }}</dd>
                          <dt>Effective date</dt><dd>{{ selectedPayload.endoEffectiveDate || '—' }}</dd>
                          <dt>Endorsement types</dt><dd>{{ (selectedPayload.endoTypes || []).join(', ') || '—' }}</dd>
                          <dt>Endorsement wording</dt><dd>{{ selectedPayload.endoText || '—' }}</dd>
                        </template>
                        <template v-if="selectedPayload.renewedFromTwRef"><dt>Renewed from</dt><dd>{{ selectedPayload.renewedFromTwRef }}</dd></template>
                        <dt>Situation</dt><dd><div v-for="(row,index) in selectedPayload.situations || []" :key="'detail-situation-' + index">{{ row.address || '—' }}<span v-if="row.postcode"> · {{ row.postcode }}</span></div><span v-if="!(selectedPayload.situations || []).length">—</span></dd>
                        <dt>Case owner</dt><dd>{{ selectedPayload.ownerPersonnelName || '—' }}</dd>
                        <dt>AE</dt><dd>{{ selectedPayload.ae || '—' }}</dd>
                        <dt>Total Sum Insured</dt><dd>{{ selectedPayload.currency || '—' }} {{ formatCurrency(selectedOverview.totalSumInsured, selectedPayload.currency) }}</dd>
                        <dt>Avg. Rate</dt><dd class="overview-emphasis" data-testid="avg-rate">{{ selectedOverview.avgRate }}</dd>
                      </dl>
                    </section>

                    <section class="overview-card">
                      <h2>Schedule of security</h2>
                      <div class="overview-table-wrap">
                        <table class="overview-table"><thead><tr><th>Reinsurer</th><th>Foreign RI Broker</th><th class="number-cell">Order hereon</th><th>Reference</th></tr></thead><tbody>
                          <tr v-for="(row,index) in selectedPayload.reinsurers || []" :key="'detail-reinsurer-' + index"><td>{{ row.name || '—' }}</td><td>{{ row.foreignBroker || '—' }}</td><td class="number-cell">{{ formatAmount(row.sharePct) }}%</td><td>{{ row.settlementRef || '—' }}</td></tr>
                        </tbody><tfoot><tr><th colspan="2">Total</th><th class="number-cell">{{ formatAmount(selectedOverview.totalOrderHereon) }}%</th><th></th></tr></tfoot></table>
                      </div>
                    </section>

                    <section class="overview-card">
                      <div class="section-heading"><div><h2>Loss Record</h2><p>Advised by broker on {{ selectedPayload.lossAdvisedDate || '—' }}</p></div><span class="pending-badge">{{ selectedOverview.lossRecordSummary }}</span></div>
                      <div v-if="(selectedPayload.lossRecord || []).length" class="review-list"><div v-for="(row,index) in selectedPayload.lossRecord" :key="'overview-loss-' + index"><strong>Loss {{ index + 1 }} · {{ row.date || '—' }}</strong><span>{{ row.cause || '—' }} · {{ selectedPayload.currency || '—' }} {{ formatAmount(row.lossPaid) }}</span></div></div>
                      <p v-else class="document-help">Clean — no losses recorded.</p>
                      <p v-if="selectedPayload.lossRecordText" class="document-help">{{ selectedPayload.lossRecordText }}</p>
                    </section>

                    <section class="overview-card">
                      <h2>Reinsurance conditions</h2>
                      <div class="review-list"><div v-for="clause in selectedOverview.clauseDetails" :key="'overview-clause-' + clause.code"><strong>{{ clause.code }}</strong><span>{{ clause.title }}</span></div></div>
                    </section>
                  </div>

                  <div class="overview-stack">
                    <section class="overview-card">
                      <h2>Computed amounts ({{ selectedPayload.currency || '—' }})</h2>
                      <div class="calculation-list">
                        <div class="calculation-row"><span>100% Premium</span><strong>{{ formatMoney(selectedPayload.originalPremium) }}</strong></div>
                        <div class="calculation-row"><span>Ceded premium ({{ formatAmount(selectedOverview.totalOrderHereon) }}%)</span><strong>{{ formatMoney(selectedOverview.legs.cedantPremium) }}</strong></div>
                        <div class="calculation-row leg"><span>{{ selectedOverview.legLabels.leg1 }}</span><strong>{{ formatMoney(selectedOverview.displayLegs.leg1) }}</strong></div>
                        <div class="calculation-row leg"><span>{{ selectedOverview.legLabels.leg2 }}</span><strong>{{ formatMoney(selectedOverview.displayLegs.leg2) }}</strong></div>
                        <div class="calculation-row leg"><span>Brokerage</span><strong>{{ formatMoney(selectedOverview.displayLegs.leg3) }}</strong></div>
                      </div>
                    </section>

                    <section class="overview-card">
                      <h2>Premium breakdown</h2>
                      <dl class="overview-kv">
                        <dt>Cedant commission</dt><dd>{{ formatMoney(selectedOverview.legs.cedantCommission) }}</dd>
                        <dt>Cedant tax</dt><dd>{{ formatMoney(selectedOverview.legs.cedantTax) }}</dd>
                        <dt>Reinsurer premium</dt><dd>{{ formatMoney(selectedOverview.legs.reinsurerPremium) }}</dd>
                        <dt>Reinsurer deductions</dt><dd>{{ formatMoney(selectedOverview.legs.reinsurerDeductions) }}</dd>
                        <dt>Reinsurer tax</dt><dd>{{ formatMoney(selectedOverview.legs.reinsurerTax) }}</dd>
                      </dl>
                    </section>

                    <section v-if="selectedPayload.installmentEnabled" class="overview-card">
                      <div class="section-heading"><div><h2>Premium Installments</h2><p>Future Production Report performance allocation</p></div><span class="pending-badge">{{ selectedOverview.installments.length }} installments</span></div>
                      <div class="review-list"><div v-for="(row,index) in selectedOverview.installments" :key="'overview-installment-' + row.id"><strong>Installment {{ index + 1 }} · {{ row.performanceMonth || '—' }}</strong><span>{{ Number(selectedPayload.originalPremium || 0) === 0 ? formatAmount(row.ratio * 100) + '%' : (selectedPayload.currency || '—') + ' ' + formatAmount(row.premium) }} · Income {{ selectedPayload.currency || '—' }} {{ formatMoney(row.income) }}</span></div></div>
                    </section>

                    <section v-if="selectedPayload.splitEnabled" class="overview-card">
                      <div class="section-heading"><div><h2>Performance Split</h2><p>Internal production credit only</p></div><span class="pending-badge">100%</span></div>
                      <div class="review-list"><div v-for="(row,index) in selectedPayload.splitParties || []" :key="'overview-split-' + index"><strong>Party {{ index === 0 ? 'A' : 'B' }} · {{ row.name || '—' }}</strong><span>{{ formatAmount(row.pct) }}%</span></div></div>
                    </section>

                    <section v-if="caseWorkflow?.actions?.canNotifyAccounting || (caseWorkflow?.notifications || []).length" class="overview-card">
                      <div class="section-heading"><div><h2>Accounting notifications</h2><p>Non-blocking record of the staff member notified</p></div><el-button v-if="caseWorkflow?.actions?.canNotifyAccounting" class="secondary-button" :loading="workflowSaving" @click="openAccountingNotification">Record notification</el-button></div>
                      <div v-if="(caseWorkflow?.notifications || []).length" class="review-list">
                        <div v-for="row in caseWorkflow.notifications" :key="row.id"><strong>{{ row.accountingStaffName }}</strong><span>{{ formatDateTime(row.notifiedAt) }} · by {{ row.notifiedByName }}<template v-if="row.note"> · {{ row.note }}</template></span></div>
                      </div>
                      <p v-else class="document-help">No Accounting notification has been recorded.</p>
                    </section>

                    <section class="overview-card">
                      <h2>Terms & conditions</h2>
                      <dl class="overview-kv">
                        <dt>Limit of Liability</dt><dd>{{ selectedPayload.currency || '—' }} {{ formatCurrency(selectedPayload.limitOfLiability, selectedPayload.currency) }}</dd>
                        <dt>Aggregate Limit</dt><dd>{{ selectedPayload.aggregateLimit === null || selectedPayload.aggregateLimit === undefined ? '—' : (selectedPayload.currency || '—') + ' ' + formatCurrency(selectedPayload.aggregateLimit, selectedPayload.currency) }}</dd>
                        <template v-if="selectedPayload.reinsuranceStructure !== 'QS'"><dt>Underlying Limits</dt><dd>{{ selectedPayload.underlyingLimits || '—' }}</dd></template>
                        <dt>Sub-Limits</dt><dd>{{ selectedPayload.subLimits || '—' }}</dd>
                        <dt>Deductibles</dt><dd>{{ selectedPayload.deductibles || '—' }}</dd>
                        <dt>Reinstatement Provisions</dt><dd>{{ selectedPayload.reinstatementProvisions || '—' }}</dd>
                        <dt>Indemnity Period</dt><dd>{{ selectedPayload.indemnityPeriod || '—' }}</dd>
                      </dl>
                    </section>
                  </div>
                </div>
              </template>

              <template v-else-if="caseDetailTab === 'documents' && selectedCase">
                <div class="documents-grid" v-loading="documentsLoading">
                  <div class="overview-stack">
                    <section class="overview-card">
                      <div class="section-heading">
                        <div><h2>Generated documents</h2><p>Development-compatible templates and filenames</p></div>
                        <span class="pending-badge">{{ selectedPayload.parentTwRef ? 'Endorsement PDF' : (selectedCase.status === 'draft' ? 'Cover Note' : 'Cover + Debit Note') }}</span>
                      </div>
                      <div class="generated-document-list">
                        <article v-if="!selectedPayload.parentTwRef" class="generated-document-card">
                          <div>
                            <strong>Cover Note</strong>
                            <span>{{ selectedCase.twRef || 'DRAFT' }} · {{ selectedPayload.reinsuranceStructure || 'Property' }}</span>
                          </div>
                          <div class="generated-document-actions">
                            <el-button class="primary-button" :loading="documentGenerating === 'cover-docx'" :disabled="true" @click="downloadGeneratedDocument('cover', 'docx')">Download Word (.docx)</el-button>
                            <el-button class="secondary-button" :loading="documentGenerating === 'cover-pdf'" :disabled="true" @click="downloadGeneratedDocument('cover', 'pdf')">Download PDF</el-button>
                          </div>
                        </article>
                        <article v-if="selectedPayload.parentTwRef" class="generated-document-card">
                          <div>
                            <strong>Endorsement</strong>
                            <span>{{ selectedCase.twRef || 'DRAFT' }} · effective {{ selectedPayload.endoEffectiveDate || 'not set' }}</span>
                          </div>
                          <div class="generated-document-actions">
                            <el-button class="primary-button" :loading="documentGenerating === 'endorsement-pdf'" :disabled="true" @click="downloadGeneratedDocument('endorsement', 'pdf')">Download PDF</el-button>
                          </div>
                        </article>
                        <article v-if="!selectedPayload.parentTwRef && selectedCase.status !== 'draft'" class="generated-document-card">
                          <div>
                            <strong>Debit Note</strong>
                            <span>{{ selectedCase.twRef }} · {{ selectedPayload.currency || '—' }}</span>
                          </div>
                          <div class="generated-document-actions">
                            <el-button class="primary-button" :loading="documentGenerating === 'debit-docx'" :disabled="true" @click="downloadGeneratedDocument('debit', 'docx')">Download Word (.docx)</el-button>
                            <el-button class="secondary-button" :loading="documentGenerating === 'debit-pdf'" :disabled="true" @click="downloadGeneratedDocument('debit', 'pdf')">Download PDF</el-button>
                          </div>
                        </article>
                      </div>
                      <p class="document-help">{{ selectedPayload.parentTwRef ? 'Endorsement output follows Development behavior: PDF only.' : 'Cover Note is available while the case is Draft. Debit Note becomes available after Announce assigns the TW Reference.' }}</p>
                      <el-alert type="info" :closable="false" show-icon title="Document generation is not available on the VM yet" description="The Word and PDF generators are migrated in a later step. Placement documents below can be uploaded and reviewed now."></el-alert>
                    </section>

                    <section class="overview-card">
                      <div class="section-heading">
                        <div><h2>Placement documents</h2><p>Evidence used for placement review and Announce readiness</p></div>
                        <el-button class="secondary-button" :loading="documentsLoading" @click="loadCaseDocuments">Refresh</el-button>
                      </div>
                      <el-alert :title="documentReadinessText" :type="documentCoverage.ready ? 'success' : 'warning'" :closable="false" show-icon></el-alert>
                      <el-alert v-if="selectedCase.status === 'draft' && selectedAnnounceIssues.length" class="case-readiness-alert" :title="`Complete ${selectedAnnounceIssues.length} required case fields before Announce.`" :description="selectedAnnounceIssues.join(', ')" type="warning" :closable="false" show-icon></el-alert>
                      <div class="document-summary">
                        <article><span>Offer Slip</span><strong>{{ documentCoverage.offer ? 'Available' : 'Missing' }}</strong></article>
                        <article><span>Reinsurer coverage</span><strong>{{ (documentCoverage.covered || []).length }} / {{ (documentCoverage.required || []).length }}</strong></article>
                        <article><span>Announce readiness</span><strong>{{ documentCoverage.ready ? 'Ready' : 'Not ready' }}</strong></article>
                      </div>
                    </section>

                    <section class="overview-card">
                      <div class="section-heading">
                        <div><h2>Signed Slip reminder</h2><p>Tracked separately from Announce evidence. Confirmation E-mail does not complete this follow-up.</p></div>
                        <span class="status-badge" :class="signedSlipReminder.due ? 'status-reversed' : signedSlipReminder.complete ? 'status-posted' : 'status-draft'">
                          {{ signedSlipReminder.due ? 'Due' : signedSlipReminder.complete ? 'Complete' : 'Tracking' }}
                        </span>
                      </div>
                      <el-alert v-if="!signedSlipReminder.outboundEnabled" title="Internal review only — automated e-mail delivery is not enabled." type="info" :closable="false" show-icon></el-alert>
                      <el-alert v-else title="Daily automatic reminder is enabled. Due notices are sent to the case AE and the supervisor recorded in Personnel." type="success" :closable="false" show-icon></el-alert>
                      <dl class="overview-kv" style="margin-top:16px;">
                        <dt>Tracking starts</dt><dd>60 days after policy effective date</dd>
                        <dt>First reminder date</dt><dd>{{ signedSlipReminder.firstReminderOn || '—' }}</dd>
                        <dt>Review date</dt><dd>{{ signedSlipReminder.today || '—' }}</dd>
                        <dt>Days since effective</dt><dd>{{ signedSlipReminder.daysSinceEffective === null ? '—' : signedSlipReminder.daysSinceEffective }}</dd>
                        <dt>Repeat cadence</dt><dd>Every {{ signedSlipReminder.cadenceDays || 7 }} days while Signed Slips remain missing</dd>
                      </dl>
                      <div v-if="selectedReinsurers.length && (signedSlipReminder.missing || []).length" class="coverage-list" style="margin-top:16px;">
                        <div v-for="name in signedSlipReminder.missing" :key="'signed-missing-' + name"><span>{{ displayReinsurerName(name) }}</span><span class="status-badge status-draft">Signed Slip missing</span></div>
                      </div>
                      <p v-else-if="selectedReinsurers.length" class="document-help">Every named reinsurer has a stored Reinsurer Signed Slip.</p>
                      <p v-else class="document-help">Add at least one named reinsurer before Signed Slip tracking can be completed.</p>
                      <p v-if="!signedSlipReminder.eligibleStatus" class="document-help">The 60-day timer becomes actionable after the case is Announced.</p>
                    </section>

                    <section class="overview-card">
                      <div class="section-heading"><div><h2>Stored evidence</h2><p>Checked documents are included in the current readiness review.</p></div><span class="pending-badge">{{ caseDocuments.length }} files</span></div>
                      <el-table :data="caseDocuments" empty-text="No placement documents uploaded yet." class="document-table" row-key="id">
                        <el-table-column label="Use" width="72" align="center"><template #default="{ row }"><el-checkbox v-model="row.is_selected" :disabled="documentsSaving || !can('documents.write')" aria-label="Use this document" @change="toggleDocumentSelection(row, $event)"></el-checkbox></template></el-table-column>
                        <el-table-column label="Document" min-width="270"><template #default="{ row }"><div class="document-name"><strong>{{ row.filename }}</strong><span>{{ documentKindLabel(row.kind) }} · {{ formatFileSize(row.byte_size) }}</span></div></template></el-table-column>
                        <el-table-column label="Reinsurer coverage" min-width="220"><template #default="{ row }"><span v-if="row.kind === 'offer'">All placement terms</span><span v-else>{{ (row.reinsurers || []).map(displayReinsurerName).join(', ') || '—' }}</span></template></el-table-column>
                        <el-table-column label="Uploaded" min-width="175"><template #default="{ row }">{{ formatDateTime(row.uploaded_at) }}</template></el-table-column>
                        <el-table-column label="Action" width="155"><template #default="{ row }"><el-button text class="table-action" @click="downloadCaseDocument(row)">Download</el-button><el-button v-if="can('documents.write')" text class="table-action danger-action" :disabled="documentsSaving" @click="deleteCaseDocument(row)">Delete</el-button></template></el-table-column>
                      </el-table>
                    </section>
                  </div>

                  <div class="overview-stack">
                    <section v-if="can('documents.write')" class="overview-card document-upload-card">
                      <h2>Upload evidence</h2>
                      <p class="document-help">Supported: PDF, DOCX, PNG, JPG, EML and MSG. Maximum 10 MB per file.</p>
                      <el-form label-position="top">
                        <el-form-item label="Document type">
                          <el-select v-model="documentForm.kind" @change="onDocumentKindChange">
                            <el-option label="Offer Slip" value="offer"></el-option>
                            <el-option label="Reinsurer Signed Slip" value="signed"></el-option>
                            <el-option label="Reinsurer Confirmation E-mail" value="confirmation"></el-option>
                          </el-select>
                        </el-form-item>
                        <el-form-item v-if="documentForm.kind !== 'offer'" :label="documentForm.kind === 'signed' ? 'Signed by reinsurer(s)' : 'Confirmed by reinsurer(s)'">
                          <el-select v-model="documentForm.reinsurers" multiple collapse-tags collapse-tags-tooltip placeholder="Select reinsurer(s)">
                            <el-option v-for="row in selectedReinsurers" :key="row.key" :label="row.label" :value="row.key"></el-option>
                          </el-select>
                        </el-form-item>
                        <el-form-item label="File">
                          <el-upload drag action="#" :auto-upload="false" :limit="1" accept=".pdf,.docx,.png,.jpg,.jpeg,.eml,.msg" :file-list="documentFileList" :on-change="onDocumentFileChange" :on-remove="onDocumentFileRemove">
                            <div class="el-upload__text">Drop a file here or <em>select file</em></div>
                            <template #tip><div class="el-upload__tip">The uploaded file is automatically selected for the current review.</div></template>
                          </el-upload>
                        </el-form-item>
                        <el-button class="primary-button document-upload-button" :loading="documentsSaving" @click="uploadCaseDocument">Upload evidence</el-button>
                      </el-form>
                    </section>

                    <section class="overview-card">
                      <h2>Coverage by reinsurer</h2>
                      <div v-if="selectedReinsurers.length" class="coverage-list">
                        <div v-for="row in selectedReinsurers" :key="'coverage-' + row.key"><span>{{ row.label }}</span><span class="status-badge" :class="(documentCoverage.covered || []).includes(row.key) ? 'status-posted' : 'status-draft'">{{ (documentCoverage.covered || []).includes(row.key) ? 'Covered' : 'Missing' }}</span></div>
                      </div>
                      <p v-else class="document-help">Add at least one named reinsurer in Schedule of Security before completing the Announce evidence check.</p>
                    </section>

                    <section class="overview-card">
                      <h2>Review & Announce</h2>
                      <p v-if="selectedCase.status === 'draft'" class="document-help">After all evidence is available, confirm that the selected files and e-mails match the case's latest terms. Announce assigns the TW Reference and is recorded in the Audit Log.</p>
                      <p v-else class="document-help">This case was Announced as {{ selectedCase.twRef }}. Placement evidence remains available for upload, download and review.</p>
                      <el-button v-if="selectedCase.status === 'draft' && can('cases.announce')" class="primary-button" :disabled="!documentCoverage.ready || selectedAnnounceIssues.length > 0 || documentsLoading" @click="openAnnounceReview">Review & Announce</el-button>
                      <span v-else class="status-badge status-posted">Announced</span>
                    </section>
                  </div>
                </div>
              </template>

              <template v-else-if="caseDetailTab === 'soa' && selectedCase">
                <div class="overview-stack">
                  <section class="overview-card">
                    <div class="section-heading">
                      <div><span class="pending-badge">Read-only case statement</span><h2>Statement of Account — {{ selectedCase.twRef || 'Draft' }}</h2><p>Settlement changes are made only from the consolidated Accounting ledger.</p></div>
                      <span class="status-badge" :class="'status-' + selectedCase.status">{{ statusLabel(selectedCase.status) }}</span>
                    </div>
                    <dl class="overview-kv" style="margin-bottom:18px;">
                      <dt>Statement No.</dt><dd>{{ selectedPayload.statementNo || '—' }}</dd>
                      <dt>Currency</dt><dd>{{ selectedPayload.currency || '—' }}</dd>
                      <dt>Transactions</dt><dd>{{ selectedCaseTransactions.length }}</dd>
                    </dl>
                    <div class="overview-table-wrap">
                      <el-table :data="selectedCaseTransactions" row-key="key" empty-text="Transactions are generated when all Production rows for this case are confirmed through a closed monthly report.">
                        <el-table-column prop="txNo" label="Transaction no." min-width="210">
                          <template #default="{ row }"><strong>{{ row.txNo }}</strong><el-tag v-if="row.reversed" size="small" type="danger" effect="plain" style="margin-left:6px;">Reversed</el-tag><el-tag v-if="row.isReversalEntry" size="small" type="warning" effect="plain" style="margin-left:6px;">Reversal entry</el-tag></template>
                        </el-table-column>
                        <el-table-column prop="sourceLabel" label="Type" width="100"></el-table-column>
                        <el-table-column prop="legType" label="Leg" width="120"></el-table-column>
                        <el-table-column prop="reinsurer" label="Reinsurer / R/I Broker" min-width="210"></el-table-column>
                        <el-table-column prop="label" label="Recipient" min-width="320"></el-table-column>
                        <el-table-column label="Amount" min-width="150" align="right"><template #default="{ row }">{{ selectedPayload.currency || '—' }} {{ formatMoney(row.amount) }}</template></el-table-column>
                        <el-table-column label="Reconciliation Ref" min-width="180"><template #default="{ row }">{{ row.reconciliationRef || '—' }}</template></el-table-column>
                        <el-table-column label="Settlement" width="130"><template #default="{ row }"><el-tag :type="{ settled: 'success', partial: 'warning', open: 'info', not_tracked: 'info' }[row.settlement] || 'info'" effect="plain">{{ { settled: 'Settled', partial: 'Partial', open: 'Open', not_tracked: 'Not tracked' }[row.settlement] || 'Open' }}</el-tag></template></el-table-column>
                      </el-table>
                    </div>
                  </section>
                </div>
              </template>

              <template v-else-if="caseDetailTab === 'claims' && selectedCase">
                <div class="overview-stack" v-loading="claimsLoading">
                  <section class="overview-card">
                    <div class="section-heading">
                      <div><span class="pending-badge">Policy-period record</span><h2>Claims — {{ claimsState.rootTwRef || 'Draft' }}</h2><p>Claims are stored once on the root case and remain the same from every endorsement view.</p></div>
                      <span class="status-badge" :class="'status-' + claimsState.rootStatus">{{ statusLabel(claimsState.rootStatus) }}</span>
                    </div>
                    <el-alert v-if="!claimsState.rootTwRef" title="This case has not been Announced yet. Claims can be recorded after a TW Reference is assigned." type="info" :closable="false" show-icon></el-alert>
                    <dl v-else class="overview-kv">
                      <dt>Root TW Reference</dt><dd>{{ claimsState.rootTwRef }}</dd>
                      <dt>Currency</dt><dd>{{ claimsState.currency || '—' }}</dd>
                      <dt>Current split source</dt><dd>{{ claimsState.splitSource?.twRef || claimsState.rootTwRef }} · {{ (claimsState.splitSource?.reinsurers || []).length }} reinsurer line(s)</dd>
                    </dl>
                  </section>

                  <section v-if="claimsState.actions?.canWrite && can('cases.write')" class="overview-card">
                    <div class="section-heading"><div><h2>Add claim</h2><p>Development-compatible loss details. Date of Loss is required; the Outstanding Reserve can be updated later.</p></div></div>
                    <el-form label-position="top" class="form-grid">
                      <el-form-item label="Claim / Loss No."><el-input v-model="claimForm.lossNo" maxlength="160"></el-input></el-form-item>
                      <el-form-item label="Date of Loss" required><el-date-picker v-model="claimForm.dateOfLoss" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" style="width:100%"></el-date-picker></el-form-item>
                      <el-form-item label="Outstanding Reserve"><el-input-number v-model="claimForm.outstandingReserve" :controls="false" style="width:100%"></el-input-number></el-form-item>
                      <el-form-item label="Cause of Loss" class="full-width"><el-input v-model="claimForm.causeOfLoss" type="textarea" :rows="3" maxlength="2000"></el-input></el-form-item>
                    </el-form>
                    <el-button class="primary-button" :loading="claimsSaving" @click="createClaim">Add claim</el-button>
                  </section>

                  <section v-if="!(claimsState.claims || []).length && claimsState.rootTwRef" class="overview-card overview-empty">
                    <h2>No claims recorded</h2><p>This policy period does not yet have a Claim record.</p>
                  </section>

                  <section v-for="claim in claimsState.claims || []" :key="'claim-' + claim.id" class="overview-card">
                    <div class="section-heading">
                      <div><span class="pending-badge">Claim #{{ claim.id }}</span><h2>{{ claim.lossNo || ('Claim #' + claim.id) }}</h2><p>{{ claim.dateOfLoss || 'Date of loss not recorded' }} · {{ claim.causeOfLoss || 'Cause of loss not recorded' }}</p></div>
                      <el-button v-if="claimsState.actions?.canWrite && can('cases.write')" class="secondary-button" :disabled="claimsSaving" @click="openClaimPayment(claim)">Add payment</el-button>
                    </div>
                    <dl class="overview-kv" style="margin-bottom:18px;">
                      <dt>Cumulative Loss Paid</dt><dd>{{ claimsState.currency || '—' }} {{ formatMoney(claimTotalPaid(claim)) }}</dd>
                      <dt>Outstanding Reserve</dt>
                      <dd>
                        <el-input-number v-if="claimsState.actions?.canWrite && can('cases.write')" v-model="claim.outstandingReserve" :controls="false" :disabled="claimsSaving" @change="updateClaimReserve(claim)" style="width:220px"></el-input-number>
                        <span v-else>{{ claimsState.currency || '—' }} {{ formatMoney(claim.outstandingReserve) }}</span>
                      </dd>
                    </dl>
                    <div class="overview-table-wrap">
                      <el-table :data="claim.payments || []" row-key="id" empty-text="No claim payments recorded.">
                        <el-table-column prop="date" label="Payment date" min-width="140"><template #default="{ row }">{{ row.date || '—' }}</template></el-table-column>
                        <el-table-column label="Amount" min-width="170" align="right"><template #default="{ row }">{{ claimsState.currency || '—' }} {{ formatMoney(row.amount) }}</template></el-table-column>
                        <el-table-column prop="note" label="Note" min-width="260"><template #default="{ row }">{{ row.note || '—' }}</template></el-table-column>
                      </el-table>
                    </div>
                  </section>
                </div>
              </template>

              <template v-else-if="caseDetailTab === 'endorsements' && selectedCase">
                <section class="overview-card" v-loading="workflowLoading">
                  <div class="section-heading">
                    <div><h2>Endorsement chain</h2><p>Only the latest Announced or Confirmed case can create the next endorsement.</p></div>
                    <el-button v-if="caseWorkflow?.actions?.canCreateEndorsement && can('cases.write')" class="primary-button" :loading="workflowSaving" @click="createEndorsement">Create endorsement</el-button>
                  </div>
                  <div v-if="(caseWorkflow?.chain || []).length" class="overview-table-wrap">
                    <table class="overview-table workflow-table"><thead><tr><th>Reference</th><th>Kind</th><th>Status</th><th>Effective date</th><th>Updated</th></tr></thead><tbody>
                      <tr v-for="row in caseWorkflow.chain" :key="row.caseUid" @click="viewWorkflowCase(row)">
                        <td>{{ row.twRef || 'Draft · not assigned' }}</td><td>{{ row.caseKind === 'endorsement' ? 'Endorsement' : 'Original' }}</td><td><span class="status-badge" :class="'status-' + row.status">{{ statusLabel(row.status) }}</span></td><td>{{ row.endoEffectiveDate || formatPolicyDateTime(row.policyFrom, row.policyFromTime) }}</td><td>{{ formatDateTime(row.updatedAt) }}</td>
                      </tr>
                    </tbody></table>
                  </div>
                  <el-empty v-else description="No endorsement chain available"></el-empty>
                  <el-alert v-if="caseWorkflow && !caseWorkflow.actions.canCreateEndorsement && caseWorkflow.latestCaseUid !== selectedCase.caseUid" class="case-readiness-alert" title="A newer endorsement exists. Open the latest row to continue the chain." type="info" :closable="false" show-icon></el-alert>
                </section>
              </template>

              <section v-else class="overview-card overview-empty">
                <h2>{{ caseDetailTabLabel }}</h2><p>This case-detail tab will be converted from the development site in a later milestone.</p>
              </section>
            </div>

            <el-dialog v-model="paymentDialogVisible" class="review-dialog" width="min(620px, 94vw)" :close-on-click-modal="false">
              <template #header><div class="review-heading"><span class="pending-badge">Immediate accounting entry</span><h2>Record claim payment</h2><p>This creates Claim Leg 1/2 transactions immediately. Recorded payments are not deleted; use an offsetting payment to correct an error.</p></div></template>
              <el-form label-position="top">
                <el-form-item label="Payment date" required><el-date-picker v-model="paymentForm.date" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" style="width:100%"></el-date-picker></el-form-item>
                <el-form-item label="Amount"><el-input-number v-model="paymentForm.amount" :controls="false" style="width:100%"></el-input-number><div class="document-help">A non-zero negative amount may be used as an offsetting correction.</div></el-form-item>
                <el-form-item label="Note"><el-input v-model="paymentForm.note" maxlength="1000"></el-input></el-form-item>
              </el-form>
              <template #footer><el-button @click="paymentDialogVisible = false">Cancel</el-button><el-button class="primary-button" :loading="claimsSaving" @click="recordClaimPayment">Record payment</el-button></template>
            </el-dialog>

            <el-dialog v-model="accountingDialogVisible" class="review-dialog" width="min(620px, 94vw)" :close-on-click-modal="false">
              <template #header><div class="review-heading"><span class="pending-badge">Non-blocking record</span><h2>Record Accounting notification</h2><p>Select the Accounting staff member who was notified. This does not change case status.</p></div></template>
              <el-form label-position="top">
                <el-form-item label="Accounting recipient" required><el-select v-model="accountingForm.accountingPersonnelId" filterable placeholder="Select staff"><el-option v-for="row in caseWorkflow?.accountingStaff || []" :key="'accounting-' + row.id" :label="row.name" :value="row.id"></el-option></el-select></el-form-item>
                <el-form-item label="Note"><el-input v-model="accountingForm.note" type="textarea" :rows="4" maxlength="2000" show-word-limit placeholder="Optional context"></el-input></el-form-item>
              </el-form>
              <template #footer><el-button class="secondary-button" :disabled="workflowSaving" @click="accountingDialogVisible = false">Cancel</el-button><el-button class="primary-button" :loading="workflowSaving" @click="saveAccountingNotification">Record notification</el-button></template>
            </el-dialog>

            <el-dialog v-model="announceDialogVisible" class="review-dialog announce-dialog" width="min(820px, 94vw)" :close-on-click-modal="false" :close-on-press-escape="!announcing" :show-close="!announcing">
              <template #header><div class="review-heading"><span class="pending-badge">Final placement review</span><h2>Review before Announce</h2><p>Announce assigns the permanent TW Reference and records this case as Announced.</p></div></template>
              <el-alert title="There is no second-person reviewer in Phase 1. Check the case and selected evidence carefully before continuing." type="warning" :closable="false" show-icon></el-alert>
              <section class="review-section">
                <h3>Case summary</h3>
                <dl class="review-grid">
                  <div><dt>Original insured</dt><dd>{{ selectedPayload.originalInsured || '—' }}</dd></div>
                  <div><dt>Reinsured</dt><dd>{{ selectedPayload.reinsured || '—' }}</dd></div>
                  <div><dt>Currency</dt><dd>{{ selectedPayload.currency || '—' }}</dd></div>
                  <div><dt>Effective date</dt><dd>{{ formatPolicyDateTime(selectedPayload.policyFrom, selectedPayload.policyFromTime) }}</dd></div>
                </dl>
              </section>
              <section class="review-section">
                <div class="review-section-heading"><h3>Reinsurers</h3><span>Total order: {{ formatAmount(selectedOverview.totalOrderHereon) }}%</span></div>
                <div class="review-list"><div v-for="(row,index) in selectedPayload.reinsurers || []" :key="'announce-reinsurer-' + index"><strong>{{ row.name || '—' }}</strong><span>{{ formatAmount(row.sharePct) }}%</span></div></div>
              </section>
              <section class="review-section">
                <div class="review-section-heading"><h3>Premium calculation</h3><span>{{ selectedPayload.currency || '—' }}</span></div>
                <div class="calculation-list">
                  <div class="calculation-row"><span>Ceded premium</span><strong>{{ formatMoney(selectedOverview.legs.cedantPremium) }}</strong></div>
                  <div class="calculation-row"><span>{{ selectedOverview.legLabels.leg1 }}</span><strong>{{ formatMoney(selectedOverview.displayLegs.leg1) }}</strong></div>
                  <div class="calculation-row"><span>{{ selectedOverview.legLabels.leg2 }}</span><strong>{{ formatMoney(selectedOverview.displayLegs.leg2) }}</strong></div>
                  <div class="calculation-row"><span>Brokerage</span><strong>{{ formatMoney(selectedOverview.displayLegs.leg3) }}</strong></div>
                </div>
              </section>
              <section class="review-section">
                <div class="review-section-heading"><h3>Selected evidence</h3><span>{{ (documentCoverage.selected || []).length }} files</span></div>
                <div class="review-list"><div v-for="row in caseDocuments.filter(file => file.is_selected)" :key="'announce-file-' + row.id"><strong>{{ documentKindLabel(row.kind) }}</strong><span>{{ row.filename }}<template v-if="row.kind !== 'offer'"> · {{ (row.reinsurers || []).map(displayReinsurerName).join(', ') }}</template></span></div></div>
              </section>
              <el-checkbox v-model="announceConfirmed" class="announce-attestation">我已確認所選 Offer Slip 的委任內容，以及各再保人 Signed Slip 或 Confirmation E-mail 所載的承接、比例與條件均對應本案最新內容。</el-checkbox>
              <template #footer><div class="review-footer"><p>After Announce, the case receives a TW Reference and can no longer be edited as a Draft.</p><div><el-button class="secondary-button" :disabled="announcing" @click="announceDialogVisible = false">Back to review</el-button><el-button class="primary-button" :loading="announcing" :disabled="!announceConfirmed" @click="announceSelectedCase">Announce</el-button></div></div></template>
            </el-dialog>
          </template>
          <template v-else-if="activeView === 'case-create'">
            <el-alert v-if="saveMessage" :title="saveMessage" type="success" :closable="false" show-icon></el-alert>
            <el-alert v-if="validationMessage" :title="validationMessage" :type="reviewReady ? 'success' : 'error'" :closable="false" show-icon></el-alert>
            <el-alert v-if="editingOriginalStatus === 'posted'" title="You are editing an Announced case. Save preserves Announced status; record the Accounting notification from the case overview when required." type="warning" :closable="false" show-icon></el-alert>
            <el-alert v-if="editingOriginalStatus === 'reversed'" title="Correct the figures and save. The case moves back to Announced; historical and reversal transactions remain, and the corrected cycle is generated only after a future Production close." type="warning" :closable="false" show-icon></el-alert>
            <!-- Development opens directly with the case sections. -->

            <el-form label-position="top" class="case-form" @submit.prevent>
              <section v-if="isEndorsementDraft" class="overview-card endorsement-editor">
                <div class="section-heading"><div><span class="pending-badge">Endorsement {{ draft.endorsementSeq || '' }}</span><h2>Endorsement details</h2><p>Parent reference: {{ draft.parentTwRef }}</p></div><el-switch v-model="endorsementFieldsUnlocked" inline-prompt active-text="Risk fields unlocked" inactive-text="Risk fields locked"></el-switch></div>
                <div class="form-grid cols-3">
                  <el-form-item label="Effective date" required :class="{ 'is-required-error': fieldInvalid('endoEffectiveDate') }"><el-date-picker v-model="draft.endoEffectiveDate" type="date" value-format="YYYY-MM-DD" placeholder="YYYY-MM-DD"></el-date-picker></el-form-item>
                  <el-form-item label="Endorsement types" required :class="{ 'is-required-error': fieldInvalid('endoTypes') }"><el-select v-model="draft.endoTypes" multiple collapse-tags placeholder="Select"><el-option v-for="item in ['Premium','Sum Insured','Period','Terms','Reinsurer','Other']" :key="item" :label="item" :value="item"></el-option></el-select></el-form-item>
                  <el-form-item label="Endorsement wording" required :class="{ 'is-required-error': fieldInvalid('endoText') }"><el-input v-model="draft.endoText" type="textarea" :rows="4" maxlength="5000" show-word-limit></el-input></el-form-item>
                </div>
              </section>
              <fieldset class="case-fieldset" :disabled="isEndorsementDraft && !endorsementFieldsUnlocked">
              <el-collapse v-model="openSections">
                <el-collapse-item name="risk" title="Risk Details">
                  <div class="form-grid cols-4">
                    <el-form-item label="Reinsurance structure" required :class="{ 'is-required-error': fieldInvalid('reinsuranceStructure') }"><el-select v-model="draft.reinsuranceStructure" clearable placeholder="Select" @change="onStructureSelected"><el-option label="Quota Share" value="QS"></el-option><el-option label="Excess of Loss" value="XOL"></el-option><el-option label="Treaty" value="TREATY"></el-option></el-select></el-form-item>
                    <el-form-item label="Case owner"><el-select v-model="draft.ownerPersonnelId" filterable clearable placeholder="Select active Personnel" @change="onOwnerSelected"><el-option v-for="item in personnelRecords.filter(row => row.isActive)" :key="'owner-' + item.id" :label="item.name" :value="item.id"></el-option></el-select></el-form-item>
                    <el-form-item label="AE" required :class="{ 'is-required-error': fieldInvalid('ae') }"><el-select v-model="draft.ae" filterable clearable placeholder="Select AE"><el-option v-for="item in masterOptions('ae', draft.ae)" :key="item.id" :label="item.historical ? item.name + ' (historical)' : item.name" :value="item.name"></el-option></el-select></el-form-item>
                    <el-form-item label="Currency" required :class="{ 'is-required-error': fieldInvalid('currency') }"><el-select v-model="draft.currency" clearable placeholder="Select"><el-option label="TWD" value="TWD"></el-option><el-option label="USD" value="USD"></el-option><el-option label="EUR" value="EUR"></el-option><el-option label="JPY" value="JPY"></el-option><el-option label="GBP" value="GBP"></el-option><el-option label="HKD" value="HKD"></el-option><el-option label="MYR" value="MYR"></el-option></el-select></el-form-item>
                    <el-form-item label="Class" required :class="{ 'is-required-error': fieldInvalid('classOfBusiness') }"><el-select v-model="draft.classOfBusiness" filterable clearable placeholder="Select class" @change="onClassSelected"><el-option v-for="item in masterOptions('class', draft.classOfBusiness)" :key="item.id" :label="item.historical ? item.name + ' (historical)' : (item.code ? item.name + ' · ' + item.code : item.name)" :value="item.name"></el-option></el-select></el-form-item>
                    <el-form-item label="New / Renew" required :class="{ 'is-required-error': fieldInvalid('newOrRenew') }"><el-select v-model="draft.newOrRenew" clearable placeholder="Select"><el-option label="New" value="New"></el-option><el-option label="Renew" value="Renew"></el-option></el-select></el-form-item>
                    <el-form-item label="Type" required :class="{ 'is-required-error': fieldInvalid('type') }"><div style="display:flex;width:100%;gap:6px;align-items:stretch;"><el-input v-model="draft.typePrefix" style="min-width:0;flex:1;" maxlength="120" placeholder="e.g. Fire / Lightning" @input="recomputeType"></el-input><span style="flex:0 0 160px;display:flex;align-items:center;padding:6px 9px;border:1px solid var(--border);border-radius:8px;background:var(--surface-card);color:var(--muted);font-size:12px;line-height:1.25;">{{ ({ QS: 'Facultative Reinsurance', XOL: 'Excess of Loss Facultative Reinsurance', TREATY: 'Reinsurance Treaty' })[draft.reinsuranceStructure] || 'Select structure' }}</span></div><div style="margin-top:6px;color:var(--muted);font-size:12px;line-height:1.4;">The structure suffix is locked. Change it using Reinsurance structure.</div></el-form-item>
                    <el-form-item label="Reinsured" required :class="{ 'is-required-error': fieldInvalid('reinsured') }"><el-select v-model="draft.reinsured" filterable clearable placeholder="Select reinsured"><el-option v-for="item in masterOptions('reinsured', draft.reinsured)" :key="item.id" :label="item.historical ? item.name + ' (historical)' : item.name" :value="item.name"></el-option></el-select></el-form-item>
                    <el-form-item label="Original insured (EN)" required :class="{ 'is-required-error': fieldInvalid('originalInsured') }"><el-input v-model="draft.originalInsured" maxlength="240"></el-input></el-form-item>
                    <el-form-item label="Effective date" required :class="{ 'is-required-error': fieldInvalid('policyFrom') }"><div class="policy-date-time"><el-date-picker v-model="draft.policyFrom" type="date" value-format="YYYY-MM-DD" placeholder="YYYY-MM-DD"></el-date-picker><el-select v-model="draft.policyFromTime" aria-label="Effective time"><el-option label="12:00" value="12:00"></el-option><el-option label="00:00" value="00:00"></el-option></el-select></div></el-form-item>
                    <el-form-item label="Expiration date" required :class="{ 'is-required-error': fieldInvalid('policyTo') }"><div class="policy-date-time"><el-date-picker v-model="draft.policyTo" type="date" value-format="YYYY-MM-DD" placeholder="YYYY-MM-DD"></el-date-picker><el-select v-model="draft.policyToTime" aria-label="Expiration time"><el-option label="12:00" value="12:00"></el-option><el-option label="00:00" value="00:00"></el-option></el-select></div></el-form-item>
                  </div>
                  <div class="repeat-block">
                    <div class="repeat-heading"><div><h3>Situation <span class="required-star">*</span></h3><p>Risk Address and 3–6 digit Postcode form one address record.</p></div><el-button class="secondary-button" @click="addSituation">+ Add situation</el-button></div>
                    <div v-for="(row,index) in draft.situations" :key="row.clientKey" class="repeat-row situation-row">
                      <span class="row-number">{{ index + 1 }}.</span><el-input v-model="row.address" class="required-control" :class="{ 'required-invalid': rowInvalid('situations', index, 'address') }" maxlength="500" placeholder="Risk Address"></el-input>
                      <el-input v-model="row.postcode" class="required-control" :class="{ 'required-invalid': rowInvalid('situations', index, 'postcode', 'postcode') }" maxlength="6" inputmode="numeric" placeholder="Postcode"></el-input>
                      <el-button text type="danger" :disabled="draft.situations.length === 1" @click="removeSituation(index)">Remove</el-button>
                    </div>
                  </div>
                  <el-form-item label="Interest" required :class="{ 'is-required-error': fieldInvalid('interest') }"><el-input v-model="draft.interest" type="textarea" :rows="3" maxlength="3000" show-word-limit></el-input></el-form-item>
                </el-collapse-item>

                <el-collapse-item name="security" title="Schedule of Security">
                  <div v-for="(row,index) in draft.reinsurers" :key="row.clientKey" class="repeat-card">
                    <div class="repeat-heading"><h3>Reinsurer {{ index + 1 }}</h3><el-button text type="danger" :disabled="draft.reinsurers.length === 1" @click="removeReinsurer(index)">Remove</el-button></div>
                    <div class="form-grid cols-4">
                      <el-form-item label="Reinsurer" required :class="{ 'is-required-error': rowInvalid('reinsurers', index, 'name') }"><el-select v-model="row.name" filterable clearable placeholder="Select reinsurer" @change="onReinsurerSelected"><el-option v-for="item in masterOptions('reinsurer', row.name)" :key="item.id" :label="item.historical ? item.name + ' (historical)' : item.name" :value="item.name"></el-option></el-select></el-form-item>
                      <el-form-item label="Order hereon (%)" required :class="{ 'is-required-error': rowInvalid('reinsurers', index, 'sharePct') }"><el-input-number v-model="row.sharePct" :min="0" :max="100" :precision="4" :controls="false" placeholder="Empty by default"></el-input-number></el-form-item>
                      <el-form-item label="Foreign RI Broker"><el-select v-model="row.foreignBroker" filterable clearable placeholder="Select foreign RI broker"><el-option v-for="item in masterOptions('foreign_broker', row.foreignBroker)" :key="item.id" :label="item.historical ? item.name + ' (historical)' : item.name" :value="item.name"></el-option></el-select></el-form-item>
                      <el-form-item label="Reinsurer Ref."><el-input v-model="row.settlementRef" maxlength="160" placeholder="Settlement reference"></el-input></el-form-item>
                      <el-form-item label="Payment terms override (days)"><el-input-number v-model="row.paymentTermsDays" :min="15" :precision="0" :controls="false" placeholder="Use Case default"></el-input-number></el-form-item>
                    </div>
                  </div>
                  <el-button class="secondary-button" @click="addReinsurer">+ Add reinsurer</el-button>
                </el-collapse-item>

                <el-collapse-item name="terms" title="Terms & Conditions">
                  <el-alert v-if="allFacilityReinsurers" class="case-readiness-alert" type="info" :closable="false" show-icon title="All selected reinsurers are Facility arrangements" description="Their standard terms are applied through fixed clauses; the Development Facility rules are active for this case."></el-alert>
                  <div class="form-grid cols-2">
                    <el-form-item label="Limit of Liability" required :class="{ 'is-required-error': fieldInvalid('limitOfLiability') }"><el-input-number v-model="draft.limitOfLiability" :min="0" :controls="false"></el-input-number></el-form-item>
                    <el-form-item label="Aggregate Limit (Policy Limit)"><el-input-number v-model="draft.aggregateLimit" :min="0" :controls="false"></el-input-number></el-form-item>
                    <el-form-item label="Basis of Valuation"><el-select v-model="draft.basisOfValuation" clearable placeholder="Select"><el-option label="Actual Cash Value" value="Actual Cash Value"></el-option><el-option label="Replacement Value" value="Replacement Value"></el-option><el-option label="Other" value="Other"></el-option></el-select></el-form-item>
                  </div>
                  <el-form-item v-if="draft.basisOfValuation === 'Other'" label="Basis of Valuation — Other" required :class="{ 'is-required-error': fieldInvalid('basisOfValuationOther') }"><el-input v-model="draft.basisOfValuationOther" maxlength="1000"></el-input></el-form-item>
                  <el-form-item v-if="draft.reinsuranceStructure !== 'QS'" label="Underlying Limits (Primary Layer)"><el-input v-model="draft.underlyingLimits" type="textarea" :rows="2" maxlength="3000"></el-input></el-form-item>
                  <el-form-item label="Sub-Limits"><el-input v-model="draft.subLimits" type="textarea" :rows="2" maxlength="3000"></el-input></el-form-item>
                  <el-form-item label="Deductibles" required :class="{ 'is-required-error': fieldInvalid('deductibles') }"><el-input v-model="draft.deductibles" type="textarea" :rows="3" maxlength="3000"></el-input></el-form-item>
                  <el-form-item label="Original Exclusions"><el-input v-model="draft.originalExclusions" type="textarea" :rows="3" maxlength="5000"></el-input></el-form-item>
                  <el-form-item label="Original Conditions" required :class="{ 'is-required-error': fieldInvalid('originalConditions') }"><el-input v-model="draft.originalConditions" type="textarea" :rows="3" maxlength="5000"></el-input></el-form-item>
                  <el-form-item label="Reinsured's Retention"><el-input v-model="draft.reinsuredRetention" type="textarea" :rows="2" maxlength="3000"></el-input></el-form-item>
                  <el-form-item label="Reinstatement Provisions"><el-input v-model="draft.reinstatementProvisions" type="textarea" :rows="2" maxlength="3000"></el-input></el-form-item>
                  <el-form-item label="Indemnity Period"><el-input v-model="draft.indemnityPeriod" maxlength="1000"></el-input></el-form-item>
                  <el-form-item label="Express Warranties"><el-input v-model="draft.expressWarranties" type="textarea" :rows="2" maxlength="3000"></el-input></el-form-item>
                  <el-form-item label="Conditions Precedent"><el-input v-model="draft.conditionsPrecedent" type="textarea" :rows="2" maxlength="3000"></el-input></el-form-item>
                  <el-form-item label="Subjectivities"><el-input v-model="draft.subjectivities" type="textarea" :rows="2" maxlength="3000"></el-input></el-form-item>
                </el-collapse-item>

                <el-collapse-item name="occupation" title="Occupation & Construction">
                  <div class="form-grid cols-2"><el-form-item label="Occupation" required :class="{ 'is-required-error': fieldInvalid('occupation') }"><el-input v-model="draft.occupation" type="textarea" :rows="3" maxlength="3000"></el-input></el-form-item><el-form-item label="Construction" required :class="{ 'is-required-error': fieldInvalid('construction') }"><el-input v-model="draft.construction" type="textarea" :rows="3" maxlength="3000"></el-input></el-form-item></div>
                </el-collapse-item>

                <el-collapse-item name="sumInsured" title="Breakdown of Sum Insured">
                  <div v-for="(row,index) in draft.sumInsured" :key="row.clientKey" class="repeat-row sum-row">
                    <span class="row-number">{{ index + 1 }}.</span><el-input v-model="row.category" class="required-control" :class="{ 'required-invalid': rowInvalid('sumInsured', index, 'category') }" maxlength="240" placeholder="Interest insured *"></el-input>
                    <el-input-number v-model="row.amount" class="required-control" :class="{ 'required-invalid': rowInvalid('sumInsured', index, 'amount') }" :min="0" :controls="false" placeholder="Amount *"></el-input-number>
                    <el-select v-if="!allFacilityReinsurers" v-model="row.locationIndex" placeholder="Situation"><el-option v-for="(situation,situationIndex) in draft.situations" :key="'sum-location-' + situation.clientKey" :label="'Situation ' + (situationIndex + 1) + (situation.address ? ' · ' + situation.address : '')" :value="situationIndex"></el-option></el-select>
                    <el-button text type="danger" :disabled="draft.sumInsured.length === 1" @click="removeSumInsured(index)">Remove</el-button>
                  </div>
                  <el-button class="secondary-button" @click="addSumInsured">+ Add item</el-button>
                </el-collapse-item>

                <el-collapse-item name="loss" title="Loss Record">
                  <div class="form-grid cols-2"><el-form-item label="Loss record advised by broker on" required :class="{ 'is-required-error': fieldInvalid('lossAdvisedDate') }"><el-date-picker v-model="draft.lossAdvisedDate" type="date" value-format="YYYY-MM-DD" placeholder="YYYY-MM-DD"></el-date-picker></el-form-item><el-form-item label="Past year(s)" required :class="{ 'is-required-error': fieldInvalid('lossRecordYears', 'positiveInteger') }"><el-input-number v-model="draft.lossRecordYears" :min="1" :precision="0" :controls="false"></el-input-number></el-form-item></div>
                  <el-alert class="case-readiness-alert" :title="lossRecordSummary" type="info" :closable="false" show-icon></el-alert>
                  <p v-if="draft.lossRecord.length === 0" class="document-help">Clean — no losses recorded.</p>
                  <div v-for="(row,index) in draft.lossRecord" :key="row.clientKey" class="repeat-card">
                    <div class="repeat-heading"><h3>Loss {{ index + 1 }}</h3><el-button text type="danger" @click="removeLossRecord(index)">Remove</el-button></div>
                    <div class="form-grid cols-3">
                      <el-form-item label="Date of Loss" required :class="{ 'is-required-error': lossRowInvalid(index, 'date') }"><el-date-picker v-model="row.date" type="date" value-format="YYYY-MM-DD" placeholder="YYYY-MM-DD"></el-date-picker></el-form-item>
                      <el-form-item label="Cause" required :class="{ 'is-required-error': lossRowInvalid(index, 'cause') }"><el-input v-model="row.cause" maxlength="1000" placeholder="Cause of loss"></el-input></el-form-item>
                      <el-form-item label="Loss Paid" required :class="{ 'is-required-error': lossRowInvalid(index, 'lossPaid') }"><el-input-number v-model="row.lossPaid" :min="0" :controls="false"></el-input-number></el-form-item>
                    </div>
                  </div>
                  <el-button class="secondary-button" @click="addLossRecord">+ Add loss</el-button>
                  <el-form-item label="Additional loss record notes"><el-input v-model="draft.lossRecordText" type="textarea" :rows="3" maxlength="5000" placeholder="Optional notes"></el-input></el-form-item>
                </el-collapse-item>

                <el-collapse-item name="specialAgreement" title="Special Agreement">
                  <el-form-item label="Special Agreement"><el-input v-model="draft.specialAgreement" type="textarea" :rows="5" maxlength="5000" placeholder="Optional special agreement"></el-input></el-form-item>
                </el-collapse-item>

                <el-collapse-item name="cedantPremium" title="Cedant Premium">
                  <div class="form-grid cols-4"><el-form-item label="100% Premium" required :class="{ 'is-required-error': fieldInvalid('originalPremium') }"><el-input-number v-model="draft.originalPremium" :min="0" :controls="false"></el-input-number></el-form-item><el-form-item label="Payment terms (days)" required :class="{ 'is-required-error': fieldInvalid('paymentTermsDays') }"><el-input-number v-model="draft.paymentTermsDays" :min="15" :precision="0" :controls="false"></el-input-number><small>Calendar days. Cedant due = Terms − 15; Reinsurer due = Terms − 10.</small></el-form-item><el-form-item label="Ceding commission (%)" required :class="{ 'is-required-error': fieldInvalid('riCommPct') }"><el-input-number v-model="draft.riCommPct" :min="0" :max="100" :precision="4" :controls="false"></el-input-number></el-form-item><el-form-item label="Tax (%)" required :class="{ 'is-required-error': fieldInvalid('taxPct') }"><el-input-number v-model="draft.taxPct" :min="0" :max="100" :precision="4" :controls="false"></el-input-number></el-form-item></div>
                  <el-form-item label="Statement No."><el-input v-model="draft.statementNo" maxlength="160" placeholder="Cedant reconciliation reference"></el-input></el-form-item>
                  <div class="repeat-card">
                    <div class="repeat-heading"><div><h3>Premium Installments</h3><p>Optionally assign Production Report performance months. Calculated Income uses the current brokerage amount; rounding difference goes to the first installment.</p></div><el-switch v-model="draft.installmentEnabled" inline-prompt active-text="On" inactive-text="Off" @change="onInstallmentToggle"></el-switch></div>
                    <template v-if="draft.installmentEnabled">
                      <el-alert class="case-readiness-alert" :title="installmentStatus.message" :type="installmentStatus.valid ? 'success' : (reviewAttempted ? 'error' : 'warning')" :closable="false" show-icon></el-alert>
                      <div v-for="(row,index) in draft.performanceInstallments" :key="row.clientKey" class="repeat-card">
                        <div class="repeat-heading"><h3>Installment {{ index + 1 }}</h3><el-button text type="danger" @click="removeInstallment(index)">Remove</el-button></div>
                        <div class="form-grid cols-3">
                          <el-form-item label="Performance month" required :class="{ 'is-required-error': installmentRowInvalid(index, 'performanceMonth') }"><el-date-picker v-model="row.performanceMonth" type="month" value-format="YYYY-MM" format="MMM YYYY" placeholder="YYYY-MM"></el-date-picker></el-form-item>
                          <el-form-item label="Payment base date" required :class="{ 'is-required-error': installmentRowInvalid(index, 'paymentBaseDate') }"><el-date-picker v-model="row.paymentBaseDate" type="date" value-format="YYYY-MM-DD" placeholder="YYYY-MM-DD"></el-date-picker></el-form-item>
                          <el-form-item label="Installment terms override"><el-input-number v-model="row.paymentTermsDays" :min="15" :precision="0" :controls="false" placeholder="Use Case default"></el-input-number></el-form-item>
                          <el-form-item v-if="Number(draft.originalPremium || 0) === 0" label="Ratio (%)" required :class="{ 'is-required-error': installmentRowInvalid(index, 'ratio') }"><el-input-number v-model="row.ratio" :min="0" :max="100" :precision="4" :controls="false"></el-input-number></el-form-item>
                          <el-form-item v-else label="Premium" required :class="{ 'is-required-error': installmentRowInvalid(index, 'premium') }"><el-input-number v-model="row.premium" :min="0" :controls="false"></el-input-number></el-form-item>
                          <el-form-item label="Income (calculated)"><strong>{{ draft.currency || '—' }} {{ formatMoney((installmentAllocations[index] || {}).income) }}</strong></el-form-item>
                        </div>
                        <div class="form-grid cols-3">
                          <el-form-item v-for="(reinsurer,reinsurerIndex) in draft.reinsurers" :key="'terms-' + row.clientKey + '-' + reinsurerIndex" :label="(reinsurer.name || ('Reinsurer ' + (reinsurerIndex + 1))) + ' terms override'"><el-input-number v-model="row.reinsurerPaymentTerms['r' + (reinsurerIndex + 1)]" :min="15" :precision="0" :controls="false" placeholder="Use higher-level default"></el-input-number></el-form-item>
                        </div>
                      </div>
                      <el-button class="secondary-button" @click="addInstallment">+ Add installment</el-button>
                    </template>
                  </div>
                </el-collapse-item>

                <el-collapse-item name="reinsurerPremium" title="Reinsurer Premium">
                  <div v-for="(row,index) in draft.reinsurers" :key="'premium-' + row.clientKey" class="repeat-card">
                    <h3>{{ row.name || ('Reinsurer ' + (index + 1)) }}</h3>
                    <div class="form-grid cols-3"><el-form-item label="Premium" required :class="{ 'is-required-error': rowInvalid('reinsurers', index, 'premium') }"><el-input-number v-model="row.premium" :min="0" :controls="false"></el-input-number></el-form-item><el-form-item label="Deductions (%)" required :class="{ 'is-required-error': rowInvalid('reinsurers', index, 'riCommPct') }"><el-input-number v-model="row.riCommPct" :min="0" :max="100" :precision="4" :controls="false"></el-input-number></el-form-item><el-form-item label="Tax (%)" required :class="{ 'is-required-error': rowInvalid('reinsurers', index, 'taxPct') }"><el-input-number v-model="row.taxPct" :min="0" :max="100" :precision="4" :controls="false"></el-input-number></el-form-item></div>
                  </div>
                </el-collapse-item>

                <el-collapse-item name="split" title="Performance Split (internal only)">
                  <div class="repeat-card">
                    <div class="repeat-heading"><div><h3>Production credit</h3><p>Split this case between exactly two people. This internal allocation is never shown on external documents or SOA.</p></div><el-switch v-model="draft.splitEnabled" inline-prompt active-text="On" inactive-text="Off" @change="onSplitToggle"></el-switch></div>
                    <template v-if="draft.splitEnabled">
                      <el-alert class="case-readiness-alert" :title="splitStatus.message" :type="splitStatus.valid ? 'success' : (reviewAttempted ? 'error' : 'warning')" :closable="false" show-icon></el-alert>
                      <p class="document-help">Select active, split-eligible Personnel records. Each saved split keeps the Personnel ID and a name snapshot; historical names remain visible when an older Draft is opened.</p>
                      <div class="form-grid cols-2">
                        <div v-for="(row,index) in draft.splitParties" :key="row.clientKey" class="repeat-card">
                          <h3>Party {{ index === 0 ? 'A' : 'B' }}</h3>
                          <el-form-item label="Person" required :class="{ 'is-required-error': splitPartyInvalid(index, 'name') }"><el-select v-model="row.name" filterable clearable placeholder="Select person" @change="onSplitPersonSelected(row)"><el-option v-for="item in splitPersonOptions(row)" :key="item.id" :label="item.historical ? item.name + ' (historical)' : item.name + ' · ' + departmentLabel(item.department)" :value="item.name"></el-option></el-select></el-form-item>
                          <el-form-item label="Split (%)" required :class="{ 'is-required-error': splitPartyInvalid(index, 'pct') }"><el-input-number v-model="row.pct" :min="0" :max="100" :precision="4" :controls="false"></el-input-number></el-form-item>
                        </div>
                      </div>
                    </template>
                  </div>
                </el-collapse-item>

                <el-collapse-item name="conditions" title="Reinsurance Conditions">
                  <div class="repeat-heading"><div><h3>Clauses</h3><p>Universal clauses are always included. Fixed clauses are copied from the selected reinsurer; later MDM changes do not rewrite this saved case.</p></div></div>
                  <div class="review-list">
                    <div v-for="clause in draft.clauseDetails" :key="'clause-' + clause.code">
                      <strong>{{ clause.code }}</strong>
                      <span>{{ clause.title }}</span>
                      <el-tag size="small" effect="plain">{{ clauseSourceLabel(clause.code) }}</el-tag>
                      <el-button v-if="isManualClause(clause.code)" text type="danger" @click="removeCaseClause(clause.code)">Remove</el-button>
                    </div>
                  </div>
                  <el-alert v-if="!hasNonFacilityReinsurer" class="case-readiness-alert" type="info" :closable="false" show-icon title="Facility clause rules" description="Case-specific clauses can be added after at least one non-Facility reinsurer is selected."></el-alert>
                  <div v-else class="repeat-card" style="margin-top:16px;">
                    <div class="repeat-heading"><div><h3>Add case-specific clause</h3><p>Manual clauses apply only to this case snapshot.</p></div></div>
                    <div class="form-grid cols-3">
                      <el-form-item label="Clause code"><el-input v-model="caseClauseDraft.code" maxlength="80" placeholder="e.g. LPO1234"></el-input></el-form-item>
                      <el-form-item label="Clause name"><el-input v-model="caseClauseDraft.title" maxlength="300" placeholder="Full clause name"></el-input></el-form-item>
                      <el-form-item label=" "><el-button class="secondary-button" @click="addCaseClause">+ Add clause</el-button></el-form-item>
                    </div>
                  </div>
                </el-collapse-item>
              </el-collapse>
              </fieldset>

              <div class="form-actions"><div><strong>Draft rules</strong><p>Drafts may be saved with incomplete business fields. Review & confirm checks readiness only; it does not change status in this milestone.</p></div><div class="action-buttons"><el-button class="secondary-button" @click="reviewAndConfirm">Review & confirm</el-button><el-button class="primary-button" :loading="saving" @click="saveDraft">{{ isEditing ? 'Save changes' : 'Save draft' }}</el-button></div></div>
            </el-form>

            <el-dialog v-model="reviewDialogVisible" class="review-dialog" width="min(920px, 94vw)" :close-on-click-modal="false">
              <template #header>
                <div class="review-heading"><span class="pending-badge">Read-only review</span><h2>Review case details</h2><p>Check the summary below. This step does not announce, confirm, or assign a reference.</p></div>
              </template>

              <div class="review-status"><span>Status after saving</span><strong>Draft</strong></div>
              <section class="review-section">
                <h3>Risk details</h3>
                <dl class="review-grid">
                  <div><dt>Structure</dt><dd>{{ structureLabel(draft.reinsuranceStructure) }}</dd></div><div><dt>Class</dt><dd>{{ draft.classOfBusiness }}</dd></div>
                  <div><dt>AE</dt><dd>{{ draft.ae }}</dd></div><div><dt>Currency</dt><dd>{{ draft.currency }}</dd></div>
                  <div><dt>New / Renew</dt><dd>{{ draft.newOrRenew }}</dd></div><div><dt>Type</dt><dd>{{ draft.type }}</dd></div>
                  <div><dt>Reinsured</dt><dd>{{ draft.reinsured }}</dd></div><div><dt>Original insured</dt><dd>{{ draft.originalInsured }}</dd></div>
                  <div><dt>Policy period</dt><dd>{{ formatPolicyDateTime(draft.policyFrom, draft.policyFromTime) }} ~ {{ formatPolicyDateTime(draft.policyTo, draft.policyToTime) }}</dd></div><div><dt>Limit of Liability</dt><dd>{{ draft.currency }} {{ formatAmount(draft.limitOfLiability) }}</dd></div>
                  <div v-if="draft.aggregateLimit !== null"><dt>Aggregate Limit</dt><dd>{{ draft.currency }} {{ formatAmount(draft.aggregateLimit) }}</dd></div><div v-if="draft.reinsuranceStructure !== 'QS' && draft.underlyingLimits"><dt>Underlying Limits</dt><dd>{{ draft.underlyingLimits }}</dd></div>
                </dl>
              </section>

              <section class="review-section">
                <h3>Situation & coverage</h3>
                <div class="review-list"><div v-for="(row,index) in draft.situations" :key="'review-situation-' + row.clientKey"><strong>Situation {{ index + 1 }}</strong><span>{{ row.address }} · {{ row.postcode }}</span></div></div>
                <dl class="review-grid review-grid-single"><div><dt>Interest</dt><dd>{{ draft.interest }}</dd></div><div v-if="draft.subLimits"><dt>Sub-Limits</dt><dd>{{ draft.subLimits }}</dd></div><div><dt>Deductibles</dt><dd>{{ draft.deductibles }}</dd></div><div v-if="draft.reinstatementProvisions"><dt>Reinstatement Provisions</dt><dd>{{ draft.reinstatementProvisions }}</dd></div><div v-if="draft.indemnityPeriod"><dt>Indemnity Period</dt><dd>{{ draft.indemnityPeriod }}</dd></div><div><dt>Occupation</dt><dd>{{ draft.occupation }}</dd></div><div><dt>Construction</dt><dd>{{ draft.construction }}</dd></div></dl>
              </section>

              <section class="review-section">
                <div class="review-section-heading"><h3>Schedule of security</h3><span>Total order: {{ formatAmount(totalOrderHereon) }}%</span></div>
                <div class="review-list"><div v-for="(row,index) in draft.reinsurers" :key="'review-reinsurer-' + row.clientKey"><strong>{{ row.name }}</strong><span>{{ formatAmount(row.sharePct) }}% · Premium {{ draft.currency }} {{ formatAmount(row.premium) }} · Deductions {{ formatAmount(row.riCommPct) }}% · Tax {{ formatAmount(row.taxPct) }}%</span></div></div>
              </section>

              <section class="review-section">
                <div class="review-section-heading"><h3>Sum insured & premium</h3><span>Total sum insured: {{ draft.currency }} {{ formatAmount(totalSumInsured) }}</span></div>
                <div class="review-list"><div v-for="(row,index) in draft.sumInsured" :key="'review-sum-' + row.clientKey"><strong>{{ row.category }}</strong><span>{{ draft.currency }} {{ formatAmount(row.amount) }}<template v-if="!allFacilityReinsurers"> · Situation {{ Number(row.locationIndex || 0) + 1 }}</template></span></div></div>
                <dl class="review-grid"><div><dt>100% Premium</dt><dd>{{ draft.currency }} {{ formatAmount(draft.originalPremium) }}</dd></div><div><dt>Payment terms</dt><dd>{{ formatAmount(draft.paymentTermsDays) }} days</dd></div><div><dt>Ceding commission</dt><dd>{{ formatAmount(draft.riCommPct) }}%</dd></div><div><dt>Cedant tax</dt><dd>{{ formatAmount(draft.taxPct) }}%</dd></div></dl>
                <div v-if="draft.installmentEnabled" class="review-list"><div v-for="(row,index) in installmentAllocations" :key="'review-installment-' + row.id"><strong>Installment {{ index + 1 }} · {{ row.performanceMonth }}</strong><span>{{ Number(draft.originalPremium || 0) === 0 ? formatAmount(row.ratio * 100) + '%' : draft.currency + ' ' + formatAmount(row.premium) }} · Income {{ draft.currency }} {{ formatMoney(row.income) }}</span></div></div>
              </section>

              <section v-if="draft.splitEnabled" class="review-section"><div class="review-section-heading"><h3>Performance Split</h3><span>Internal only</span></div><div class="review-list"><div v-for="(row,index) in draft.splitParties" :key="'review-split-' + row.clientKey"><strong>Party {{ index === 0 ? 'A' : 'B' }} · {{ row.name }}</strong><span>{{ formatAmount(row.pct) }}%</span></div></div></section>

              <section class="review-section"><h3>Loss record</h3><dl class="review-grid"><div><dt>Advised by broker on</dt><dd>{{ draft.lossAdvisedDate }}</dd></div><div><dt>Summary</dt><dd>{{ lossRecordSummary }}</dd></div><div v-if="draft.lossRecordText" class="review-wide"><dt>Additional notes</dt><dd>{{ draft.lossRecordText }}</dd></div></dl><div v-if="draft.lossRecord.length" class="review-list"><div v-for="(row,index) in draft.lossRecord" :key="'review-loss-' + row.clientKey"><strong>Loss {{ index + 1 }} · {{ row.date }}</strong><span>{{ row.cause }} · {{ draft.currency || '—' }} {{ formatAmount(row.lossPaid) }}</span></div></div><p v-else class="document-help">Clean — no losses recorded.</p></section>

              <section class="review-section"><h3>Reinsurance conditions</h3><div class="review-list"><div v-for="clause in draft.clauseDetails" :key="'review-clause-' + clause.code"><strong>{{ clause.code }}</strong><span>{{ clause.title }}</span></div></div></section>

              <template #footer><div class="review-footer"><p>Saving keeps this case as Draft. Announce and Confirm remain unavailable.</p><div><el-button class="secondary-button" @click="reviewDialogVisible = false">Back to edit</el-button><el-button class="primary-button" :loading="saving" @click="saveReviewedDraft">{{ isEditing ? 'Save changes' : 'Save draft' }}</el-button></div></div></template>
            </el-dialog>
          </template>
</template>
