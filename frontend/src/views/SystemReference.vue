<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, apiFetch } from '../api'
import { can } from '../auth'

const files = ref([])
const manuals = ref([])
const trash = ref([])
const unreadable = ref(0)
const managing = ref(false)
const loading = ref(false)
const saving = ref(false)
const selectedFile = ref(null)
const fileList = ref([])
const endpoint = '/api/system-reference'
async function load() {
  loading.value = true
  try {
    const data = await api(endpoint)
    files.value = data.files
    manuals.value = data.manuals
    trash.value = data.trash || []
    unreadable.value = Number(data.unreadable) || 0
  } catch (error) { ElMessage.error(error.message) }
  finally { loading.value = false }
}
function choose(file) { selectedFile.value = file.raw; fileList.value = [file] }
function clear() { selectedFile.value = null; fileList.value = [] }
async function upload() {
  if (!selectedFile.value) return ElMessage.error('Select a document template first.')
  if (selectedFile.value.size > 10 * 1024 * 1024) return ElMessage.error('Each file must be no larger than 10 MB.')
  saving.value = true
  try {
    const body = new FormData()
    body.append('file', selectedFile.value)
    const response = await apiFetch(endpoint, { method: 'POST', body })
    const data = await response.json()
    if (!response.ok) throw new Error(data.message || data.detail || 'Upload failed.')
    clear()
    ElMessage.success('Document template uploaded.')
    await load()
  } catch (error) { ElMessage.error(error.message) }
  finally { saving.value = false }
}
async function download(row, manual = false) {
  try {
    const response = await apiFetch(`${endpoint}?${manual ? 'manual' : 'fileId'}=${encodeURIComponent(row.id)}`)
    if (!response.ok) {
      const data = await response.json()
      throw new Error(data.message || data.detail || 'Download failed.')
    }
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url; link.download = row.filename
    document.body.appendChild(link); link.click(); link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error) { ElMessage.error(error.message) }
}
function date(value) { return new Date(value).toLocaleString('en-GB', { timeZone: 'Asia/Taipei' }) }
function target(row) { return row.kind === 'manual' ? { manual: row.id } : { fileId: row.id } }
async function rename(row) {
  const dot = row.filename.lastIndexOf('.')
  const stem = row.filename.slice(0, dot)
  const extension = row.filename.slice(dot)
  try {
    const { value } = await ElMessageBox.prompt(`Enter a new name. The download filename will also change, and the ${extension} extension will be preserved.`, 'Rename', {
      inputValue: stem, confirmButtonText: 'Save', cancelButtonText: 'Cancel',
      inputValidator: value => !!value?.trim() && value.trim().length <= 160 && !/[\x00-\x1f\x7f/\\]/.test(value) || 'Enter 1 to 160 characters without slashes or control characters.',
    })
    managing.value = true
    await api(endpoint, { method: 'PATCH', body: { ...target(row), action: 'rename', name: value } })
    ElMessage.success('File renamed.')
    await load()
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(error.message || 'Rename failed.') }
  finally { managing.value = false }
}
async function remove(row) {
  try {
    await ElMessageBox.confirm(`Move "${row.filename}" to the Recycle Bin? You can restore it later.`, 'Delete file', {
      type: 'warning', confirmButtonText: 'Move to Recycle Bin', cancelButtonText: 'Cancel',
    })
    managing.value = true
    const query = new URLSearchParams(target(row))
    await api(`${endpoint}?${query}`, { method: 'DELETE' })
    ElMessage.success('File moved to the Recycle Bin.')
    await load()
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(error.message || 'Delete failed.') }
  finally { managing.value = false }
}
async function restore(row) {
  managing.value = true
  try {
    await api(endpoint, { method: 'PATCH', body: { ...target(row), action: 'restore' } })
    ElMessage.success('File restored.')
    await load()
  } catch (error) { ElMessage.error(error.message || 'Restore failed.') }
  finally { managing.value = false }
}
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="reference-page">
    <el-alert v-if="unreadable" type="warning" :closable="false" show-icon :title="`${unreadable} document template record(s) could not be read and are not listed.`" />
    <section class="reference-card">
      <h2>System Guides</h2>
      <p>Download system guides for master data management, database structure and Facility accounting.</p>
      <el-table :data="manuals" empty-text="The system guides are in the Recycle Bin. Restore them below.">
        <el-table-column prop="filename" label="Filename" min-width="260" />
        <el-table-column prop="release_date" label="Release date" width="160" />
        <el-table-column label="Actions" width="320"><template #default="{ row }"><div class="reference-actions"><el-button :disabled="managing" @click="download(row, true)">Download</el-button><el-button :disabled="managing" @click="rename(row)">Rename</el-button><el-button type="danger" plain :disabled="managing" @click="remove(row)">Delete</el-button></div></template></el-table-column>
      </el-table>
    </section>
    <section class="reference-card">
      <h2>Document Templates</h2>
      <p>Upload, download and manage document templates. Uploading a file with the same name keeps each version. Deleted files can be restored from the Recycle Bin.</p>
      <div v-if="can('accounts.manage')" class="reference-upload">
        <el-upload action="#" :auto-upload="false" :limit="1" accept=".docx,.dotx,.xlsx,.xltx,.pptx,.pdf" :file-list="fileList" :on-change="choose" :on-remove="clear" :disabled="saving">
          <el-button :disabled="saving">Select template</el-button>
          <template #tip><div class="el-upload__tip">DOCX, DOTX, XLSX, XLTX, PPTX or PDF. Maximum file size: 10 MB.</div></template>
        </el-upload>
        <el-button class="primary-button" :loading="saving" :disabled="!selectedFile" @click="upload">Upload template</el-button>
      </div>
      <el-table :data="files" empty-text="No document templates uploaded yet." row-key="id">
        <el-table-column prop="filename" label="Filename" min-width="240" />
        <el-table-column label="Size" width="120"><template #default="{ row }">{{ (row.byte_size / 1024).toFixed(1) }} KB</template></el-table-column>
        <el-table-column prop="uploaded_by" label="Uploaded by" min-width="130" />
        <el-table-column label="Uploaded at (Taipei)" min-width="220"><template #default="{ row }">{{ date(row.uploaded_at) }}</template></el-table-column>
        <el-table-column label="Actions" width="320"><template #default="{ row }"><div class="reference-actions"><el-button :disabled="managing" @click="download(row)">Download</el-button><el-button :disabled="managing" @click="rename(row)">Rename</el-button><el-button type="danger" plain :disabled="managing" @click="remove(row)">Delete</el-button></div></template></el-table-column>
      </el-table>
    </section>
    <section class="reference-card">
      <h2>Recycle Bin ({{ trash.length }})</h2>
      <p>Deleted files are kept here. Restoring a file returns it to its original category.</p>
      <el-table :data="trash" empty-text="The Recycle Bin is empty." :row-key="row => `${row.kind}:${row.id}`">
        <el-table-column prop="filename" label="Filename" min-width="240" />
        <el-table-column label="Category" width="130"><template #default="{ row }">{{ row.kind === 'manual' ? 'System Guides' : 'Document Templates' }}</template></el-table-column>
        <el-table-column prop="deleted_by" label="Deleted by" min-width="130" />
        <el-table-column label="Deleted at (Taipei)" min-width="220"><template #default="{ row }">{{ date(row.deleted_at) }}</template></el-table-column>
        <el-table-column label="Actions" width="100"><template #default="{ row }"><el-button :disabled="managing" @click="restore(row)">Restore</el-button></template></el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.reference-page { display: grid; gap: 24px; }
.reference-card { background: var(--surface-card, #fff); border: 1px solid #e3e6eb; border-radius: 12px; padding: 24px; }
.reference-card h2 { margin: 0 0 12px; font-size: 20px; }
.reference-card p { color: #606775; line-height: 1.6; }
.reference-upload { display: flex; align-items: flex-start; flex-wrap: wrap; gap: 20px; margin: 24px 0; }
.reference-actions { display: flex; gap: 8px; }
.reference-actions .el-button + .el-button { margin-left: 0; }
</style>
