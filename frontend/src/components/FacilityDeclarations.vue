<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiFetch } from '../api'
import { jsonOrThrow } from '../alpha/format'

const props = defineProps({ facility: { type: Object, required: true }, writable: { type: Boolean, default: false } })
const emit = defineEmits(['changed'])
const rows = ref([]), editing = ref(null), files = ref([]), selectedFile = ref(null), busy = ref(false)
const form = reactive({ periodFrom: '', periodTo: '', statementNo: '', premium: '', claim: '' })
const params = row => `facilityUid=${encodeURIComponent(props.facility.caseUid)}&declarationUid=${encodeURIComponent(row.declarationUid)}`
async function load() {
  const body = await jsonOrThrow(await apiFetch('/api/facility-declarations?facilityUid=' + encodeURIComponent(props.facility.caseUid)))
  rows.value = body.declarations || []
}
async function loadFiles(row) {
  const body = await jsonOrThrow(await apiFetch('/api/facility-declaration-documents?' + params(row)))
  files.value = body.files || []
}
function startNew() {
  editing.value = { isNew: true }
  Object.assign(form, { periodFrom: rows.value.length ? '' : props.facility.payload?.policyFrom || '', periodTo: '', statementNo: '', premium: '', claim: '' })
  files.value = []; selectedFile.value = null
}
async function startEdit(row) {
  editing.value = row
  Object.assign(form, { periodFrom: row.periodFrom, periodTo: row.periodTo, statementNo: row.statementNo,
                        premium: row.payload?.premium || '', claim: row.payload?.claim || '' })
  selectedFile.value = null
  try { await loadFiles(row) } catch (err) { ElMessage.error(err.message) }
}
async function save() {
  busy.value = true
  try {
    const updating = !editing.value.isNew
    const request = { facilityUid: props.facility.caseUid, declaration: { ...form } }
    if (updating) Object.assign(request, { declarationUid: editing.value.declarationUid, rowVersion: editing.value.rowVersion })
    const body = await jsonOrThrow(await apiFetch('/api/facility-declarations', {
      method: updating ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request)
    }))
    editing.value = body.declaration
    if (body.caseRowVersion) props.facility.rowVersion = body.caseRowVersion
    if (body.caseRowVersion) emit('changed')
    await load(); await loadFiles(editing.value)
    ElMessage.success(editing.value.status === 'posted' ? 'Declaration correction saved.' : 'Declaration Draft saved.')
  } catch (err) { ElMessage.error(err.message) } finally { busy.value = false }
}
async function upload() {
  if (!selectedFile.value || editing.value?.isNew) return
  busy.value = true
  try {
    const data = await new Promise((resolve, reject) => {
      const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = reject
      reader.readAsDataURL(selectedFile.value)
    })
    await jsonOrThrow(await apiFetch('/api/facility-declaration-documents', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ facilityUid: props.facility.caseUid, declarationUid: editing.value.declarationUid,
                             filename: selectedFile.value.name, base64: data })
    }))
    selectedFile.value = null; await loadFiles(editing.value); ElMessage.success('Evidence uploaded.')
  } catch (err) { ElMessage.error(err.message) } finally { busy.value = false }
}
async function download(file) {
  try {
    const response = await apiFetch('/api/facility-declaration-documents?' + params(editing.value) + '&fileId=' + encodeURIComponent(file.id))
    if (!response.ok) throw new Error('Unable to download evidence.')
    const url = URL.createObjectURL(await response.blob())
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = file.filename; document.body.appendChild(anchor); anchor.click(); anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (err) { ElMessage.error(err.message) }
}
async function announce() {
  if (!editing.value || editing.value.isNew) return
  const amount = value => String(value || '0').replaceAll(',', '').trim()
  if (form.periodFrom !== editing.value.periodFrom || form.periodTo !== editing.value.periodTo ||
      form.statementNo.trim() !== editing.value.statementNo ||
      amount(form.premium) !== amount(editing.value.payload?.premium) || amount(form.claim) !== amount(editing.value.payload?.claim)) {
    ElMessage.warning('Save Declaration changes before Announce.')
    return
  }
  try {
    await ElMessageBox.confirm('Confirm this Declaration and its evidence?', 'Review Declaration', { confirmButtonText: 'Announce', cancelButtonText: 'Back' })
    busy.value = true
    const body = await jsonOrThrow(await apiFetch('/api/facility-declaration-announce', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ facilityUid: props.facility.caseUid, declarationUid: editing.value.declarationUid,
                             rowVersion: editing.value.rowVersion, confirmed: true })
    }))
    editing.value = null
    props.facility.rowVersion = body.caseRowVersion
    emit('changed')
    await load()
    ElMessage.success('Declaration Announced.')
  } catch (err) { if (err !== 'cancel' && err !== 'close') ElMessage.error(err?.message || String(err)) }
  finally { busy.value = false }
}
onMounted(() => load().catch(err => ElMessage.error(err.message)))
</script>

<template>
  <section class="overview-card" data-testid="facility-declarations">
    <div class="section-heading"><h2>Declarations</h2><el-button v-if="writable" @click="startNew">New Declaration</el-button></div>
    <el-table :data="rows" empty-text="No Declarations yet.">
      <el-table-column prop="periodFrom" label="From" /><el-table-column prop="periodTo" label="To" />
      <el-table-column prop="statementNo" label="Cedant's Statement No." /><el-table-column prop="status" label="Status" />
      <el-table-column label=""><template #default="{ row }"><el-button v-if="writable && ['draft','posted'].includes(row.status)" link @click="startEdit(row)">{{ row.status === 'posted' ? 'Correct' : 'Edit' }}</el-button></template></el-table-column>
    </el-table>
    <div v-if="editing" class="form-grid cols-2">
      <el-form-item label="Declaration Period From"><el-date-picker v-model="form.periodFrom" type="date" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="Declaration Period To"><el-date-picker v-model="form.periodTo" type="date" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="Cedant's Statement No."><el-input v-model="form.statementNo" maxlength="160" /></el-form-item>
      <el-form-item label="Currency"><el-input :model-value="facility.payload?.currency" disabled /></el-form-item>
      <el-form-item label="Premium"><el-input v-model="form.premium" inputmode="decimal" /></el-form-item>
      <el-form-item label="Claim"><el-input v-model="form.claim" inputmode="decimal" /></el-form-item>
      <el-button :loading="busy" @click="save">{{ editing.status === 'posted' ? 'Save correction' : 'Save Draft' }}</el-button>
      <div v-if="!editing.isNew"><p>Payment due: {{ editing.payload?.dueDate || '—' }}</p><p v-for="file in files" :key="file.id"><el-button link @click="download(file)">{{ file.filename }}</el-button></p>
        <template v-if="editing.status === 'draft'"><input type="file" aria-label="Declaration evidence" @change="selectedFile = $event.target.files?.[0] || null" />
        <el-button :disabled="!selectedFile" :loading="busy" @click="upload">Upload evidence</el-button>
        <el-button type="primary" :disabled="!files.length" :loading="busy" @click="announce">Review &amp; Announce</el-button></template>
      </div>
    </div>
  </section>
</template>
