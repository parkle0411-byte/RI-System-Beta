<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiFetch } from '../api'
import { formatMoney } from '../alpha/format'
const props=defineProps({rows:{type:Array,default:()=>[]},canEdit:Boolean})
const emit=defineEmits(['refresh'])
const busy=ref(false),dialog=ref(''),active=ref(null)
const form=reactive({date:'',note:'',reference:'',originalKey:''})
const periodFor=row=>props.rows.find(item=>item.caseUid===row?.caseUid&&item.installmentId===row?.installmentId&&item.swissFacility)?.dueDate||''
const originals=computed(()=>!active.value?[]:props.rows.filter(row=>row.caseUid===active.value.rootCaseUid&&row.amount>0&&row.outstanding>0&&row.currency===active.value.currency&&row.partyType===active.value.partyType&&row.partyName===active.value.partyName))
const selectedOriginal=computed(()=>originals.value.find(row=>row.key===form.originalKey))
const offsetValid=computed(()=>selectedOriginal.value&&Math.abs(selectedOriginal.value.outstanding)>=Math.abs(active.value?.outstanding||0)&&periodFor(selectedOriginal.value)===periodFor(active.value))
function open(row,kind){if(!props.canEdit)return;active.value=row;Object.assign(form,{date:new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()),note:'',reference:row.statementReference||'',originalKey:''});dialog.value=kind}
async function save(){
 const row=active.value;if(!row||busy.value)return
 let body
 if(dialog.value==='statement'){
  if(!form.reference.trim())return ElMessage.warning('Enter the Swiss settlement statement reference.')
  body={action:'mark_swiss_statement',caseUid:row.caseUid,rowVersion:row.caseRowVersion,scheduleKey:row.scheduleKey,reference:form.reference}
 }else{
  if(!offsetValid.value||!form.date)return ElMessage.warning('Select the matching original policy with sufficient balance. Swiss must use the same settlement period.')
  const original=selectedOriginal.value
  body={action:'record_premium_offset',originalCaseUid:original.caseUid,refundCaseUid:row.caseUid,originalRowVersion:original.caseRowVersion,refundRowVersion:row.caseRowVersion,originalKey:original.scheduleKey,refundKey:row.scheduleKey,amount:Math.abs(row.outstanding),paymentDate:form.date,note:form.note}
 }
 busy.value=true
 try{const response=await apiFetch('/api/accounting',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const result=await response.json();if(!response.ok)throw new Error(result.message||result.error);dialog.value='';ElMessage.success('Accounting updated');emit('refresh')}
 catch(error){ElMessage.error(error.message);emit('refresh')}finally{busy.value=false}
}
defineExpose({open})
</script>
<template>
<el-dialog :model-value="!!dialog" :title="'Swiss settlement statement reference'" width="min(680px,94vw)" :close-on-click-modal="false" @close="dialog=''">
 <template v-if="active"><p>{{ active.twRef }} · {{ active.installmentLabel }} · {{ active.partyName }}</p>
 <el-form label-position="top">
  <template><p>Swiss due date: {{ active.contractDueDate || active.dueDate }}. All Cedant receipts for this installment must be fully received and automatically settled first.</p><el-form-item label="Settlement statement reference" required><el-input v-model="form.reference" maxlength="200" placeholder="SWRPA-xxxxxxx-xxxxxxxx" /><small>Format: SWRPA-xxxxxxx-xxxxxxxx</small></el-form-item></template>
 </el-form></template>
 <template #footer><el-button @click="dialog=''">Cancel</el-button><el-button type="primary" :loading="busy" @click="save">Save</el-button></template>
</el-dialog>
</template>
