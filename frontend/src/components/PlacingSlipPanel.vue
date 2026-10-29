<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiFetch } from '../api'
import { can } from '../auth'
const props = defineProps({ caseRecord: { type: Object, required: true } })
const state = ref({ versions: [], eligible: false })
const busy = ref(false), description = ref(''), annual = ref(true), chosen = ref(null), issues = ref([])
const writable = computed(() => can('documents.write') && props.caseRecord.status === 'draft')
const base = () => '/api/placing-slips?caseUid=' + encodeURIComponent(props.caseRecord.caseUid)
async function read(response) {
  const b = await response.json()
  if (!response.ok) { issues.value = b.issues || []; throw new Error(b.message || b.error) }
  return b
}
async function reload() {
  if (!can('documents.read')) return
  try { state.value = await read(await apiFetch(base())) } catch (e) { ElMessage.error(e.message) }
}
watch(() => [props.caseRecord.caseUid, props.caseRecord.rowVersion, props.caseRecord.status], reload, { immediate: true })
function uuid() {
  const a = crypto.getRandomValues(new Uint8Array(16)); a[6] = a[6] & 15 | 64; a[8] = a[8] & 63 | 128
  const s = [...a].map(x => x.toString(16).padStart(2, '0')).join('')
  return [s.slice(0,8), s.slice(8,12), s.slice(12,16), s.slice(16,20), s.slice(20)].join('-')
}
let pending = null
async function submit(action) {
  if (!description.value.trim()) return ElMessage.warning('Enter a version description.')
  if (action === 'upload' && !chosen.value) return ElMessage.warning('Select an edited DOCX or PDF.')
  busy.value = true; issues.value = []
  try {
    let encoded = ''
    if (action === 'upload') encoded = await new Promise((resolve,reject) => { const r = new FileReader(); r.onload = () => resolve(String(r.result).split(',')[1]); r.onerror = reject; r.readAsDataURL(chosen.value) })
    const data = { caseUid: props.caseRecord.caseUid, rowVersion: props.caseRecord.rowVersion, description: description.value.trim(), action, annual: annual.value, ...(action === 'upload' ? { filename: chosen.value.name, base64: encoded } : {}) }
    const signature = JSON.stringify(data)
    if (!pending || pending.signature !== signature) pending = { signature, id: uuid() }
    const b = await read(await apiFetch('/api/placing-slips', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...data, generationId: pending.id }) }))
    pending = null; state.value = b; description.value = ''; chosen.value = null; annual.value = true
    ElMessage.success('Placing Slip version saved.')
    if (action === 'generate') await download(b.file)
  } catch (e) { ElMessage.error(e.message || 'The file could not be saved. Retry the same operation.') }
  finally { busy.value = false }
}
async function download(row) {
  try {
    const response = await apiFetch(base() + '&fileId=' + encodeURIComponent(row.id))
    if (!response.ok) { await read(response); return }
    const url = URL.createObjectURL(await response.blob()), a = document.createElement('a')
    a.href = url; a.download = row.filename; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e) { ElMessage.error(e.message) }
}
async function remove(row) {
  try { await ElMessageBox.confirm(`Delete Placing Slip version ${row.version}?`, 'Delete Placing Slip', { type: 'warning' }) } catch { return }
  busy.value = true
  try { state.value = await read(await apiFetch(base() + '&fileId=' + encodeURIComponent(row.id), { method: 'DELETE' })) }
  catch (e) { ElMessage.error(e.message) }
  finally { busy.value = false }
}
function selectFile(e) {
  const f = e.target.files?.[0]
  if (f && (!/\.(docx|pdf)$/i.test(f.name) || f.size > 30 * 1024 * 1024)) { e.target.value = ''; chosen.value = null; return ElMessage.warning('Select a DOCX or PDF no larger than 30 MB.') }
  chosen.value = f || null
}
</script>
<template>
  <section v-if="state.eligible || state.versions.length" class="overview-card" data-testid="placing-slip-panel" v-loading="busy">
    <h2>Placing Slip</h2>
    <p>Market enquiry documents. These do not replace Offer Slip, Endorsement or Signed Slip evidence.</p>
    <el-alert v-if="state.outdated" title="Existing Placing Slip may not reflect the latest terms. Edit and upload an updated version." type="warning" :closable="false" />
    <template v-if="writable && state.canUpload">
      <el-form-item label="Version description" required><el-input v-model="description" maxlength="500" placeholder="Initial enquiry, revised deductible, market review…" /></el-form-item>
      <el-checkbox v-if="state.canGenerate && caseRecord.caseKind !== 'endorsement'" v-model="annual">Annual</el-checkbox>
      <el-button v-if="state.canGenerate" :disabled="busy" @click="submit('generate')">Generate Word</el-button>
      <p v-else>Edited versions exist. Upload the next edited version. Deleting all uploaded versions restores generation.</p>
      <input type="file" accept=".docx,.pdf" aria-label="Edited Placing Slip" @change="selectFile" />
      <el-button :disabled="busy || !chosen" @click="submit('upload')">Upload edited version</el-button>
    </template>
    <el-alert v-if="issues.length" type="warning" :closable="false"><ul><li v-for="(issue,i) in issues" :key="i">{{ issue.label || issue.message }}</li></ul></el-alert>
    <el-table :data="state.versions" empty-text="No Placing Slip versions saved." row-key="id">
      <el-table-column label="Version" width="90"><template #default="{row}">V{{ row.version }}</template></el-table-column>
      <el-table-column label="Document" min-width="220"><template #default="{row}">{{ row.filename }}<small style="display:block">{{ row.source }} · {{ row.description }}</small></template></el-table-column>
      <el-table-column label="Saved by" prop="uploaded_by" min-width="130" />
      <el-table-column label="Saved at" min-width="170"><template #default="{row}">{{ new Date(row.uploaded_at).toLocaleString('en-GB', { timeZone: 'Asia/Taipei' }) }}</template></el-table-column>
      <el-table-column label="Action" width="160"><template #default="{row}"><el-button text @click="download(row)">Download</el-button><el-button v-if="writable && state.canDelete" text type="danger" @click="remove(row)">Delete</el-button></template></el-table-column>
    </el-table>
  </section>
</template>
