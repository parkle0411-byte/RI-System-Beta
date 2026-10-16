<script setup>
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiFetch } from '../api'
import { can } from '../auth'
import { displayTwRef } from '../alpha/manualTwRef'
const emit = defineEmits(['saved', 'refresh'])
const visible = ref(false), loading = ref(false), saving = ref(false), current = ref(null)
const form = reactive({ statementNo: '', reinsurers: [] })
async function readResponse(response) {
  const body = await response.json()
  if (!response.ok) { const error = new Error(body.message || body.error || 'Unable to update references.'); error.status = response.status; throw error }
  return body
}
async function open(caseUid) {
  if (!can('cases.write') || loading.value || saving.value) return
  loading.value = true; current.value = null; visible.value = true
  try {
    const body = await readResponse(await apiFetch('/api/case-reconciliation-references?caseUid=' + encodeURIComponent(caseUid)))
    current.value = body.case
    form.statementNo = body.case.statementNo || ''
    form.reinsurers = body.case.reinsurers.map(row => ({ ...row }))
  } catch (error) { visible.value = false; ElMessage.error(error.message); emit('refresh') }
  finally { loading.value = false }
}
async function save() {
  if (!current.value || !can('cases.write') || loading.value || saving.value) return
  saving.value = true
  try {
    const body = await readResponse(await apiFetch('/api/case-reconciliation-references', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ caseUid: current.value.caseUid, rowVersion: current.value.rowVersion,
        statementNo: form.statementNo, reinsurers: form.reinsurers.map(row => ({ index: row.index, settlementRef: row.settlementRef })) })
    }))
    visible.value = false
    ElMessage.success(body.changed === false ? 'References are up to date' : 'Reconciliation references updated')
    emit('saved', body.case)
  } catch (error) {
    ElMessage.error(error.message)
    if (error.status === 409 || error.status === 404) { visible.value = false; emit('refresh') }
  } finally { saving.value = false }
}
defineExpose({ open })
</script>
<template>
<el-dialog v-model="visible" title="Edit Reconciliation References" width="min(640px, 94vw)" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving" destroy-on-close>
  <div v-loading="loading">
    <template v-if="current">
      <p><strong>{{ displayTwRef(current) }}</strong><br>{{ current.originalInsured || '—' }}<template v-if="current.originalInsuredCn"><br>{{ current.originalInsuredCn }}</template></p>
      <p>Updates apply to all entries for this case.</p>
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="Statement No."><el-input v-model="form.statementNo" maxlength="160" clearable /></el-form-item>
        <el-form-item v-for="row in form.reinsurers" :key="row.index" :label="'Reinsurer Ref. · ' + (row.name || 'Reinsurer ' + (row.index + 1))"><el-input v-model="row.settlementRef" maxlength="160" clearable /></el-form-item>
      </el-form>
    </template>
  </div>
  <template #footer><el-button :disabled="saving" @click="visible = false">Cancel</el-button><el-button type="primary" :disabled="loading || !current" :loading="saving" @click="save">Save references</el-button></template>
</el-dialog>
</template>
