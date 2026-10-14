<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiFetch } from '../api'
import { formatMoney, formatMoneyInput, parseMoneyInput } from '../alpha/format'
const props=defineProps({rows:{type:Array,default:()=>[]},canEdit:Boolean})
const emit=defineEmits(['refresh'])
const busy=ref(false), dialog=ref(''), active=ref(null)
const form=reactive({date:'',amount:null,note:'',reference:'',clearingType:'bank_fee',originalKey:''})
const today=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())
const originals=computed(()=>!active.value?[]:props.rows.filter(row=>row.caseUid===active.value.rootCaseUid&&row.amount>0&&row.outstanding>0&&row.currency===active.value.currency&&row.partyType===active.value.partyType&&(row.partyType==='cedant'||row.swissFacility)))
const selectedOriginal=computed(()=>originals.value.find(row=>row.key===form.originalKey))
const periodFor=row=>props.rows.find(item=>item.caseUid===row?.caseUid&&item.installmentId===row?.installmentId&&item.swissFacility)?.dueDate||''
const offsetValid=computed(()=>selectedOriginal.value&&periodFor(selectedOriginal.value)===periodFor(active.value)&&Math.abs(selectedOriginal.value.outstanding)>=Math.abs(active.value?.outstanding||0))
const identity=row=>({caseUid:row.caseUid,rowVersion:row.caseRowVersion,scheduleKey:row.scheduleKey})
async function write(body){
 if(!props.canEdit||busy.value)return
 busy.value=true
 try{const response=await apiFetch('/api/accounting',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const result=await response.json();if(!response.ok)throw new Error(result.message||result.error);dialog.value='';ElMessage.success('Accounting updated');emit('refresh')}
 catch(error){ElMessage.error(error.message);emit('refresh')}
 finally{busy.value=false}
}
async function confirm(row,undo=false){
 if(!props.canEdit)return
 if(undo){try{await ElMessageBox.confirm('Cancel the collection confirmation and recalculate the pending settlement period?','Cancel confirmation')}catch{return}}
 await write({action:undo?'unconfirm_swiss_collection':'confirm_swiss_collection',...identity(row)})
}
function open(row,kind){
 if(!props.canEdit)return
 active.value=row;Object.assign(form,{date:today(),amount:Math.abs(row.outstanding),note:'',reference:row.statementReference||'',clearingType:'bank_fee',originalKey:''});dialog.value=kind
}
async function save(){
 const row=active.value;if(!row)return
 if(dialog.value==='clearance'){
  if(!(form.amount>0)||form.amount>Math.abs(row.outstanding)||!form.note.trim())return ElMessage.warning('Enter an amount within the balance and a reason.')
  await write({action:'record_swiss_clearance',...identity(row),amount:form.amount,clearingType:form.clearingType,note:form.note})
 }else if(dialog.value==='statement'){
  if(!form.reference.trim())return ElMessage.warning('Enter the settlement statement reference.')
  await write({action:'mark_swiss_statement',...identity(row),reference:form.reference})
 }else if(dialog.value==='offset'){
  if(!offsetValid.value||!form.date)return ElMessage.warning('Select this policy’s original premium in the same settlement period.')
  const original=selectedOriginal.value
  await write({action:'record_swiss_offset',originalCaseUid:original.caseUid,refundCaseUid:row.caseUid,originalRowVersion:original.caseRowVersion,refundRowVersion:row.caseRowVersion,originalKey:original.scheduleKey,refundKey:row.scheduleKey,amount:Math.abs(row.outstanding),paymentDate:form.date,note:form.note})
 }
}
const title=computed(()=>({clearance:'Record fee / shortfall clearance',statement:active.value?.statementNeedsRevision?'Confirm revised settlement statement':'Mark settlement statement prepared',offset:'Same-policy, same-period offset'})[dialog.value]||'Accounting')
defineExpose({open,confirm})
</script>
<template>
<el-dialog :model-value="!!dialog" :title="title" width="min(680px,94vw)" :close-on-click-modal="false" @close="dialog=''">
 <template v-if="active"><p>{{ active.twRef }} · {{ active.installmentLabel }} · {{ active.partyName }}</p>
 <el-form label-position="top">
  <el-form-item v-if="dialog==='offset'" label="Receipt / payment date" required><el-date-picker v-model="form.date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
  <el-form-item v-if="dialog==='offset'" label="Original policy premium" required><el-select v-model="form.originalKey" style="width:100%"><el-option v-for="row in originals" :key="row.key" :label="row.twRef+' · '+row.installmentLabel+' · Settlement '+periodFor(row)+' · Balance '+formatMoney(row.outstanding)" :value="row.key" /></el-select></el-form-item>
  <el-form-item v-if="dialog!=='statement'" label="Amount" required><el-input-number v-model="form.amount" :disabled="dialog==='offset'" :min="0.01" :max="Math.abs(active.outstanding)" :precision="2" :controls="false" :formatter="formatMoneyInput" :parser="parseMoneyInput" /></el-form-item>
  <el-form-item v-if="dialog==='clearance'" label="Clearance type" required><el-select v-model="form.clearingType"><el-option label="Bank fee" value="bank_fee" /><el-option label="Shortfall" value="shortfall" /></el-select></el-form-item>
  <el-form-item v-if="dialog==='statement'" label="Settlement statement reference" required><el-input v-model="form.reference" maxlength="200" /></el-form-item>
  <el-form-item v-if="dialog!=='statement'" :label="dialog==='clearance'?'Reason (required)':'Note'"><el-input v-model="form.note" type="textarea" maxlength="1000" /></el-form-item>
 </el-form>
 <p v-if="dialog==='offset'">Offset the full refund against its original policy only when both use the same settlement period. Different cases and periods remain separate.</p>
 <p v-if="dialog==='statement'">Current period: {{ active.dueDate }}. Confirm after preparing or manually revising the statement.</p>
 </template>
 <template #footer><el-button @click="dialog=''">Cancel</el-button><el-button type="primary" :loading="busy" :disabled="!canEdit" @click="save">Save</el-button></template>
</el-dialog>
</template>
