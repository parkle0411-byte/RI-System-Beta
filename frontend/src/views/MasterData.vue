<script setup>
// 移植自 Alpha index.html 的 activeView === 'mdm' 與 app.js 的主檔函式
// （loadMasterData、openMasterDialog、add/removeMdmFixedClause、add/removeMdmRating、masterPayloadFromForm、saveMasterRecord、toggleMasterStatus 等）。
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiFetch } from '../api'
import { can } from '../auth'
import { UNIVERSAL_CLAUSES, compareClauses, normalizeClauseList, normalizeRatingList } from '../alpha/constants'
import { jsonOrThrow, reportWriteError } from '../alpha/format'
import { shell } from '../alpha/shell'

const masterTypes = [
  { value: 'reinsurer', label: 'Reinsurer', tabLabel: 'Reinsurers' },
  { value: 'clause', label: 'Clause', tabLabel: 'Clauses' },
  { value: 'reinsured', label: 'Cedant', tabLabel: 'Cedants' },
  { value: 'foreign_broker', label: 'Foreign RI Broker', tabLabel: 'Foreign RI Brokers' },
  { value: 'ae', label: 'Account Executive', tabLabel: 'Account Executive' },
  { value: 'class', label: 'Class', tabLabel: 'Classes' }
]
const mdmLoading = ref(false)
const mdmSaving = ref(false)
const mdmDialogVisible = ref(false)
const editingMasterId = ref(null)
const editingMasterRowVersion = ref(null)
const activeMdmType = ref('reinsurer')
const mdmRecords = ref([])
const mdmCounts = ref({ ae: 0, reinsurer: 0, reinsured: 0, class: 0, foreign_broker: 0, clause: 0 })
const mdmForm = reactive({ entityType: 'ae', code: '', name: '', abbreviation: '', address: '', fixedClauses: [], ratings: [] })
const mdmClauseDraft = reactive({ code: '', title: '' })
const mdmRatingDraft = reactive({ agency: '', grade: '', outlook: '', ratingType: '', asOfDate: '', legalEntity: '', sourceUrl: '', checkedAt: '', status: '' })

const filteredMasterRecords = computed(() => {
  const records = mdmRecords.value.filter((row) => row.entityType === activeMdmType.value)
  return activeMdmType.value === 'clause' ? [...records].sort(compareClauses) : records
})

function masterTypeLabel(value) {
  return masterTypes.find((item) => item.value === value)?.label || value
}
function isUniversalClauseCode(code) {
  return UNIVERSAL_CLAUSES.some((row) => row.code === String(code || '').toUpperCase())
}
function clauseSourceType(code) {
  return isUniversalClauseCode(code) ? 'Universal' : 'Standard'
}
function clauseUsedByReinsurers(code) {
  const normalized = String(code || '').toUpperCase()
  return mdmRecords.value
    .filter((row) => row.entityType === 'reinsurer' && Array.isArray(row.payload?.fixedClauses) && row.payload.fixedClauses.some((c) => String(c.code || '').toUpperCase() === normalized))
    .map((row) => row.payload?.abbreviation || row.name)
    .sort((a, b) => a.localeCompare(b))
}
function availableClauseOptions() {
  const alreadyAdded = new Set((mdmForm.fixedClauses || []).map((row) => String(row.code || '').toUpperCase()))
  return mdmRecords.value
    .filter((row) => row.entityType === 'clause' && row.isActive && !isUniversalClauseCode(row.code) && !alreadyAdded.has(String(row.code || '').toUpperCase()))
    .map((row) => ({ code: row.code, title: row.name }))
    .sort(compareClauses)
}
function onMdmClauseDraftSelect(code) {
  const match = mdmRecords.value.find((row) => row.entityType === 'clause' && row.code === code)
  mdmClauseDraft.title = match ? match.name : ''
}

async function loadMasterData() {
  mdmLoading.value = true; shell.error = ''
  try {
    const response = await apiFetch('/api/master-data', { headers: { Accept: 'application/json' } })
    const body = await response.json()
    if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
    mdmRecords.value = Array.isArray(body.records) ? body.records : []
    mdmCounts.value = body.counts || mdmCounts.value
  } catch (err) {
    shell.error = err instanceof Error ? err.message : String(err)
    ElMessage.error(shell.error)
  } finally { mdmLoading.value = false }
}

function openMasterDialog(row = null) {
  editingMasterId.value = row ? Number(row.id) : null
  editingMasterRowVersion.value = row ? Number(row.rowVersion) : null
  Object.assign(mdmForm, row
    ? {
        entityType: row.entityType, code: row.code || '', name: row.name || '',
        abbreviation: row.payload?.abbreviation || '', address: row.payload?.address || '',
        fixedClauses: normalizeClauseList(row.payload?.fixedClauses), ratings: normalizeRatingList(row.payload?.ratings)
      }
    : { entityType: activeMdmType.value, code: '', name: '', abbreviation: '', address: '', fixedClauses: [], ratings: [] })
  Object.assign(mdmClauseDraft, { code: '', title: '' })
  Object.assign(mdmRatingDraft, { agency: '', grade: '', outlook: '', ratingType: '', asOfDate: '', legalEntity: '', sourceUrl: '', checkedAt: '', status: '' })
  mdmDialogVisible.value = true
}

function addMdmFixedClause() {
  const clause = normalizeClauseList([mdmClauseDraft])[0]
  if (!clause) return ElMessage.error('Enter both Clause code and Clause name')
  if (UNIVERSAL_CLAUSES.some((row) => row.code === clause.code)) return ElMessage.error(`${clause.code} is included in every case`)
  if (mdmForm.fixedClauses.some((row) => row.code === clause.code)) return ElMessage.error('This Clause code already exists for the reinsurer')
  mdmForm.fixedClauses.push(clause)
  mdmForm.fixedClauses.sort(compareClauses)
  Object.assign(mdmClauseDraft, { code: '', title: '' })
}
function removeMdmFixedClause(index) { mdmForm.fixedClauses.splice(index, 1) }
function addMdmRating() {
  const rating = normalizeRatingList([mdmRatingDraft])[0]
  if (!rating) return ElMessage.error('Enter both Rating agency and Grade')
  mdmForm.ratings.push(rating)
  Object.assign(mdmRatingDraft, { agency: '', grade: '', outlook: '', ratingType: '', asOfDate: '', legalEntity: '', sourceUrl: '', checkedAt: '', status: '' })
}
function removeMdmRating(index) { mdmForm.ratings.splice(index, 1) }
function masterPayloadFromForm() {
  const type = mdmForm.entityType
  const payload = {}
  if (['reinsurer', 'reinsured', 'foreign_broker'].includes(type)) payload.abbreviation = String(mdmForm.abbreviation || '').trim()
  if (type === 'reinsured') payload.address = String(mdmForm.address || '').trim()
  if (type === 'reinsurer') {
    payload.fixedClauses = normalizeClauseList(mdmForm.fixedClauses)
    payload.ratings = normalizeRatingList(mdmForm.ratings)
  }
  return payload
}

async function saveMasterRecord() {
  if (!mdmForm.name.trim()) {
    ElMessage.error('Name is required')
    return
  }
  if (mdmForm.entityType === 'clause' && !String(mdmForm.code || '').trim()) {
    ElMessage.error('Clause code is required')
    return
  }
  mdmSaving.value = true; shell.error = ''
  try {
    const body = await jsonOrThrow(await apiFetch('/api/master-data', {
      method: editingMasterId.value ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(editingMasterId.value
        ? { entityType: mdmForm.entityType, code: mdmForm.code, name: mdmForm.name, payload: JSON.stringify(masterPayloadFromForm()), id: editingMasterId.value, rowVersion: editingMasterRowVersion.value }
        : { entityType: mdmForm.entityType, code: mdmForm.code, name: mdmForm.name, payload: JSON.stringify(masterPayloadFromForm()) })
    }))
    mdmDialogVisible.value = false
    activeMdmType.value = body.record.entityType
    await loadMasterData()
    ElMessage.success(`${masterTypeLabel(body.record.entityType)} ${editingMasterId.value ? 'updated' : 'added'}`)
  } catch (err) {
    shell.error = err instanceof Error ? err.message : String(err)
    reportWriteError(err, () => loadMasterData())
  } finally { mdmSaving.value = false }
}

async function toggleMasterStatus(row) {
  mdmSaving.value = true; shell.error = ''
  try {
    const body = await jsonOrThrow(await apiFetch('/api/master-data', {
      method: 'PUT', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        id: row.id, rowVersion: row.rowVersion, entityType: row.entityType,
        code: row.code, name: row.name, payload: JSON.stringify(row.payload || {}), isActive: !row.isActive
      })
    }))
    await loadMasterData()
    ElMessage.success(body.record.isActive ? 'Master record reactivated' : 'Master record deactivated')
  } catch (err) {
    shell.error = err instanceof Error ? err.message : String(err)
    reportWriteError(err, () => loadMasterData())
  } finally { mdmSaving.value = false }
}

onMounted(loadMasterData)
</script>

<template>
  <!-- Development begins this page with its master-data tabs. -->

  <div class="mdm-tabs" role="tablist" aria-label="Master data types">
    <button v-for="item in masterTypes" :key="item.value" type="button" class="mdm-tab" :class="{ active: activeMdmType === item.value }" @click="activeMdmType = item.value">
      <span>{{ item.tabLabel }} ({{ mdmCounts[item.value] || 0 }})</span>
    </button>
  </div>

  <section class="table-card" v-loading="mdmLoading">
    <div class="section-heading"><div><h2>{{ masterTypeLabel(activeMdmType) }}</h2><p>Ordering and Development data are preserved through versioned Edit and lifecycle controls; routine physical deletion is not exposed.</p></div><div><el-button v-if="can('mdm.write')" class="primary-button" @click="openMasterDialog()">+ Add {{ masterTypeLabel(activeMdmType) }}</el-button><el-button class="secondary-button" :loading="mdmLoading" @click="loadMasterData">Refresh</el-button></div></div>
    <el-table :data="filteredMasterRecords" class="case-table" row-key="id" empty-text="No records yet. Select Add to create the first master record.">
      <el-table-column v-if="['class','clause'].includes(activeMdmType)" prop="code" label="Code" width="120"><template #default="{ row }">{{ row.code || '—' }}</template></el-table-column>
      <el-table-column prop="name" :label="activeMdmType === 'clause' ? 'Title' : 'Name'" min-width="220"></el-table-column>
      <el-table-column v-if="['reinsurer','reinsured','foreign_broker'].includes(activeMdmType)" label="Abbreviation" min-width="150"><template #default="{ row }">{{ row.payload?.abbreviation || '—' }}</template></el-table-column>
      <el-table-column v-if="activeMdmType === 'reinsured'" label="Address" min-width="240"><template #default="{ row }">{{ row.payload?.address || '—' }}</template></el-table-column>
      <el-table-column v-if="activeMdmType === 'clause'" label="Source" width="110"><template #default="{ row }"><span class="status-badge" :class="isUniversalClauseCode(row.code) ? 'status-posted' : 'status-archived'">{{ clauseSourceType(row.code) }}</span></template></el-table-column>
      <el-table-column v-if="activeMdmType === 'clause'" label="Used by" min-width="220"><template #default="{ row }">{{ isUniversalClauseCode(row.code) ? 'Every case' : (clauseUsedByReinsurers(row.code).join(', ') || '—') }}</template></el-table-column>
      <el-table-column label="Status" width="120"><template #default="{ row }"><span class="status-badge" :class="row.isActive ? 'status-posted' : 'status-archived'">{{ row.isActive ? 'Active' : 'Inactive' }}</span></template></el-table-column>
      <el-table-column v-if="activeMdmType === 'reinsurer'" label="Ratings" width="100"><template #default="{ row }">{{ row.payload?.ratings?.length || 0 }}</template></el-table-column>
      <el-table-column v-if="activeMdmType === 'reinsurer'" label="Fixed clauses" width="130"><template #default="{ row }">{{ row.payload?.fixedClauses?.length || 0 }}</template></el-table-column>
      <el-table-column v-if="can('mdm.write')" label="Action" width="220"><template #default="{ row }"><span v-if="activeMdmType === 'clause' && isUniversalClauseCode(row.code)" class="pending-badge">System-managed</span><template v-else><el-button text type="primary" @click="openMasterDialog(row)">Edit</el-button><el-button text :type="row.isActive ? 'danger' : 'success'" :loading="mdmSaving" @click="toggleMasterStatus(row)">{{ row.isActive ? 'Deactivate' : 'Reactivate' }}</el-button></template></template></el-table-column>
    </el-table>
  </section>

  <el-dialog v-model="mdmDialogVisible" class="master-dialog" width="min(760px, 94vw)" :close-on-click-modal="false">
    <template #header><div class="review-heading"><span class="pending-badge">{{ editingMasterId ? 'Versioned master update' : 'New master record' }}</span><h2>{{ editingMasterId ? 'Edit' : 'Add' }} {{ masterTypeLabel(mdmForm.entityType) }}</h2><p>{{ editingMasterId ? 'Saving creates a new version and snapshot.' : 'The record starts Active and receives version 1 plus a snapshot.' }}</p></div></template>
    <el-form label-position="top" @submit.prevent>
      <el-form-item label="Type"><el-select v-model="mdmForm.entityType" :disabled="Boolean(editingMasterId)"><el-option v-for="item in masterTypes" :key="item.value" :label="item.label" :value="item.value"></el-option></el-select></el-form-item>
      <el-form-item :label="mdmForm.entityType === 'clause' ? 'Clause code' : 'Code'" :required="mdmForm.entityType === 'clause'"><el-input v-model="mdmForm.code" maxlength="80" :placeholder="mdmForm.entityType === 'clause' ? 'Required; e.g. LMA5390' : 'Optional; stored in uppercase'"></el-input></el-form-item>
      <el-form-item :label="mdmForm.entityType === 'clause' ? 'Clause title' : 'Name'" required><el-input v-model="mdmForm.name" maxlength="240" placeholder="Required"></el-input></el-form-item>
      <el-form-item v-if="['reinsurer','reinsured','foreign_broker'].includes(mdmForm.entityType)" label="Abbreviation"><el-input v-model="mdmForm.abbreviation" maxlength="80" placeholder="Optional short name"></el-input></el-form-item>
      <el-form-item v-if="mdmForm.entityType === 'reinsured'" label="Address"><el-input v-model="mdmForm.address" type="textarea" :rows="3" maxlength="1000" show-word-limit></el-input></el-form-item>
      <!-- Additional fields vary by master-data type. -->
      <template v-if="mdmForm.entityType === 'reinsurer'">
        <div class="repeat-heading"><div><h3>Financial ratings</h3><p>Keep the agency, grade, entity, source and review details used by Development.</p></div></div>
        <div class="review-list">
          <div v-for="(rating,index) in mdmForm.ratings" :key="'mdm-rating-' + index"><strong>{{ rating.agency }} · {{ rating.grade }}</strong><span>{{ [rating.ratingType, rating.outlook, rating.asOfDate, rating.status].filter(Boolean).join(' · ') || 'No additional details' }}<br v-if="rating.legalEntity"><small v-if="rating.legalEntity">{{ rating.legalEntity }}</small></span><el-button text type="danger" @click="removeMdmRating(index)">Remove</el-button></div>
        </div>
        <div class="form-grid cols-3" style="margin-top:16px;">
          <el-form-item label="Rating agency"><el-input v-model="mdmRatingDraft.agency" maxlength="120" placeholder="e.g. S&amp;P"></el-input></el-form-item>
          <el-form-item label="Grade"><el-input v-model="mdmRatingDraft.grade" maxlength="80" placeholder="e.g. A+"></el-input></el-form-item>
          <el-form-item label="Outlook"><el-input v-model="mdmRatingDraft.outlook" maxlength="80"></el-input></el-form-item>
          <el-form-item label="Rating type"><el-input v-model="mdmRatingDraft.ratingType" maxlength="120"></el-input></el-form-item>
          <el-form-item label="As-of date"><el-date-picker v-model="mdmRatingDraft.asOfDate" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" style="width:100%"></el-date-picker></el-form-item>
          <el-form-item label="Status"><el-input v-model="mdmRatingDraft.status" maxlength="80"></el-input></el-form-item>
          <el-form-item label="Legal entity"><el-input v-model="mdmRatingDraft.legalEntity" maxlength="240"></el-input></el-form-item>
          <el-form-item label="Source URL"><el-input v-model="mdmRatingDraft.sourceUrl" maxlength="1000"></el-input></el-form-item>
          <el-form-item label="Checked at"><el-date-picker v-model="mdmRatingDraft.checkedAt" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" style="width:100%"></el-date-picker></el-form-item>
          <el-form-item label=" "><el-button class="secondary-button" @click="addMdmRating">+ Add rating</el-button></el-form-item>
        </div>
        <div class="repeat-heading"><div><h3>Fixed clauses</h3><p>Applied to future new case snapshots. Picked from the Clause master list; Universal clauses (LMA3333, INTERMEDIARY) are always included and cannot be added here.</p></div></div>
        <div class="review-list">
          <div v-for="(clause,index) in mdmForm.fixedClauses" :key="'mdm-clause-' + clause.code"><strong>{{ clause.code }}</strong><span>{{ clause.title }}</span><el-button text type="danger" @click="removeMdmFixedClause(index)">Remove</el-button></div>
        </div>
        <div class="form-grid cols-3" style="margin-top:16px;">
          <el-form-item label="Clause"><el-select v-model="mdmClauseDraft.code" filterable placeholder="Select from Clause master" @change="onMdmClauseDraftSelect" style="width:100%"><el-option v-for="item in availableClauseOptions()" :key="item.code" :label="item.code + ' — ' + item.title" :value="item.code"></el-option></el-select><small v-if="!availableClauseOptions().length">No available clauses. Add one under the Clause tab first.</small></el-form-item>
          <el-form-item label=" "><el-button class="secondary-button" :disabled="!mdmClauseDraft.code" @click="addMdmFixedClause">+ Add fixed clause</el-button></el-form-item>
        </div>
      </template>
    </el-form>
    <template #footer><div class="review-footer"><p>Records are retained; lifecycle changes never physically delete master data.</p><div><el-button class="secondary-button" @click="mdmDialogVisible = false">Cancel</el-button><el-button class="primary-button" :loading="mdmSaving" @click="saveMasterRecord">{{ editingMasterId ? 'Save changes' : 'Add record' }}</el-button></div></div></template>
  </el-dialog>
</template>
