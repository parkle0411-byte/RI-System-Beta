<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { apiFetch } from '../api'
import { auth } from '../auth'

const props = defineProps({ caseUid: {type:String, required:true}, payload: {type:Object, required:true} })
const emit = defineEmits(['changed'])
const visible = ref(false), loading = ref(false), people = ref([]), history = ref([]), version = ref(null)
const field = ref('ae'), personnelId = ref(null), reason = ref(''), confirmed = ref(false)
const allowed = computed(() => ['general_manager','admin'].includes(auth.principal?.roleCode) || Number(props.payload.ownerPersonnelId) === Number(auth.principal?.id))
const missing = computed(() => !props.payload.aePersonnelId || !props.payload.ownerPersonnelId)
const selected = computed(() => people.value.find(row => row.id === personnelId.value))
const previousName = computed(() => String(field.value === 'ae' ? props.payload.ae || '' : props.payload.ownerPersonnelName || '').trim())
const previousId = computed(() => field.value === 'ae' ? props.payload.aePersonnelId : props.payload.ownerPersonnelId)
const different = computed(() => !!selected.value && previousName.value.toLowerCase() !== selected.value.name.trim().toLowerCase())
const reasonRequired = computed(() => different.value || !!previousId.value && Number(previousId.value) !== Number(personnelId.value))
watch([field, personnelId], () => { confirmed.value = false; reason.value = '' })

async function open() {
  visible.value = true; loading.value = true
  field.value = !props.payload.aePersonnelId ? 'ae' : 'owner'; personnelId.value = null; reason.value = ''; confirmed.value = false
  try {
    const response = await apiFetch('/api/case-personnel-history?caseUid=' + encodeURIComponent(props.caseUid))
    const data = await response.json()
    if (!response.ok) throw new Error(data.message || 'Unable to load historical identities.')
    people.value = data.people || []; history.value = data.history || []; version.value = data.rowVersion
  } catch (error) { ElMessage.error(error.message); visible.value = false }
  finally { loading.value = false }
}
async function save() {
  if (!personnelId.value || reasonRequired.value && !reason.value.trim() || different.value && !confirmed.value) return
  loading.value = true
  try {
    const response = await apiFetch('/api/case-personnel-history', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({caseUid:props.caseUid, rowVersion:version.value, field:field.value, personnelId:personnelId.value, reason:reason.value, confirmed:confirmed.value})})
    const data = await response.json()
    if (!response.ok) throw new Error(data.message || 'Unable to save the historical link.')
    visible.value = false; emit('changed'); ElMessage.success('Historical Personnel link saved.')
  } catch (error) { ElMessage.error(error.message) }
  finally { loading.value = false }
}
</script>

<template>
  <div v-if="payload.personnelIdentityVersion !== 'personnel-v1'">
    <el-alert v-if="missing" type="warning" :closable="false" show-icon title="A historical Case Owner or Account Executive is not linked to Personnel." />
    <el-button v-if="allowed" text type="primary" @click="open">Confirm historical Personnel links</el-button>
    <el-dialog v-model="visible" title="Historical Personnel links" width="min(620px, 95vw)">
      <p>Confirming a historical link preserves the name recorded on the case. This is not a new assignment.</p>
      <el-form label-position="top" v-skeleton="{ on: loading, rows: 3 }">
        <el-form-item label="Case field"><el-select v-model="field"><el-option label="Account Executive" value="ae" /><el-option label="Case Owner" value="owner" /></el-select></el-form-item>
        <el-form-item label="Recorded historical name"><span>{{ previousName || '—' }}</span></el-form-item>
        <el-form-item label="Personnel"><el-select v-model="personnelId" filterable placeholder="Select a historical person"><el-option v-for="person in people" :key="person.id" :value="person.id" :label="person.name + ' — ' + person.department + (person.is_active ? '' : ' (inactive)')" /></el-select></el-form-item>
        <el-form-item label="Reason" :required="reasonRequired"><el-input v-model="reason" type="textarea" maxlength="1000" /></el-form-item>
        <el-checkbox v-if="different" v-model="confirmed">I confirm the historical name and selected Personnel refer to the same person.</el-checkbox>
      </el-form>
      <div v-if="history.length"><h3>Link history</h3><p v-for="(row,index) in history" :key="index">{{ row.changedAt }} · {{ row.changedByName }} · {{ row.field }} · {{ row.historicalName }} → {{ row.personnelName }}<span v-if="row.reason"> · {{ row.reason }}</span></p></div>
      <template #footer><el-button @click="visible=false">Cancel</el-button><el-button type="primary" :loading="loading" :disabled="!personnelId || reasonRequired &amp;&amp; !reason.trim() || different &amp;&amp; !confirmed" @click="save">Confirm link</el-button></template>
    </el-dialog>
  </div>
</template>
