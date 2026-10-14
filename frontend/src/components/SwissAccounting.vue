<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiFetch } from '../api'
import { formatMoney, formatMoneyInput, parseMoneyInput } from '../alpha/format'
const props=defineProps({rows:{type:Array,default:()=>[]},canEdit:Boolean})
const emit=defineEmits(['refresh','open-batch'])
const busy=ref(false), dialog=ref(''), active=ref(null), history=ref(null)
const form=reactive({date:'',amount:null,note:'',reference:'',clearingType:'bank_fee',originalKey:''})
const today=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())
const visibleRows=computed(()=>props.rows.filter(r=>r.partyType==='cedant'||r.swissFacility||r.requiresCollectionConfirmation))
const originals=computed(()=>!active.value?[]:props.rows.filter(r=>r.caseUid===active.value.rootCaseUid&&r.amount>0&&r.outstanding>0&&r.currency===active.value.currency&&r.partyType===active.value.partyType&&(r.partyType==='cedant'||r.swissFacility)))
const selectedOriginal=computed(()=>originals.value.find(r=>r.key===form.originalKey))
const periodFor=row=>props.rows.find(r=>r.caseUid===row?.caseUid&&r.installmentId===row?.installmentId&&r.swissFacility)?.dueDate||''
const offsetValid=computed(()=>selectedOriginal.value&&periodFor(selectedOriginal.value)===periodFor(active.value)&&Math.abs(selectedOriginal.value.outstanding)>=Math.abs(active.value?.outstanding||0))
const fullPayment=row=>row.fullPaymentRequired
const incoming=row=>(row.partyType==='cedant'&&row.amount>0)||(row.partyType==='reinsurer'&&row.amount<0)
const eligiblePayment=row=>!!row.dueDate&&Math.abs(row.outstanding)>.004&&row.paymentAllowed!==false&&!row.statementNeedsRevision
const identity=row=>({caseUid:row.caseUid,rowVersion:row.caseRowVersion,scheduleKey:row.scheduleKey})
async function write(body){
 busy.value=true
 try{const response=await apiFetch('/api/accounting',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const result=await response.json();if(!response.ok)throw new Error(result.message||result.error);dialog.value='';history.value=null;ElMessage.success('Accounting updated');emit('refresh')}
 catch(error){ElMessage.error(error.message);emit('refresh')}
 finally{busy.value=false}
}
async function confirm(row,undo=false){
 if(undo){try{await ElMessageBox.confirm('Cancel the collection confirmation and recalculate the pending Swiss period?','Cancel confirmation')}catch{return}}
 await write({action:undo?'unconfirm_swiss_collection':'confirm_swiss_collection',...identity(row)})
}
function open(row,kind){active.value=row;Object.assign(form,{date:today(),amount:Math.abs(row.outstanding),note:'',reference:row.statementReference||'',clearingType:'bank_fee',originalKey:''});dialog.value=kind}
async function save(){
 const row=active.value;if(!row)return
 if(dialog.value==='payment'){
  if(!form.date||!(form.amount>0)||form.amount>Math.abs(row.outstanding)||(fullPayment(row)&&Math.abs(form.amount-Math.abs(row.outstanding))>.004))return ElMessage.warning('Enter a valid receipt amount, or the entire payable balance.')
  await write({action:'record_payment',...identity(row),paymentDate:form.date,amount:form.amount,note:form.note,reference:form.reference})
 }else if(dialog.value==='clearance'){
  if(!(form.amount>0)||!form.note.trim())return ElMessage.warning('Enter the clearance amount and reason.')
  await write({action:'record_swiss_clearance',...identity(row),amount:form.amount,clearingType:form.clearingType,note:form.note})
 }else if(dialog.value==='statement'){
  if(!form.reference.trim())return ElMessage.warning('Enter the settlement statement reference.')
  await write({action:'mark_swiss_statement',...identity(row),reference:form.reference})
 }else if(dialog.value==='offset'){
  if(!offsetValid.value||!form.date)return ElMessage.warning('Select this policy’s original premium in the same Swiss settlement period.')
  const original=selectedOriginal.value
  await write({action:'record_swiss_offset',originalCaseUid:original.caseUid,refundCaseUid:row.caseUid,originalRowVersion:original.caseRowVersion,refundRowVersion:row.caseRowVersion,originalKey:original.scheduleKey,refundKey:row.scheduleKey,amount:Math.abs(row.outstanding),paymentDate:form.date,note:form.note})
 }
}
async function reverse(row,entry){
 if(entry.batchId){emit('open-batch',entry.batchId);return}
 try{const result=await ElMessageBox.prompt('Enter the reason for reversing this original record. The original date, amount and any Swiss settlement period remain in history.','Reverse receipt / bank return',{inputValidator:v=>!!v?.trim()||'A reason is required.'});await write({action:'reverse_payment',...identity(row),entryId:entry.id,paymentDate:today(),note:result.value})}catch{}
}
const title=computed(()=>({payment:incoming(active.value||{})?'Record receipt':'Record full payment',clearance:'Record fee / shortfall clearance',statement:active.value?.statementNeedsRevision?'Confirm revised settlement statement':'Mark settlement statement prepared',offset:'Same-policy, same-period offset'})[dialog.value]||'Accounting')
</script>
<template>
<section class="table-card swiss-accounting" v-loading="busy">
 <div class="section-heading"><div><h2>Swiss Facility · Property</h2><p>Cedant dates: 75-day reminder / 90-day deadline. Swiss settlements: 14 February, May, August and November.</p></div></div>
 <el-table :data="visibleRows" row-key="key" data-testid="swiss-accounting-table" empty-text="No announced Swiss Facility Property entries yet. Entries appear here after a Property case using Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility) is announced.">
  <el-table-column label="Case / installment" min-width="210"><template #default="{row}">{{ row.twRef }}<br><small>{{ row.installmentLabel }}</small></template></el-table-column>
  <el-table-column label="Party / direction" min-width="230"><template #default="{row}">{{ row.partyName }}<br><small>{{ incoming(row)?'Receivable':'Payable' }} · {{ row.amount<0?'Return premium':'Premium' }}</small></template></el-table-column>
  <el-table-column label="Amount / outstanding" min-width="170" align="right"><template #default="{row}">{{ row.currency }} {{ formatMoney(row.amount) }}<br><strong>{{ formatMoney(row.outstanding) }}</strong></template></el-table-column>
  <el-table-column label="Dates" min-width="235"><template #default="{row}">
   <template v-if="row.swissFacility"><div>Original: {{ row.originalDueDate||'—' }}</div><div>{{ row.projectedDueDate?'Projected':'Settlement' }}: {{ row.dueDate||'—' }}</div><small v-if="row.confirmationCutoff">Cutoff: {{ row.confirmationCutoff }}</small></template>
   <template v-else><div>Accounting: {{ row.dueDate||'—' }}</div><small v-if="row.contractDueDate">Contract: {{ row.contractDueDate }}</small></template>
   <small v-if="row.status==='overdue'" class="overdue">Overdue</small><small v-else-if="row.status==='reminder'">75-day reminder</small>
  </template></el-table-column>
  <el-table-column label="Collection confirmation" min-width="225"><template #default="{row}">
   <template v-if="row.requiresCollectionConfirmation"><el-tag :type="row.collectionConfirmed?'success':'warning'">{{ row.collectionConfirmed?'Confirmed collected':'Confirmation needed' }}</el-tag><div v-if="row.collectionConfirmedAt"><small>{{ row.collectionConfirmedAt }} · {{ row.collectionConfirmationSource }}</small></div><small v-if="row.latestReceiptDate">Latest receipt: {{ row.latestReceiptDate }}</small></template>
   <small v-if="row.paymentAllowed===false">{{ row.paymentBlockedReason }}</small>
   <small v-if="row.statementNeedsRevision" class="overdue">Statement moved from {{ row.statementDueDate }}. Revise manually.</small>
  </template></el-table-column>
  <el-table-column label="Action" min-width="240"><template #default="{row}">
   <template v-if="canEdit">
    <el-button v-if="Math.abs(row.outstanding)>.004" text type="primary" :disabled="!eligiblePayment(row)" @click="open(row,'payment')">{{ incoming(row)?'Record receipt':'Record full payment' }}</el-button>
    <el-button v-if="row.requiresCollectionConfirmation&&!row.collectionConfirmed" text type="primary" :disabled="!row.canConfirmCollection" @click="confirm(row)">Confirm collected</el-button>
    <el-button v-if="row.requiresCollectionConfirmation&&row.collectionConfirmed" text @click="confirm(row,true)">Cancel confirmation</el-button>
    <el-button v-if="row.requiresCollectionConfirmation&&Math.abs(row.outstanding)>.004" text @click="open(row,'clearance')">Fee / shortfall</el-button>
    <el-button v-if="row.amount<0&&Math.abs(row.outstanding)>.004&&(row.partyType==='cedant'||row.swissFacility)&&row.rootCaseUid!==row.caseUid" text @click="open(row,'offset')">Offset with original</el-button>
    <el-button v-if="row.swissFacility&&row.amount>0&&row.outstanding>.004" text @click="open(row,'statement')">{{ row.statementNeedsRevision?'Confirm revised statement':'Statement reference' }}</el-button>
   </template>
   <el-button v-if="row.entries?.length" text @click="history=row">History</el-button>
  </template></el-table-column>
 </el-table>
</section>
<el-dialog :model-value="!!dialog" :title="title" width="min(680px,94vw)" :close-on-click-modal="false" @close="dialog=''">
 <template v-if="active"><p>{{ active.twRef }} · {{ active.installmentLabel }} · {{ active.partyName }}</p>
 <el-form label-position="top">
  <el-form-item v-if="dialog==='payment'||dialog==='offset'" label="Receipt / payment date" required><el-date-picker v-model="form.date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
  <el-form-item v-if="dialog==='offset'" label="Original policy premium" required><el-select v-model="form.originalKey" style="width:100%"><el-option v-for="row in originals" :key="row.key" :label="row.twRef+' · '+row.installmentLabel+' · Swiss '+periodFor(row)+' · Balance '+formatMoney(row.outstanding)" :value="row.key" /></el-select></el-form-item>
  <el-form-item v-if="dialog!=='statement'" label="Amount" required><el-input-number v-model="form.amount" :disabled="dialog==='offset'||(dialog==='payment'&&fullPayment(active))" :min="0.01" :max="Math.abs(active.outstanding)" :precision="2" :controls="false" :formatter="formatMoneyInput" :parser="parseMoneyInput" /></el-form-item>
  <el-form-item v-if="dialog==='clearance'" label="Clearance type" required><el-select v-model="form.clearingType"><el-option label="Bank fee" value="bank_fee" /><el-option label="Shortfall" value="shortfall" /></el-select></el-form-item>
  <el-form-item v-if="dialog==='statement'" label="Settlement statement reference" required><el-input v-model="form.reference" maxlength="200" /></el-form-item>
  <el-form-item v-if="dialog!=='statement'" :label="dialog==='clearance'?'Reason (required)':'Note'"><el-input v-model="form.note" type="textarea" maxlength="1000" /></el-form-item>
 </el-form>
 <p v-if="dialog==='offset'">Offset the full refund against its original policy only when both use the same Swiss settlement period. Different cases and periods remain separate.</p>
 <p v-if="dialog==='statement'">Current period: {{ active.dueDate }}. Confirm after preparing or manually revising the statement.</p>
 </template>
 <template #footer><el-button @click="dialog=''">Cancel</el-button><el-button type="primary" :loading="busy" @click="save">Save</el-button></template>
</el-dialog>
<el-dialog :model-value="!!history" title="Swiss accounting history" width="min(850px,94vw)" @close="history=null">
 <el-table :data="history?.entries||[]"><el-table-column prop="paymentDate" label="Date" /><el-table-column label="Type"><template #default="{row}">{{ row.entryType }}{{ row.entryKind?' · '+row.entryKind:'' }}</template></el-table-column><el-table-column label="Amount"><template #default="{row}">{{ formatMoney(row.amount) }}</template></el-table-column><el-table-column prop="settlementDueDate" label="Swiss period" /><el-table-column prop="note" label="Reason" /><el-table-column label="Action" min-width="140"><template #default="{row}"><el-button v-if="canEdit&&row.entryType==='payment'&&!row.offsetId&&!history.entries.some(e=>e.reversalOf===row.id)" text type="danger" @click="reverse(history,row)">{{ row.batchId?'View remittance':'Reverse / bank return' }}</el-button></template></el-table-column></el-table>
</el-dialog>
</template>
<style scoped>.overdue{display:block;color:var(--el-color-danger)}small{display:block}</style>
