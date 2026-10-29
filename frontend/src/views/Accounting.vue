<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiFetch } from '../api'
import { can } from '../auth'
import { recall, remember } from './accountingMemory'
import { formatMoney, formatMoneyInput, parseMoneyInput, reportWriteError } from '../alpha/format'
import { shell } from '../alpha/shell'
import { displayTwRef } from '../alpha/manualTwRef'
import { transactionNumber } from '../alpha/transactionNumber'
import { transactionParty, paymentDirection } from '../alpha/transactionParty'
import vSyncInputNumberAria from '../directives/syncInputNumberAria'
import AccountingEntryActions from '../components/AccountingEntryActions.vue'
import ReconciliationReferences from '../components/ReconciliationReferences.vue'
import { accountingRows } from '../alpha/accountingRows'
const router=useRouter()
const loading=ref(false), saving=ref(false), rows=ref([]), batches=ref([]), currencies=ref([]), canEdit=ref(false), selected=ref([])
const filters=reactive({reference:'',party:'',currency:'',leg:'',settlement:'',source:'',from:'',to:''})
const swissRows=ref([])
const refreshing=ref(false), shownAt=ref('')
const dataWarnings=ref([])
const entryActions=ref(null), referenceEditor=ref(null)
const paymentVisible=ref(false), historyRow=ref(null), batchVisible=ref(false), activeBatch=ref(null)
const payment=reactive({date:today(),amount:null,reference:'',note:'',allocations:[]})
function today(){return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())}
const filtered=computed(()=>rows.value.filter(r=>{
  const includes=(values,query)=>values.some(v=>String(v||'').toLowerCase().includes(query.trim().toLowerCase()))
  return (!filters.reference||includes([r.statementNo,r.txNo,transactionNumber(r.txNo),r.reconciliationRef,displayTwRef(r)],filters.reference)) && (!filters.party||includes([transactionParty(r),r.reinsurer],filters.party)) && (!filters.currency||r.currency===filters.currency) && (!filters.leg||String(r.legType||'').startsWith(filters.leg)) && (!filters.settlement||r.settlement===filters.settlement) && (!filters.source||r.source===filters.source) && (!filters.from||!r.announcedAt||String(r.announcedAt).slice(0,10)>=filters.from) && (!filters.to||!r.announcedAt||String(r.announcedAt).slice(0,10)<=filters.to)
}))
// 2026-10-15：列表分頁。1 萬件案件約 1.8 萬列，一次全部畫出會讓瀏覽器卡住；篩選仍在全部資料上進行，只有顯示分頁。
const pageSize=ref(100), page=ref(1)
const pagedRows=computed(()=>filtered.value.slice((page.value-1)*pageSize.value,page.value*pageSize.value))
watch(filters,()=>{page.value=1},{deep:true})
watch(pageSize,()=>{page.value=1})
watch(filtered,list=>{const last=Math.max(1,Math.ceil(list.length/pageSize.value));if(page.value>last)page.value=last})
const toCents=v=>Math.round(Number(v||0)*100)
const allocated=computed(()=>payment.allocations.reduce((sum,a)=>sum+toCents(a.amount),0)/100)
const difference=computed(()=>(toCents(payment.amount)-toCents(allocated.value))/100)
function statusLabel(r){return r.reversed?'Reversed':r.isReversalEntry?'Reversal entry':({settled:'Settled',partial:'Partial',open:'Open',pending_confirmation:'Awaiting confirmation',not_tracked:'Not tracked'})[r.settlement]||'Open'}
const isGreatAmericanRecord=row=>!!(row.greatAmericanFacility||row.greatAmericanCase||row.greatAmericanCaseClaim||row.schedules?.some(item=>item.greatAmericanCase))
const isQbeRecord=row=>!!(row.qbeFacility||row.qbeCase||row.qbeCaseClaim||row.schedules?.some(item=>item.qbeCase))
function registrationScope(row){
 if(row.source==='claim')return JSON.stringify([row.caseUid,'claim',row.claimId,row.paymentId])
 if(row.partyType==='cedant'&&row.amount<0)return JSON.stringify([row.caseUid,'return-endorsement'])
 const periods=[...new Set((row.schedules||[]).map(item=>item.installmentId).filter(Boolean))]
 return periods.length===1?JSON.stringify([row.caseUid,'premium',periods[0]]):null
}
function compatible(row){
 if(!selected.value.length)return true
 const first=selected.value[0]
 if(first.paymentGroup!==row.paymentGroup)return false
 if(selected.value.some(r=>r.allianzFacility||r.allianzCaseClaim)||row.allianzFacility||row.allianzCaseClaim){
  if(selected.value.some(r=>r.source!==row.source))return false
  if(row.source!=='claim'&&selected.value.some(r=>r.contractDueDate!==row.contractDueDate))return false
 }
 const candidates=[...selected.value,row]
 if(candidates.some(r=>isGreatAmericanRecord(r)||isQbeRecord(r))){
  const scope=registrationScope(row)
  if(!scope||candidates.some(r=>registrationScope(r)!==scope))return false
 }
 return true
}
function eligible(row){return compatible(row)&&canEdit.value&&!row.scheduleOnly&&row.canRecord&&row.paymentAllowed!==false&&!row.statementNeedsRevision&&(!selected.value.length||selected.value[0].paymentGroup===row.paymentGroup)}
const rowTitle=row=>row.scheduleOnly?'Premium · '+row.installmentLabel:transactionNumber(row.txNo)
const needsCollection=row=>row.schedules?.some(item=>item.requiresCollectionConfirmation)
const offsetAllowed=item=>item.offsetAllowed!==false&&item.amount<0&&Math.abs(item.outstanding)>.004&&item.rootCaseUid!==item.caseUid
const statementAllowed=item=>item.swissFacility&&item.collectionConfirmed&&item.amount>0&&item.outstanding>.004
const hasEntryActions=row=>row.schedules?.some(item=>offsetAllowed(item)||statementAllowed(item))
function toggle(row,value){selected.value=value?[...selected.value,row]:selected.value.filter(r=>r.key!==row.key)}
async function load(){
 loading.value=!refreshing.value;shell.error=''
 try{const response=await apiFetch('/api/accounting?view=list');const body=await response.json();if(!response.ok)throw new Error(body.message||body.error);apply(body);remember(body)
 }catch(err){shell.error=err.message;ElMessage.error(err.message)}finally{loading.value=false;refreshing.value=false}
}
function apply(body){
 swissRows.value=[...new Map([...(body.scheduleRows||[]),...(body.rows||[]).filter(r=>r.source==='premium'),...(body.swissRows||[])].map(r=>[r.key,r])).values()];dataWarnings.value=(body.warnings||[]).filter(w=>w.dataError);rows.value=accountingRows(body);batches.value=body.cashBatches||[];currencies.value=[...new Set([...(body.currencies||[]),...rows.value.map(row=>row.currency).filter(Boolean)])].sort();canEdit.value=!!body.scope?.canEdit;selected.value=[]
 if(historyRow.value)historyRow.value=rows.value.find(r=>r.key===historyRow.value.key)||null
 if(activeBatch.value)activeBatch.value=batches.value.find(b=>b.batchId===activeBatch.value.batchId)||null
}
// 回到這一頁：先顯示上次的清單（更新完成前不能記收款或確認），背景重新載入
function start(){
 const saved=recall()
 if(saved){apply(saved.body);canEdit.value=false;refreshing.value=true;shownAt.value=saved.at.toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'})}
 load()
}
async function post(body){const response=await apiFetch('/api/accounting',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const result=await response.json();if(!response.ok){const err=new Error(result.message||result.error);err.status=response.status;throw err}return result}
function openPayment(targets){if(!targets.length)return;payment.date=today();payment.reference='';payment.note='';payment.amount=targets.every(r=>r.fullPaymentRequired)?targets.reduce((s,r)=>s+Math.abs(r.outstanding),0):targets.length===1?Math.abs(targets[0].outstanding):null;payment.allocations=targets.map(row=>({row,amount:row.fullPaymentRequired||targets.length===1?Math.abs(row.outstanding):null}));paymentVisible.value=true}
async function savePayment(){
 if(!payment.reference.trim()&&!payment.note.trim())return ElMessage.warning('Enter an external reference or registration explanation.')
 if(payment.allocations.length===1)payment.allocations[0].amount=payment.amount
 if(!payment.date||toCents(payment.amount)<=0||difference.value!==0||payment.allocations.some(a=>toCents(a.amount)<=0||toCents(a.amount)>Math.abs(toCents(a.row.outstanding))||(a.row.fullPaymentRequired&&toCents(a.amount)!==Math.abs(toCents(a.row.outstanding)))))return ElMessage.warning('Enter positive allocations within each balance. The allocations must equal the recorded receipt/payment amount.')
 saving.value=true
 try{const single=payment.allocations.length===1&&payment.allocations[0].row.scheduleOnly?payment.allocations[0].row:null
 await post(single?{action:'record_payment',caseUid:single.caseUid,rowVersion:single.caseRowVersion,scheduleKey:single.scheduleKey,paymentDate:payment.date,amount:payment.amount,reference:payment.reference,note:payment.note}:{action:'record_transaction_payments',paymentDate:payment.date,amount:payment.amount,reference:payment.reference,note:payment.note,allocations:payment.allocations.map(a=>({caseUid:a.row.caseUid,txNo:a.row.txNo,rowVersion:a.row.caseRowVersion,amount:a.amount}))});paymentVisible.value=false;ElMessage.success('Payment recorded');await load()}
 catch(err){if(err.status===409)paymentVisible.value=false;reportWriteError(err,()=>load());await load()}finally{saving.value=false}
}
function showBatch(id){activeBatch.value=batches.value.find(b=>b.batchId===id)||null;if(activeBatch.value)batchVisible.value=true}
async function reverseBatch(){const batch=activeBatch.value;if(!batch?.canReverse||!canEdit.value)return
 let reason;try{const result=await ElMessageBox.prompt('Enter the correction reason for these registered amounts. Original entries remain in history.','Reverse receipt / payment',{inputValidator:v=>!!v?.trim()||'A reason is required.'});reason=result.value}catch{return}
 saving.value=true
 try{const versions=new Map(batch.allocations.map(a=>[a.caseUid,a.caseRowVersion]));await post({action:'reverse_batch_payment',batchId:batch.batchId,cases:[...versions].map(([caseUid,rowVersion])=>({caseUid,rowVersion})),paymentDate:today(),note:reason});ElMessage.success('Receipt / payment records reversed');await load()}catch(err){reportWriteError(err,()=>load());await load()}finally{saving.value=false}
}
async function reverseLegacy(row,entry){
 try{await ElMessageBox.confirm('Reverse the complete original schedule payment. All transaction balances sharing this payment will be recalculated.','Reverse legacy payment',{type:'warning'})}catch{return}
 saving.value=true
 try{await post({action:'reverse_payment',caseUid:row.caseUid,rowVersion:row.caseRowVersion,entryId:entry.id,paymentDate:today(),note:'Correction reversal'});await load()}catch(err){reportWriteError(err,()=>load());await load()}finally{saving.value=false}
}
async function confirmSettlement(row,undo=false){
 if(!canEdit.value)return
 let note
 try{const result=await ElMessageBox.prompt(undo?'Enter the reason for cancelling this settlement confirmation.':(row.greatAmericanFacility||row.qbeFacility)&&row.amount>0?'Confirm Accounting’s recorded full payment and manually checked bank success, then enter its reconciliation reference. Recipient receipt and bank-return/re-payment follow-up are retained by Accounting externally.':'Confirm the reconciliation and enter its reference or reason.',undo?'Cancel settlement confirmation':'Confirm settlement',{inputValidator:v=>!!v?.trim()||'A reference or reason is required.'});note=result.value}catch{return}
 saving.value=true
 try{await post({action:undo?'unconfirm_facility_settlement':'confirm_facility_settlement',caseUid:row.caseUid,rowVersion:row.caseRowVersion,...(row.scheduleOnly?{scheduleKey:row.scheduleKey}:{txNo:row.txNo}),note});ElMessage.success(undo?'Settlement confirmation cancelled':'Settlement confirmed by Accounting');await load()}catch(err){reportWriteError(err,()=>load());await load()}finally{saving.value=false}
}
async function recordAllianzFollowup(row){
 if(!canEdit.value)return
 let note;try{const result=await ElMessageBox.prompt('Enter the claim follow-up record.',row.qbeClaim?'QBE claim follow-up':row.greatAmericanClaim?'Great American claim follow-up':'Allianz claim follow-up',{inputValidator:v=>!!v?.trim()||'A follow-up record is required.'});note=result.value}catch{return}
 saving.value=true
 try{await post({action:row.qbeClaim?'record_qbe_claim_followup':row.greatAmericanClaim?'record_great_american_claim_followup':'record_allianz_claim_followup',caseUid:row.caseUid,rowVersion:row.caseRowVersion,txNo:row.txNo,note});ElMessage.success('Claim follow-up recorded');await load()}catch(error){reportWriteError(error,()=>load());await load()}finally{saving.value=false}
}
const editVisible=ref(false),editTarget=ref(null),editMode=ref('amount')
const editForm=reactive({amount:null,days:null,reason:''})
function editPaymentRecord(row,entry){editTarget.value={row,entry};editMode.value='amount';Object.assign(editForm,{amount:Math.abs(entry.amount),days:null,reason:''});editVisible.value=true}
function fillTerms(row,item){editTarget.value={row,item};editMode.value='terms';Object.assign(editForm,{amount:null,days:null,reason:''});editVisible.value=true}
async function saveEdit(){
 const target=editTarget.value;if(!target||!editForm.reason.trim())return ElMessage.warning('Enter a reason.')
 const body={caseUid:target.row.caseUid,rowVersion:target.row.caseRowVersion,reason:editForm.reason}
 if(editMode.value==='terms')Object.assign(body,{action:'complete_payment_terms',installmentId:target.item.installmentId,partyKey:target.item.partyKey,days:editForm.days})
 else Object.assign(body,{action:'edit_payment',entryId:target.entry.id,amount:editForm.amount})
 saving.value=true
 try{await post(body);editVisible.value=false;ElMessage.success('Updated with history');await load()}catch(error){reportWriteError(error,()=>load())}finally{saving.value=false}
}
function openCase(row){router.push({path:'/cases',query:{case:row.caseUid,tab:'soa'}})}
onMounted(start)
</script>
<template>
<div class="overview-stack">
<el-alert v-if="refreshing" type="info" :closable="false" show-icon data-testid="accounting-refreshing" :title="'Showing the list loaded at '+shownAt+'. Updating… Recording and confirmations are available after the update.'" />
<el-alert v-if="dataWarnings.length" type="error" :closable="false" show-icon title="Some cases could not be read and are not shown" :description="dataWarnings.map(w=>(w.twRef||w.caseUid)).join(', ')+'. Contact the System Administrator.'" />
<section class="table-card">
 <div class="section-heading"><div><h2>Accounting · SoA / Transactions</h2><p>Record which obligations have been received or paid. Premiums require the full outstanding amount; claims allow partial amounts. Full receipts/payments automatically settle and lock their accounts. Premium/refund offsets are disabled. Each reinsurer T3 settles after its own T1 and T2 complete. Any settled T3 locks all T2/T3 amounts for that installment.</p></div><el-button :loading="loading" @click="load">Refresh</el-button></div>
 <div class="form-grid cols-3">
  <el-form-item label="SoA / Transaction / Reference"><el-input v-model="filters.reference" clearable /></el-form-item>
  <el-form-item label="Cedant / Reinsurer / R/I Broker"><el-input v-model="filters.party" clearable /></el-form-item>
  <el-form-item label="Currency"><el-select v-model="filters.currency" clearable placeholder="All"><el-option v-for="currency in currencies" :key="currency" :label="currency" :value="currency" /></el-select></el-form-item>
  <el-form-item label="Leg"><el-select v-model="filters.leg" clearable placeholder="All"><el-option v-for="leg in ['Leg 1','Leg 2','Leg 3','Claim Leg 1','Claim Leg 2']" :key="leg" :label="leg" :value="leg" /></el-select></el-form-item>
  <el-form-item label="Settlement"><el-select v-model="filters.settlement" clearable placeholder="All"><el-option v-for="state in ['open','partial','pending_confirmation','settled']" :key="state" :label="state" :value="state" /></el-select></el-form-item>
  <el-form-item label="Type"><el-select v-model="filters.source" clearable placeholder="All"><el-option label="Premium" value="premium" /><el-option label="Claim" value="claim" /></el-select></el-form-item>
  <el-form-item label="Announced from"><el-date-picker v-model="filters.from" type="date" value-format="YYYY-MM-DD" /></el-form-item>
  <el-form-item label="Announced to"><el-date-picker v-model="filters.to" type="date" value-format="YYYY-MM-DD" /></el-form-item>
 </div>
</section>
<section class="table-card" v-loading="loading">
 <div class="section-heading"><div><h2>SoA / Transactions ({{ filtered.length }})</h2><p>Select obligations with the same currency, receipt/payment direction and counterparty to record their amounts.</p></div><el-button v-if="canEdit" class="primary-button" :disabled="!selected.length" @click="openPayment(selected)">Record selected ({{ selected.length }})</el-button></div>
 <el-table :data="pagedRows" row-key="key" data-testid="accounting-table" empty-text="No accounting entries. Premium transactions appear at Announce, including all installments. Production confirms performance without creating duplicate accounts.">
  <el-table-column v-if="canEdit" width="44"><template #default="{row}"><el-checkbox v-if="!row.scheduleOnly" :model-value="selected.some(r=>r.key===row.key)" :disabled="!eligible(row)" :aria-label="'Select '+transactionNumber(row.txNo)" @change="value=>toggle(row,value)" /></template></el-table-column>
  <el-table-column label="Transaction / SoA / TW Ref" min-width="250" fixed="left"><template #default="{row}"><el-button v-if="can('cases.read.all')" text class="table-action" @click="openCase(row)">{{ rowTitle(row) }}</el-button><strong v-else>{{ rowTitle(row) }}</strong><br><small>SoA: {{ row.statementNo||'—' }}<br>{{ displayTwRef(row) }} · {{ row.installmentLabel|| (row.source==='claim'?'Claim':'Premium') }}</small><small v-if="row.scheduleOnly">Awaiting Production close</small><small v-if="row.reversed||row.isReversalEntry">{{ statusLabel(row) }}</small></template></el-table-column>
  <el-table-column label="Original Insured (EN / CN)" min-width="240"><template #default="{row}"><div>{{ row.originalInsured||'—' }}</div><div>{{ row.originalInsuredCn||'—' }}</div></template></el-table-column>
  <el-table-column label="TWD valuation" min-width="155"><template #default="{row}"><span v-if="row.outstandingNtd!=null">{{ formatMoney(row.outstandingNtd,'TWD') }}</span><span v-else>Awaiting FX</span><small>{{ row.fxEstimated?'Estimated · latest FX':'Formal posting FX' }} {{ row.fxMonth||'' }}</small></template></el-table-column>
 <el-table-column label="Reconciliation Ref" min-width="160"><template #default="{row}">{{ row.reconciliationRef||'—' }}<br><el-button v-if="can('cases.write') && ['posted','closed'].includes(row.caseStatus)" text type="primary" size="small" @click="referenceEditor.open(row.caseUid)">Edit references</el-button></template></el-table-column>
  <el-table-column label="Reinsurer allocation" min-width="200"><template #default="{row}">{{ row.reinsurerName||row.reinsurer||'—' }}</template></el-table-column>
  <el-table-column label="Party / Leg" min-width="190"><template #default="{row}">{{ transactionParty(row) }}<br><small>{{ row.legType }} · {{ paymentDirection(row) }}</small><br><small>{{ row.source==='claim'?'Claim':row.returnPremium?'Return premium':'Premium' }}</small></template></el-table-column>
  <el-table-column label="Amount" align="right" min-width="135"><template #default="{row}">{{ row.currency }} {{ formatMoney(row.amount, row.currency || activeBatch?.currency) }}</template></el-table-column>
  <el-table-column label="Paid / received" align="right" min-width="110"><template #default="{row}">{{ formatMoney(row.cashPaid??row.paid, row.currency) }}<small v-if="row.nonCashPaid">Manually offset: {{ formatMoney(row.nonCashPaid, row.currency) }}</small></template></el-table-column>
  <el-table-column label="Outstanding" align="right" min-width="140"><template #default="{row}"><strong>{{ row.currency }} {{ formatMoney(row.outstanding, row.currency) }}</strong></template></el-table-column>
  <el-table-column label="Due date" min-width="210"><template #default="{row}">
   <template v-if="row.schedules.length"><div v-for="item in row.schedules" :key="item.key" class="entry-dates"><small v-if="row.schedules.length>1">{{ item.installmentLabel }}</small>
    <el-button v-if="can('cases.write')&&item.termsDays==null&&!row.reversed&&!row.isReversalEntry" text type="primary" @click="fillTerms(row,item)">Complete missing days</el-button><template v-if="item.swissFacility && !item.swissCgl"><div>Original Swiss: {{ item.originalDueDate||'—' }}</div><div>{{ item.projectedDueDate?'Projected':'Settlement' }}: {{ item.dueDate||'—' }}</div><small v-if="item.confirmationCutoff">Cutoff: {{ item.confirmationCutoff }}</small></template>
    <template v-else><div>Accounting: {{ item.dueDate||'—' }}</div><small v-if="item.contractDueDate">Contract: {{ item.contractDueDate }}</small></template>
    <small v-if="item.status==='reminder'">{{ ['swiss_cedant_80_90','allianz_month_end_90','great_american_quarter_end_90','qbe_underwriting_quarter_end_90'].includes(item.paymentRule)?(item.paymentRule==='swiss_cedant_80_90'?'80-day reminder':'10 days before due'):'Upcoming due' }}</small><small v-if="item.status==='overdue'" class="cash-overdue">Overdue</small><small v-if="item.statementNeedsRevision" class="cash-overdue">Statement moved from {{ item.statementDueDate }}. Revise manually.</small>
   </div></template>
   <template v-else>{{ row.dueDate||'—' }}<small v-if="row.dueTime"> · {{ row.dueTime }} TW</small><small v-if="row.contractDueDate">{{ row.source==='claim'?'Claim due':row.partyType==='cedant'?'Cedant Due Date':row.swissFacility?(row.swissCgl?'Swiss due':'Swiss settlement'):row.allianzFacility?'Allianz due':row.qbeFacility?'QBE due':row.greatAmericanFacility?'Great American due':'Contract due' }}: {{ row.contractDueDate }}</small><small v-if="row.originalDueDate">Original Swiss: {{ row.originalDueDate }}</small><small v-if="row.projectedDueDate">Projected: {{ row.projectedDueDate }}</small><small v-if="row.paymentStatus==='reminder'">{{ row.paymentRule==='claim_created_15'?'Claim due-date reminder':['swiss_cedant_80_90','allianz_month_end_90','great_american_quarter_end_90','qbe_underwriting_quarter_end_90'].includes(row.paymentRule)?(row.paymentRule==='swiss_cedant_80_90'?'80-day reminder':'10 days before due'):'Upcoming due' }}</small><small v-if="row.paymentStatus==='overdue'" class="cash-overdue">Overdue</small><small v-if="row.statementNeedsRevision" class="cash-overdue">Revise statement period</small></template>
   <small v-if="row.qbeFacility&&row.schedules?.some(s=>s.underwritingQuarter)">QBE underwriting year {{ row.schedules.find(s=>s.underwritingQuarter)?.underwritingYear }} · Q{{ row.schedules.find(s=>s.underwritingQuarter)?.underwritingQuarter }}</small>
   <template v-if="row.source==='claim'"><small>Claim created: {{ row.baseDate||'Pending confirmation' }}</small><small v-if="row.nextTrackingDate">Next reminder: {{ row.nextTrackingDate }}</small><small v-if="row.trackingDue" class="cash-overdue">Claim reminder due today</small><small v-for="(item,index) in row.trackingHistory||[]" :key="index">{{ item.recordedAt?.slice(0,10) }} · {{ item.recordedByName }} · {{ item.note }}</small><el-button v-if="(row.allianzClaim||row.greatAmericanClaim||row.qbeClaim)&&canEdit&&(Math.abs(row.outstanding)>.004)&&!row.reversed&&!row.isReversalEntry" text type="primary" @click="recordAllianzFollowup(row)">Record claim follow-up</el-button></template>
  </template></el-table-column>
  <el-table-column label="Settlement / collection" min-width="200"><template #default="{row}"><el-tag :type="row.settlement==='settled'?'success':row.settlement==='partial'?'warning':'info'">{{ statusLabel(row) }}</el-tag>
   <template v-for="item in row.schedules" :key="item.key"><div v-if="item.requiresCollectionConfirmation"><small v-if="row.schedules.length>1">{{ item.installmentLabel }}</small><el-tag :type="item.collectionConfirmed?'success':'warning'">{{ item.collectionConfirmed?'Confirmed collected':'Confirmation needed' }}</el-tag><small v-if="item.collectionConfirmedAt">{{ item.collectionConfirmedAt }} · {{ item.collectionConfirmationSource }}</small><small v-if="item.latestReceiptDate">Latest receipt: {{ item.latestReceiptDate }}</small></div></template>
   <small v-if="row.receiptStatus">{{ ({received:"Reported received",paid:"Reported paid",partial:row.paymentDirection==='receivable'?"Partially received":"Partially paid",unpaid:"Not yet received / paid"})[row.receiptStatus] }}</small><small v-if="row.settlementFinalized">Final T3 lock</small><small v-if="row.paymentAllowed===false">{{ row.paymentBlockedReason }}</small>
  </template></el-table-column>
  <el-table-column label="Action" min-width="220"><template #default="{row}">
   <el-button v-if="canEdit&&row.canRecord" :disabled="row.paymentAllowed===false||row.statementNeedsRevision" text type="primary" @click="openPayment([row])">Record payment</el-button>
   <small v-if="(row.greatAmericanFacility||row.qbeFacility)&&row.amount>0&&row.manualSettlementConfirmed">Actual receipt / bank returns: track externally; original payment remains complete.</small><el-button v-if="canEdit&&!row.scheduleOnly&&row.manualSettlementRequired&&!row.reversed&&!row.isReversalEntry&&!row.manualSettlementConfirmed" text type="primary" :disabled="!row.canConfirmSettlement||saving" @click="confirmSettlement(row)">Confirm settlement</el-button>
   <el-button v-if="canEdit&&row.canCancelSettlement&&!row.reversed&&!row.isReversalEntry" text @click="confirmSettlement(row,true)">Cancel settlement</el-button>
   <el-dropdown v-if="canEdit&&hasEntryActions(row)" trigger="click" @command="command=>entryActions.open(command.item,command.kind)"><el-button text>More</el-button><template #dropdown><el-dropdown-menu><template v-for="item in row.schedules" :key="item.key">
    <el-dropdown-item v-if="offsetAllowed(item)" :command="{item,kind:'offset'}">Offset with original{{ row.schedules.length>1?' · '+item.installmentLabel:'' }}</el-dropdown-item>
    <el-dropdown-item v-if="statementAllowed(item)" :command="{item,kind:'statement'}">Statement reference{{ row.schedules.length>1?' · '+item.installmentLabel:'' }}</el-dropdown-item>
   </template></el-dropdown-menu></template></el-dropdown>
   <el-button v-if="row.entries?.length||row.cashTracking==='derived'||row.settlementHistory?.length" text @click="historyRow=row">{{ row.cashTracking==='derived'?'Settlement history':'History' }}</el-button>
  </template></el-table-column>
 </el-table>
 <div v-if="filtered.length>50" class="table-pagination"><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[50,100,200,500]" :total="filtered.length" layout="total, sizes, prev, pager, next" background data-testid="accounting-pagination" /></div>
</section>
<AccountingEntryActions ref="entryActions" :rows="swissRows" :can-edit="canEdit" @refresh="load" />
<ReconciliationReferences ref="referenceEditor" @saved="load" @refresh="load" />
<el-dialog v-model="paymentVisible" title="Record receipt / payment" width="min(900px, 94vw)" :close-on-click-modal="false">
 <p v-if="payment.allocations.length">{{ payment.allocations[0].row.currency }} · {{ paymentDirection(payment.allocations[0].row) }} · {{ transactionParty(payment.allocations[0].row) }}</p>
 <el-form label-position="top"><div class="form-grid cols-2">
 <el-form-item label="Payment date" required><el-date-picker v-model="payment.date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
 <el-form-item label="Recorded receipt / payment amount" required><el-input-number v-sync-input-number-aria v-model="payment.amount" :disabled="payment.allocations.length>0&&payment.allocations.every(a=>a.row.fullPaymentRequired)" :min="0.01" :precision="payment.allocations.length && payment.allocations.every(a=>a.row.currency==='TWD' && a.row.source==='premium' && Number.isInteger(a.row.outstanding)) ? 0 : 2" :controls="false" :formatter="formatMoneyInput" :parser="parseMoneyInput" @change="value=>{if(payment.allocations.length===1)payment.allocations[0].amount=value}" /></el-form-item>
 <el-form-item label="External system reference"><small>Enter a reference or note; at least one is required.</small><el-input v-model="payment.reference" maxlength="200" /><small>The same reference may be entered on separate case / installment records.</small></el-form-item><el-form-item label="Note"><el-input v-model="payment.note" maxlength="1000" /></el-form-item>
 </div></el-form>
 <el-table :data="payment.allocations"><el-table-column label="Transaction" min-width="260"><template #default="{row}">{{ rowTitle(row.row) }}<br><small>{{ displayTwRef(row.row) }}</small></template></el-table-column><el-table-column label="Outstanding" align="right"><template #default="{row}">{{ formatMoney(Math.abs(row.row.outstanding), row.row.currency) }}</template></el-table-column><el-table-column label="Allocated amount" width="210"><template #default="{row}"><el-input-number v-sync-input-number-aria v-model="row.amount" :disabled="payment.allocations.length===1||row.row.fullPaymentRequired" :min="0.01" :max="Math.abs(row.row.outstanding)" :precision="row.row.currency==='TWD' && row.row.source==='premium' && Number.isInteger(row.row.outstanding) ? 0 : 2" :controls="false" :formatter="formatMoneyInput" :parser="parseMoneyInput" /></template></el-table-column></el-table>
 <el-alert :type="difference===0?'success':'warning'" :closable="false" style="margin-top:16px" :title="'Allocated: '+formatMoney(allocated, payment.allocations[0]?.row.currency)+' · Difference: '+formatMoney(difference, payment.allocations[0]?.row.currency)" />
 <p>Accounting manually records the receipt/payment date, amount and reference. Balances and due-date tracking use the saved records.</p>
 <p v-if="payment.allocations.some(a=>isGreatAmericanRecord(a.row))">Great American: register one case / installment or claim request at a time. Each record retains its own deadline, balance and manual confirmation.</p>
 <p v-if="payment.allocations.some(a=>isQbeRecord(a.row))">QBE: register one case / installment or claim request at a time. Each transaction retains its own balance and manual confirmation.</p>
 <p>Premiums must be recorded for their full remaining balance. Claims may be recorded in parts; cumulative claim payments cannot exceed recorded receipts.</p>
 <p v-if="payment.allocations.some(a=>(a.row.greatAmericanCase||a.row.qbeCase)&&a.row.partyType==='cedant'&&a.row.amount<0)">Record the full Cedant refund for this endorsement together. All reinsurer refunds must first be recorded as received and individually confirmed.</p>
 <template #footer><el-button @click="paymentVisible=false">Cancel</el-button><el-button class="primary-button" :loading="saving" @click="savePayment">Record payment</el-button></template>
</el-dialog>
<el-dialog :model-value="!!historyRow" :title="historyRow?.cashTracking==='derived'?'Brokerage settlement':'Payment history'" width="min(850px,94vw)" @close="historyRow=null">
 <template v-if="historyRow"><p>{{ rowTitle(historyRow) }} · {{ transactionParty(historyRow) }}</p>
 <template v-if="historyRow.cashTracking==='derived'"><el-alert title="Brokerage requires Accounting to confirm settlement after the matching T1 and T2 are manually settled. This creates no bank remittance." :closable="false" type="info" /><p v-for="dependency in historyRow.settlementDependencies" :key="dependency.txNo">{{ transactionNumber(dependency.txNo) }} · {{ dependency.settlement }}</p></template>
 <el-table v-else :data="historyRow.entries||[]"><el-table-column prop="paymentDate" label="Date" /><el-table-column label="Type"><template #default="{row}">{{ row.entryType }}{{ row.entryKind?' · '+row.entryKind:'' }}</template></el-table-column><el-table-column label="Applied amount" align="right"><template #default="{row}">{{ formatMoney(row.appliedAmount, historyRow.currency) }}</template></el-table-column><el-table-column prop="settlementDueDate" label="Swiss period" /><el-table-column prop="reference" label="Reference" /><el-table-column prop="note" label="Note" /><el-table-column label="Action" width="160"><template #default="{row}"><el-button v-if="canEdit&&row.transactionNo&&row.entryType==='payment'&&!row.nonCash&&!historyRow.amountEditLocked&&!historyRow.reversed&&!historyRow.entries.some(e=>e.reversalOf===row.id)" text type="primary" @click="editPaymentRecord(historyRow,row)">Edit amount</el-button><el-button v-if="row.batchId&&row.entryType==='payment'" text @click="showBatch(row.batchId)">View registration</el-button><el-button v-else-if="canEdit&&!historyRow.amountEditLocked&&row.entryType==='payment'&&!row.offsetId&&!historyRow.reversed&&!historyRow.isReversalEntry&&!historyRow.entries.some(e=>e.reversalOf===row.id)" text type="danger" @click="reverseLegacy(historyRow,row)">Reverse original</el-button></template></el-table-column></el-table>
 <el-table v-if="historyRow.paymentEditHistory?.length" :data="historyRow.paymentEditHistory"><el-table-column prop="changedAt" label="Changed at" /><el-table-column label="Before"><template #default="{row}">{{ formatMoney(row.before.amount, historyRow.currency) }}</template></el-table-column><el-table-column label="After"><template #default="{row}">{{ formatMoney(row.after.amount, historyRow.currency) }}</template></el-table-column><el-table-column prop="reason" label="Reason" /><el-table-column prop="changedByName" label="Accountant" /></el-table>
 <el-table v-if="historyRow.settlementHistory?.length" :data="historyRow.settlementHistory"><el-table-column prop="confirmedAt" label="Confirmation time" /><el-table-column label="Action"><template #default="{row}">{{ row.confirmed?'Confirmed settlement':'Cancelled settlement' }}</template></el-table-column><el-table-column prop="confirmedByName" label="Accountant" /><el-table-column prop="note" label="Reference / reason" /></el-table>
 </template>
</el-dialog>
<el-dialog v-model="editVisible" :title="editMode==='terms'?'Complete missing contract days':'Edit recorded amount'" width="min(560px,94vw)" :close-on-click-modal="false">
 <el-form label-position="top"><el-form-item v-if="editMode==='terms'" label="Calendar days (minimum 15)" required><el-input-number v-sync-input-number-aria v-model="editForm.days" :min="15" :precision="0" :controls="false" /></el-form-item><el-form-item v-else label="Correct recorded amount" required><el-input-number v-sync-input-number-aria v-model="editForm.amount" :min="0.01" :precision="2" :controls="false" /></el-form-item><el-form-item label="Reason (required)" required><el-input v-model="editForm.reason" type="textarea" maxlength="1000" /></el-form-item></el-form>
 <p>The previous value, new value, reason and operator are retained. Previously settled amounts remain locked.</p><template #footer><el-button @click="editVisible=false">Cancel</el-button><el-button type="primary" :loading="saving" @click="saveEdit">Save with history</el-button></template>
</el-dialog>
<el-dialog v-model="batchVisible" title="Receipt / payment record details" width="min(900px,94vw)">
 <template v-if="activeBatch"><p>{{ activeBatch.paymentDate }} · {{ activeBatch.currency }} {{ formatMoney(activeBatch.amount, activeBatch.currency) }} · {{ activeBatch.partyName }} · {{ activeBatch.status }}</p><p>{{ activeBatch.reference }} · {{ activeBatch.note }}</p><el-table :data="activeBatch.allocations"><el-table-column prop="twRef" label="TW Ref" min-width="210" /><el-table-column label="Transaction" min-width="230"><template #default="{row}">{{ transactionNumber(row.txNo) }}</template></el-table-column><el-table-column label="Amount" align="right"><template #default="{row}">{{ formatMoney(row.amount, row.currency || activeBatch?.currency) }}</template></el-table-column></el-table></template>
 <template #footer><el-button @click="batchVisible=false">Close</el-button><el-button v-if="canEdit&&activeBatch?.canReverse" type="danger" :loading="saving" @click="reverseBatch">Reverse recorded amounts</el-button></template>
</el-dialog>
</div>
</template>
<style scoped>.cash-overdue{display:block;color:var(--el-color-danger)}small{display:block}.entry-dates+.entry-dates{margin-top:8px}.table-pagination{display:flex;justify-content:flex-end;margin-top:12px;overflow-x:auto}</style>
