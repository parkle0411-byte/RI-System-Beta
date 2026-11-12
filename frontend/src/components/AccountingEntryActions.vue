<script setup>
// 2026-11-12：只剩 Swiss 結算清單參考號；已退役且沒有入口的「保費抵銷」對話框程式已移除。
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiFetch } from '../api'
const props=defineProps({rows:{type:Array,default:()=>[]},canEdit:Boolean})
const emit=defineEmits(['refresh'])
const busy=ref(false),dialog=ref(''),active=ref(null)
const form=reactive({reference:''})
function open(row,kind){if(!props.canEdit||kind!=='statement')return;active.value=row;form.reference=row.statementReference||'';dialog.value=kind}
async function save(){
 const row=active.value;if(!row||busy.value)return
 if(!form.reference.trim())return ElMessage.warning('Enter the Swiss settlement statement reference.')
 const body={action:'mark_swiss_statement',caseUid:row.caseUid,rowVersion:row.caseRowVersion,scheduleKey:row.scheduleKey,reference:form.reference}
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
