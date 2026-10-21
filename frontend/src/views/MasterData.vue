<script setup>
// 移植自 Alpha index.html 的 activeView === 'mdm' 與 app.js 的主檔函式
// （loadMasterData、openMasterDialog、add/removeMdmFixedClause、add/removeMdmRating、masterPayloadFromForm、saveMasterRecord、toggleMasterStatus 等）。
// VM 才有（2026-09-29 決定）：再保人的 Fixed Clause 可指定適用 Class（classIds；沒有 = All classes，新增時預設 Property），
// Class 主檔也可以有自己的 Fixed Clause。
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiFetch } from '../api'
import { can } from '../auth'
import { UNIVERSAL_CLAUSES, compareClauses, normalizeClauseCode, normalizeClauseList, normalizeRatingList } from '../alpha/constants'
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
const openReinsurerMarkets = ref([])
const lloydsMarketProfile = ref(null)
const lloydsRatingDialogVisible = ref(false)
const lloydsRatingSaving = ref(false)
const lloydsRatingRows = ref([])
const editingLloydsRatingVersion = ref(null)
const mdmRecords = ref([])
const mdmCounts = ref({ ae: 0, reinsurer: 0, reinsured: 0, class: 0, foreign_broker: 0, clause: 0 })
const mdmForm = reactive({ entityType: 'ae', code: '', name: '', abbreviation: '', address: '', fixedClauses: [], ratings: [] })
const mdmClauseDraft = reactive({ code: '', title: '' })
const mdmRatingDraft = reactive({ agency: '', grade: '', outlook: '', ratingType: '', asOfDate: '', legalEntity: '', sourceUrl: '', checkedAt: '', status: '' })

const filteredMasterRecords = computed(() => {
  const records = mdmRecords.value.filter((row) => row.entityType === activeMdmType.value)
  return activeMdmType.value === 'clause' ? [...records].sort(compareClauses) : records
})

// Lloyd's is a display group; keep the original master names and business rules.
function isLloydsMarket(row) {
  return /^Lloyd['’]s\s+Underwriter\s+Syndicate\s+No\./i.test(String(row.name || '').trim())
}
const lloydsMarketRecords = computed(() => filteredMasterRecords.value.filter(isLloydsMarket))
const ungroupedMasterRecords = computed(() => activeMdmType.value === 'reinsurer'
  ? filteredMasterRecords.value.filter((row) => !isLloydsMarket(row))
  : filteredMasterRecords.value)

const isLloydsForm = computed(() => mdmForm.entityType === 'reinsurer' && isLloydsMarket(mdmForm))
const sharedLloydsRatings = computed(() => normalizeRatingList(lloydsMarketProfile.value?.ratings))
const displayedFormRatings = computed(() => isLloydsForm.value ? sharedLloydsRatings.value : mdmForm.ratings)

async function openLloydsRatingDialog() {
  try {
    const body = await jsonOrThrow(await apiFetch('/api/master-data/lloyds-ratings', { headers: { Accept: 'application/json' } }))
    lloydsMarketProfile.value = body.profile
    editingLloydsRatingVersion.value = body.profile.rowVersion
    lloydsRatingRows.value = normalizeRatingList(body.profile.ratings).map((row) => ({ ...row }))
    lloydsRatingDialogVisible.value = true
  } catch (err) { ElMessage.error(err instanceof Error ? err.message : String(err)) }
}
function addLloydsRatingRow() {
  lloydsRatingRows.value.push({ agency: '', grade: '', outlook: '', ratingType: 'Financial Strength', asOfDate: '', status: '', legalEntity: "Lloyd's of London", sourceUrl: '', checkedAt: '' })
}
async function saveLloydsRatings() {
  if (!lloydsRatingRows.value.length || lloydsRatingRows.value.some((row) => !row.agency.trim() || !row.grade.trim())) {
    return ElMessage.error('Enter an agency and a grade for every rating.')
  }
  lloydsRatingSaving.value = true
  try {
    const body = await jsonOrThrow(await apiFetch('/api/master-data/lloyds-ratings', {
      method: 'PUT', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ rowVersion: editingLloydsRatingVersion.value, ratings: lloydsRatingRows.value })
    }))
    lloydsMarketProfile.value = body.profile
    lloydsRatingDialogVisible.value = false
    await loadMasterData()
    ElMessage.success("Lloyd's Market ratings updated for all syndicates")
  } catch (err) {
    // Keep the draft unless the user chooses Reload latest version.
    reportWriteError(err, () => openLloydsRatingDialog())
  } finally { lloydsRatingSaving.value = false }
}

function masterTypeLabel(value) {
  return masterTypes.find((item) => item.value === value)?.label || value
}
function isUniversalClauseCode(code) {
  return UNIVERSAL_CLAUSES.some((row) => row.code === String(code || '').toUpperCase())
}
function clauseSourceType(code) {
  return isUniversalClauseCode(code) ? 'Universal' : 'Standard'
}
const ALL_CLASSES = '*'
function classNameById(id) {
  return mdmRecords.value.find((row) => row.entityType === 'class' && Number(row.id) === Number(id))?.name || `Class #${id}`
}
function appliesToLabel(classIds) {
  return Array.isArray(classIds) ? classIds.map(classNameById).join(', ') : 'All classes'
}
function clauseUsedByReinsurers(code) {
  const normalized = String(code || '').toUpperCase()
  const users = []
  mdmRecords.value.forEach((row) => {
    if (!['reinsurer', 'class'].includes(row.entityType) || !Array.isArray(row.payload?.fixedClauses)) return
    const clause = row.payload.fixedClauses.find((c) => String(c.code || '').toUpperCase() === normalized)
    if (!clause) return
    if (row.entityType === 'class') users.push(`Class: ${row.name}`)
    else users.push((row.payload?.abbreviation || row.name) + (Array.isArray(clause.classIds) ? ` (${appliesToLabel(clause.classIds)})` : ''))
  })
  return users.sort((a, b) => a.localeCompare(b))
}
function classScopeOptions(selected) {
  const ids = new Set((selected || []).filter((v) => v !== ALL_CLASSES).map(Number))
  return mdmRecords.value
    .filter((row) => row.entityType === 'class' && (row.isActive || ids.has(Number(row.id))))
    .map((row) => ({ value: Number(row.id), label: row.isActive ? row.name : `${row.name} (inactive)` }))
}
function defaultClauseScope() {
  const property = mdmRecords.value.find((row) => row.entityType === 'class' && row.isActive && row.name === 'Property')
  return property ? [Number(property.id)] : [ALL_CLASSES]
}
function onClauseScopeChange(clause, value) {
  const last = value[value.length - 1]
  clause.appliesTo = last === ALL_CLASSES ? [ALL_CLASSES] : value.filter((v) => v !== ALL_CLASSES)
}
function formClausesFromPayload(type, rows) {
  const source = Array.isArray(rows) ? rows : []
  return normalizeClauseList(source).map((clause) => {
    if (type !== 'reinsurer') return clause
    const original = source.find((row) => normalizeClauseCode(row?.code) === clause.code)
    return { ...clause, appliesTo: Array.isArray(original?.classIds) ? original.classIds.map(Number) : [ALL_CLASSES] }
  })
}
function payloadClausesFromForm(type) {
  return normalizeClauseList(mdmForm.fixedClauses).map((clause) => {
    if (type !== 'reinsurer') return clause
    const scope = mdmForm.fixedClauses.find((row) => row.code === clause.code)?.appliesTo || []
    return scope.includes(ALL_CLASSES) ? clause : { ...clause, classIds: scope.map(Number) }
  })
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
    lloydsMarketProfile.value = body.reinsurerMarkets?.lloyds || null
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
        fixedClauses: formClausesFromPayload(row.entityType, row.payload?.fixedClauses), ratings: isLloydsMarket(row) ? [] : normalizeRatingList(row.payload?.ratings)
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
  if (mdmForm.fixedClauses.some((row) => row.code === clause.code)) return ElMessage.error(`This Clause code already exists for the ${mdmForm.entityType === 'class' ? 'class' : 'reinsurer'}`)
  mdmForm.fixedClauses.push(mdmForm.entityType === 'reinsurer' ? { ...clause, appliesTo: defaultClauseScope() } : clause)
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
    payload.fixedClauses = payloadClausesFromForm(type)
    payload.ratings = isLloydsForm.value ? sharedLloydsRatings.value : normalizeRatingList(mdmForm.ratings)
  }
  if (type === 'class') {
    const clauses = payloadClausesFromForm(type)
    if (clauses.length) payload.fixedClauses = clauses
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
  const unscoped = mdmForm.entityType === 'reinsurer' ? mdmForm.fixedClauses.find((row) => !row.appliesTo?.length) : null
  if (unscoped) {
    ElMessage.error(`Select All classes or at least one Class for ${unscoped.code}`)
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
    <el-collapse v-if="activeMdmType === 'reinsurer'" v-model="openReinsurerMarkets" class="mdm-market-groups">
      <el-collapse-item name="lloyds" :title="`Lloyd's Market (${lloydsMarketRecords.length})`">
        <div class="lloyds-market-ratings">
          <div class="lloyds-rating-heading"><strong>Financial ratings · Lloyd's of London</strong><el-button v-if="can('mdm.write')" text type="primary" aria-label="Edit Lloyd's Market ratings" @click="openLloydsRatingDialog">Edit</el-button></div>
          <p v-if="sharedLloydsRatings.length" class="lloyds-rating-grades"><span v-for="rating in sharedLloydsRatings" :key="rating.agency">{{ rating.agency }} <b>{{ rating.grade }}</b></span></p>
          <p>All reinsurers in this market use these shared financial strength ratings.</p>
        </div>
        <el-table :data="lloydsMarketRecords" class="case-table" row-key="id" empty-text="No reinsurers in this market.">
          <el-table-column prop="name" label="Name" min-width="220"></el-table-column>
          <el-table-column label="Abbreviation" min-width="150"><template #default="{ row }">{{ row.payload?.abbreviation || '—' }}</template></el-table-column>
          <el-table-column label="Status" width="120"><template #default="{ row }"><span class="status-badge" :class="row.isActive ? 'status-posted' : 'status-archived'">{{ row.isActive ? 'Active' : 'Inactive' }}</span></template></el-table-column>
          <el-table-column label="Ratings" min-width="170"><template #default><span>Lloyd's of London</span></template></el-table-column>
          <el-table-column label="Fixed clauses" width="130"><template #default="{ row }">{{ row.payload?.fixedClauses?.length || 0 }}</template></el-table-column>
          <el-table-column v-if="can('mdm.write')" label="Action" width="220"><template #default="{ row }"><el-button text type="primary" @click="openMasterDialog(row)">Edit</el-button><el-button text :type="row.isActive ? 'danger' : 'success'" :loading="mdmSaving" @click="toggleMasterStatus(row)">{{ row.isActive ? 'Deactivate' : 'Reactivate' }}</el-button></template></el-table-column>
        </el-table>
      </el-collapse-item>
    </el-collapse>
    <el-table v-if="activeMdmType !== 'reinsurer' || ungroupedMasterRecords.length" :data="ungroupedMasterRecords" class="case-table" row-key="id" empty-text="No records yet. Select Add to create the first master record.">
      <el-table-column v-if="['class','clause'].includes(activeMdmType)" prop="code" label="Code" width="120"><template #default="{ row }">{{ row.code || '—' }}</template></el-table-column>
      <el-table-column prop="name" :label="activeMdmType === 'clause' ? 'Title' : 'Name'" min-width="220"></el-table-column>
      <el-table-column v-if="['reinsurer','reinsured','foreign_broker'].includes(activeMdmType)" label="Abbreviation" min-width="150"><template #default="{ row }">{{ row.payload?.abbreviation || '—' }}</template></el-table-column>
      <el-table-column v-if="activeMdmType === 'reinsured'" label="Address" min-width="240"><template #default="{ row }">{{ row.payload?.address || '—' }}</template></el-table-column>
      <el-table-column v-if="activeMdmType === 'clause'" label="Source" width="110"><template #default="{ row }"><span class="status-badge" :class="isUniversalClauseCode(row.code) ? 'status-posted' : 'status-archived'">{{ clauseSourceType(row.code) }}</span></template></el-table-column>
      <el-table-column v-if="activeMdmType === 'clause'" label="Used by" min-width="220"><template #default="{ row }">{{ isUniversalClauseCode(row.code) ? 'Every case' : (clauseUsedByReinsurers(row.code).join(', ') || '—') }}</template></el-table-column>
      <el-table-column label="Status" width="120"><template #default="{ row }"><span class="status-badge" :class="row.isActive ? 'status-posted' : 'status-archived'">{{ row.isActive ? 'Active' : 'Inactive' }}</span></template></el-table-column>
      <el-table-column v-if="activeMdmType === 'reinsurer'" label="Ratings" width="100"><template #default="{ row }">{{ row.payload?.ratings?.length || 0 }}</template></el-table-column>
      <el-table-column v-if="['reinsurer','class'].includes(activeMdmType)" label="Fixed clauses" width="130"><template #default="{ row }">{{ row.payload?.fixedClauses?.length || 0 }}</template></el-table-column>
      <el-table-column v-if="can('mdm.write')" label="Action" width="220"><template #default="{ row }"><span v-if="activeMdmType === 'clause' && isUniversalClauseCode(row.code)" class="pending-badge">System-managed</span><template v-else><el-button text type="primary" @click="openMasterDialog(row)">Edit</el-button><el-button text :type="row.isActive ? 'danger' : 'success'" :loading="mdmSaving" @click="toggleMasterStatus(row)">{{ row.isActive ? 'Deactivate' : 'Reactivate' }}</el-button></template></template></el-table-column>
    </el-table>

  </section>

  <el-dialog v-model="lloydsRatingDialogVisible" class="lloyds-rating-dialog" title="Edit Lloyd's Market ratings" width="min(760px, 94vw)" :close-on-click-modal="false" :close-on-press-escape="!lloydsRatingSaving" :show-close="!lloydsRatingSaving">
    <p>Changes apply to all reinsurers in Lloyd's Market.</p>
    <el-form label-position="top" @submit.prevent>
      <div v-for="(rating,index) in lloydsRatingRows" :key="index" class="lloyds-rating-editor-row">
        <div class="repeat-heading"><strong>Rating {{ index + 1 }}</strong><el-button text type="danger" :disabled="lloydsRatingSaving" @click="lloydsRatingRows.splice(index,1)">Remove</el-button></div>
        <div class="form-grid cols-3">
          <el-form-item label="Rating agency" required><el-input v-model="rating.agency" maxlength="120" :disabled="lloydsRatingSaving"></el-input></el-form-item>
          <el-form-item label="Grade" required><el-input v-model="rating.grade" maxlength="80" :disabled="lloydsRatingSaving"></el-input></el-form-item>
          <el-form-item label="Outlook"><el-input v-model="rating.outlook" maxlength="80" :disabled="lloydsRatingSaving"></el-input></el-form-item>
          <el-form-item label="Rating type"><el-input v-model="rating.ratingType" maxlength="120" :disabled="lloydsRatingSaving"></el-input></el-form-item>
          <el-form-item label="As-of date"><el-date-picker v-model="rating.asOfDate" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" :disabled="lloydsRatingSaving" style="width:100%"></el-date-picker></el-form-item>
          <el-form-item label="Status"><el-input v-model="rating.status" maxlength="80" :disabled="lloydsRatingSaving"></el-input></el-form-item>
        </div>
      </div>
      <el-button class="secondary-button" :disabled="lloydsRatingSaving || lloydsRatingRows.length >= 50" @click="addLloydsRatingRow">+ Add rating</el-button>
    </el-form>
    <template #footer><el-button :disabled="lloydsRatingSaving" @click="lloydsRatingDialogVisible = false">Cancel</el-button><el-button type="primary" :loading="lloydsRatingSaving" @click="saveLloydsRatings">Save changes</el-button></template>
  </el-dialog>

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
        <div class="repeat-heading"><div><h3>Financial ratings</h3><p v-if="isLloydsForm">Fixed source: Lloyd's of London. All syndicates in Lloyd's Market share the market's financial strength ratings.</p><p v-else>Keep the agency, grade, entity, source and review details used by Development.</p></div></div>
        <div class="review-list">
          <div v-for="(rating,index) in displayedFormRatings" :key="'mdm-rating-' + index"><strong>{{ rating.agency }} · {{ rating.grade }}</strong><span>{{ [rating.ratingType, rating.outlook, rating.asOfDate, rating.status].filter(Boolean).join(' · ') || 'No additional details' }}<br v-if="rating.legalEntity"><small v-if="rating.legalEntity">{{ rating.legalEntity }}</small></span><el-button v-if="!isLloydsForm" text type="danger" @click="removeMdmRating(index)">Remove</el-button></div>
        </div>
        <div v-if="!isLloydsForm" class="form-grid cols-3" style="margin-top:16px;">
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
      </template>
      <template v-if="['reinsurer','class'].includes(mdmForm.entityType)">
        <div class="repeat-heading"><div><h3>Fixed clauses</h3><p v-if="mdmForm.entityType === 'reinsurer'">Applied to future new case snapshots whose Class is listed under Applies to. Picked from the Clause master list; Universal clauses (LMA3333, INTERMEDIARY) are always included and cannot be added here.</p><p v-else>Applied to future new case snapshots of this Class, whichever reinsurers are selected. Picked from the Clause master list; Universal clauses (LMA3333, INTERMEDIARY) are always included and cannot be added here.</p></div></div>
        <div class="review-list">
          <div v-for="(clause,index) in mdmForm.fixedClauses" :key="'mdm-clause-' + clause.code"><strong>{{ clause.code }}</strong><span>{{ clause.title }}<template v-if="mdmForm.entityType === 'reinsurer'"><br><el-select :model-value="clause.appliesTo" multiple collapse-tags collapse-tags-tooltip size="small" placeholder="Applies to" :aria-label="'Applies to ' + clause.code" style="width:100%;max-width:360px;margin-top:6px" @update:model-value="onClauseScopeChange(clause, $event)"><el-option label="All classes" :value="ALL_CLASSES"></el-option><el-option v-for="item in classScopeOptions(clause.appliesTo)" :key="item.value" :label="item.label" :value="item.value"></el-option></el-select></template></span><el-button text type="danger" @click="removeMdmFixedClause(index)">Remove</el-button></div>
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

<style scoped>
.mdm-market-groups { margin: 0 20px 20px; }
.lloyds-market-ratings { padding: 16px 18px; }
.lloyds-rating-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.lloyds-rating-editor-row { border-bottom: 1px solid var(--border); margin-bottom: 16px; padding-bottom: 8px; }
.lloyds-market-ratings p { margin: 8px 0; }
.lloyds-rating-grades { display: flex; flex-wrap: wrap; gap: 8px 20px; }
.mdm-market-groups :deep(.el-collapse-item) { margin-bottom: 0; }
.mdm-market-groups :deep(.el-collapse-item__content) { padding: 0; }
</style>
