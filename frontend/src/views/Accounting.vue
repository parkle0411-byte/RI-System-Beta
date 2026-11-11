<script setup>
import vAccountingScroll from '../directives/accountingScroll'
import { partyKey, isOverseaCash, isDerivedBrokerage, activeAccount, isCedantAccount, accountSource, visibleAccount, cashTotals, cashUuid } from './accountingCash'
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { apiFetch } from '../api'
import { can } from '../auth'
import { recall, remember } from './accountingMemory'
import { accountingRows } from '../alpha/accountingRows'
import { formatMoney, formatMoneyInput, parseMoneyInput, reportWriteError } from '../alpha/format'
import { displayTwRef } from '../alpha/manualTwRef'
import { transactionNumber } from '../alpha/transactionNumber'
import { transactionParty, paymentDirection } from '../alpha/transactionParty'
import vSyncInputNumberAria from '../directives/syncInputNumberAria'
import ReconciliationReferences from '../components/ReconciliationReferences.vue'
import AccountingEntryActions from '../components/AccountingEntryActions.vue'
const tableViewportHeight=ref(Math.max(240,Math.min(720,Math.round(window.innerHeight*.65))))
const wideScreen=ref(window.innerWidth>760), resize=()=>{wideScreen.value=window.innerWidth>760;tableViewportHeight.value=Math.max(240,Math.min(720,Math.round(window.innerHeight*.65)))};window.addEventListener('resize',resize);onUnmounted(()=>window.removeEventListener('resize',resize))
const router=useRouter(), tab=ref('all'), loading=ref(false), refreshing=ref(false), shownAt=ref(''), saving=ref(false), loadError=ref('')
const rows=ref([]), batches=ref([]), reviewBatches=ref([]), currencies=ref([]), warnings=ref([]), canEdit=ref(false), selected=ref([]), caseHistories=ref({})
const filters=reactive({reference:'',insured:'',cedant:'',reinsurer:'',currency:'',direction:'',settlement:[],source:'',origin:'',due:''})
const page=ref(1), pageSize=ref(100)
const entryActions=ref(null),referenceEditor=ref(null),historyRow=ref(null),activeBatch=ref(null),reviewVisible=ref(false),reviewTargets=ref([]),paymentVisible=ref(false),termsVisible=ref(false),termsTarget=ref(null)
const review=reactive({date:today(),reference:'',note:''}),payment=reactive({date:today(),reference:'',note:'',replacement:'',submissionId:'',allocations:[]}),terms=reactive({days:null,reason:''})
function today(){return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())}
const money=(v,c)=>formatMoney(v,c), cents=v=>Math.round(Number(v||0)*100), label=s=>({open:'Open',partial:'Open',settled:'Settled',pending_confirmation:'Open',not_tracked:'Not tracked'})[s]||s
const rowTitle=r=>r.scheduleOnly?'Historical schedule · '+r.installmentLabel:transactionNumber(r.txNo)
const statusLabel=r=>r.reversed?'Reversed':r.isReversalEntry?'Reversal entry':label(r.settlement)
const isBrokerage=computed(()=>tab.value==='brokerage')
const canSelect=computed(()=>canEdit.value&&['unreconciled','reconciled'].includes(tab.value))
const accountTitle=computed(()=>({all:'All Accounts',unreconciled:'Unreconciled Accounts',reconciled:'Reconciled Accounts',settled:'Settled/Closed',brokerage:'Brokerage'})[tab.value])
const group=partyKey
const compatible=r=>!selected.value.length||group(selected.value[0])===group(r)
const active=activeAccount
const selectable=r=>!r.legacyHistorical&&canSelect.value&&active(r)&&(tab.value==='unreconciled'?!r.financeReviewed:r.financeReviewed&&r.canRecord&&r.paymentAllowed!==false&&!r.statementNeedsRevision)
const eligible=r=>selectable(r)&&compatible(r)
const matches=(values,q)=>!q||values.some(v=>String(v||'').toLowerCase().includes(q.trim().toLowerCase()))
const isT3=r=>r.cashTracking==='derived'||String(r.legType||'').startsWith('Leg 3')
const soa=r=>r.reconciliationRef||'Missing'
const actualDue=r=>r.contractDueDate||r.schedules?.find(x=>x.contractDueDate)?.contractDueDate||r.dueDate||''
const normalizedSettlement=r=>r.settlement==='partial'?'open':r.settlement
const cedantOptions=computed(()=>[...new Set(rows.value.filter(r=>isCedantAccount(r)&&!isDerivedBrokerage(r)).map(row=>transactionParty(row)).filter(Boolean))].sort())
const reinsurerOptions=computed(()=>[...new Set(rows.value.filter(r=>!isCedantAccount(r)&&!isDerivedBrokerage(r)).map(row=>transactionParty(row)).filter(Boolean))].sort())
watch(()=>filters.cedant,value=>{if(value)filters.reinsurer=''})
watch(()=>filters.reinsurer,value=>{if(value)filters.cedant=''})
const filtered=computed(()=>rows.value.filter(r=>{
 if(!visibleAccount(r,tab.value))return false
 if(filters.settlement.length&&(r.reversed||r.isReversalEntry||!filters.settlement.includes(normalizedSettlement(r))))return false
 return matches([r.twRef,r.manualTwRef,displayTwRef(r)],filters.reference)&&matches([r.originalInsured,r.originalInsuredCn],filters.insured)&&(!filters.cedant||isCedantAccount(r)&&transactionParty(r)===filters.cedant)&&(!filters.reinsurer||!isCedantAccount(r)&&transactionParty(r)===filters.reinsurer)&&(!filters.currency||filters.currency===r.currency)&&(!filters.direction||r.paymentDirection===filters.direction)&&(!filters.source||accountSource(r)===filters.source)&&(!filters.origin||(r.origin||'native')===filters.origin)&&(!filters.due||!!actualDue(r)&&actualDue(r)<=filters.due)
}).sort((a,b)=>{
 if(isBrokerage.value)return Number(a.settlement==='settled')-Number(b.settlement==='settled')||displayTwRef(a).localeCompare(displayTwRef(b))
 const reminder=r=>r.dueDate||r.schedules?.find(x=>x.dueDate)?.dueDate||actualDue(r)||'9999-12-31'
 const overdue=r=>r.settlement!=='settled'&&actualDue(r)&&actualDue(r)<today()
 return Number(!!overdue(b))-Number(!!overdue(a))||(overdue(a)?actualDue(a):reminder(a)).localeCompare(overdue(b)?actualDue(b):reminder(b))||displayTwRef(a).localeCompare(displayTwRef(b))||rowTitle(a).localeCompare(rowTitle(b))
}))
const pagedRows=computed(()=>filtered.value.slice((page.value-1)*pageSize.value,page.value*pageSize.value))
const selectedGroup=computed(()=>selected.value.length?transactionParty(selected.value[0])+' · '+[...new Set(selected.value.map(r=>r.currency))].join(', '):'')
const selectionAvailable=computed(()=>filtered.value.some(eligible)&&(selected.value.length>0||new Set(filtered.value.filter(selectable).map(group)).size===1))
function selectAll(){
 const first=selected.value[0]||filtered.value.find(selectable)
 if(!first)return
 selected.value=filtered.value.filter(r=>selectable(r)&&group(r)===group(first))
}
watch(tab,()=>{selected.value=[];page.value=1;filters.settlement=['unreconciled','reconciled'].includes(tab.value)?['open']:tab.value==='settled'?['settled']:[]})
watch(filters,()=>{page.value=1;selected.value=[]},{deep:true});watch(pageSize,()=>page.value=1)
const pendingPayments=computed(()=>payment.allocations.filter(a=>a.status!=='recorded'))
const recordedPayments=computed(()=>payment.allocations.filter(a=>a.status==='recorded'))
const pendingTotals=computed(()=>cashTotals(payment.allocations,a=>a.status!=='recorded'))
const recordedTotals=computed(()=>cashTotals(payment.allocations,a=>a.status==='recorded'))
const reviewTotals=computed(()=>cashTotals(reviewTargets.value.map(row=>({row,cashAmount:Math.abs(row.amount)}))))
function refreshPaymentRows(){
 if(!paymentVisible.value)return
 const fresh=new Map(rows.value.map(row=>[row.caseUid+':'+row.txNo,row]))
 for(const allocation of payment.allocations){
  const row=fresh.get(allocation.row.caseUid+':'+allocation.row.txNo)
  if(!row)continue
  allocation.row=row
  const entries=(row.entries||[]).filter(e=>e.entryType==='payment'&&e.cashSubmissionId===payment.submissionId&&e.cashItemId===allocation.itemId)
  if(entries.length){
   const entry=entries[0]
   Object.assign(allocation,{status:'recorded',error:'',batchId:entry.batchId,savedDate:entry.paymentDate,savedReference:entry.reference,
    cashAmount:entries.reduce((sum,e)=>sum+cents(Math.abs(e.appliedAmount)),0)/100})
  }
 }
}
function toggle(row,value){if(value&&!eligible(row))return;selected.value=value?[...selected.value.filter(r=>r.key!==row.key),row]:selected.value.filter(r=>r.key!==row.key)}
function removeReview(row){reviewTargets.value=reviewTargets.value.filter(r=>r.key!==row.key);selected.value=selected.value.filter(r=>r.key!==row.key)}
function removeAllocation(row){if(row.status==='recorded'||saving.value)return;payment.allocations=payment.allocations.filter(a=>a.row.key!==row.row.key);selected.value=selected.value.filter(r=>r.key!==row.row.key)}
// 2026-11-10：載入失敗時顯示常駐錯誤＋Retry，不再只閃一下提示後顯示「0 筆」；伺服器錯誤頁（非 JSON）也轉成白話訊息。
function loadFailure(response,body){if(body&&(body.message||body.error))return body.message||body.error;return response?`The server could not finish loading Accounting (HTTP ${response.status}).`:'The connection to the server failed.'}
async function load(){loading.value=!refreshing.value;try{let response=null,b=null;try{response=await apiFetch('/api/accounting?view=list');b=await response.json().catch(()=>null)}catch{throw new Error(loadFailure(null,null))}if(!response.ok||!b)throw new Error(loadFailure(response,b));apply(b);remember(b);loadError.value='';shownAt.value=new Date().toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'})}catch(e){loadError.value=e.message||loadFailure(null,null);canEdit.value=false}finally{loading.value=false;refreshing.value=false}}
function apply(b){rows.value=accountingRows(b);batches.value=b.cashBatches||[];reviewBatches.value=b.reviewBatches||[];currencies.value=b.currencies||[];canEdit.value=!!b.scope?.canEdit;warnings.value=(b.warnings||[]).filter(w=>w.dataError);caseHistories.value=b.caseHistories||{};selected.value=[];if(historyRow.value)historyRow.value=rows.value.find(r=>r.caseUid===historyRow.value.caseUid&&r.txNo===historyRow.value.txNo)||null;if(activeBatch.value)activeBatch.value=batches.value.find(x=>x.batchId===activeBatch.value.batchId)||null;refreshPaymentRows()}
async function post(body){const r=await apiFetch('/api/accounting',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const b=await r.json();if(!r.ok){const e=new Error(b.message||b.error);e.status=r.status;throw e}return b}
async function write(body,done){saving.value=true;try{const result=await post(body);done?.(result);ElMessage.success('Accounting updated');await load()}catch(e){reportWriteError(e,()=>load());await load()}finally{saving.value=false}}
function members(targets){return targets.map(r=>({caseUid:r.caseUid,txNo:r.txNo,rowVersion:r.caseRowVersion}))}
function openReview(targets){reviewTargets.value=[...targets];Object.assign(review,{date:today(),reference:'',note:''});reviewVisible.value=true}
async function saveReview(){if(!review.date||!reviewTargets.value.length)return ElMessage.warning('Enter a review date and select at least one account.');await write({action:'review_accounts',date:review.date,reference:review.reference,note:review.note,members:members(reviewTargets.value)},()=>reviewVisible.value=false)}
async function cancelReview(row){const batch=reviewBatches.value.find(b=>b.id===row.reviewBatchId);if(!batch)return;let reason;try{const x=await ElMessageBox.prompt('Cancel all '+batch.members.length+' accounts in this Finance review batch. Active receipt/payment and offset registrations must be reversed first.','Cancel entire review batch',{inputValidator:v=>!!v?.trim()||'A reason is required.'});reason=x.value}catch{return};await write({action:'cancel_review_batch',reviewBatchId:batch.id,members:batch.members.map(({caseUid,txNo,rowVersion})=>({caseUid,txNo,rowVersion})),reason})}
function openPayment(targets,replacement=''){
 if(!targets.length)return
 Object.assign(payment,{date:today(),reference:'',note:'',replacement,submissionId:cashUuid(),
  allocations:targets.map(row=>({row,itemId:cashUuid(),cashAmount:Math.abs(row.outstanding),status:'pending',error:'',batchId:'',savedDate:'',savedReference:''}))})
 paymentVisible.value=true
}
async function savePayment(){
 if(saving.value||!pendingPayments.value.length)return
 if(!payment.date||(!payment.reference.trim()&&!payment.note.trim()))return ElMessage.warning('Enter a date and an Accounting Dept. Ref. or note.')
 const targets=[...pendingPayments.value]
 saving.value=true
 try{
  const result=await post({action:'record_transaction_payments',cashSubmissionId:payment.submissionId,paymentDate:payment.date,
   reference:payment.reference,note:payment.note,replacementOfBatchId:payment.replacement,
   allocations:targets.map(a=>({...members([a.row])[0],cashItemId:a.itemId,cashAmount:a.cashAmount}))})
  if(!Array.isArray(result.results))throw new Error('The registration result could not be confirmed. Refresh and retry pending accounts.')
  const byId=new Map(result.results.map(item=>[item.cashItemId,item]))
  for(const allocation of targets){
   const item=byId.get(allocation.itemId)
   if(item?.status==='recorded')Object.assign(allocation,{status:'recorded',error:'',batchId:item.batchId,savedDate:item.paymentDate,savedReference:item.reference,cashAmount:item.cashAmount})
   else Object.assign(allocation,{status:'failed',error:item?.message||'This account could not be recorded.'})
  }
  if(result.failed)ElMessage.warning(result.succeeded+' accounts recorded; '+result.failed+' failed. Correct and retry failed accounts only.')
  else ElMessage.success(result.succeeded+' accounts recorded.')
  await load()
 }catch(error){
  for(const allocation of targets)if(allocation.status!=='recorded')Object.assign(allocation,{status:'failed',error:'Result unconfirmed. Refresh or retry to check the saved registration.'})
  ElMessage.error(error.message)
  await load()
 }finally{saving.value=false}
}
function showBatch(id){activeBatch.value=batches.value.find(b=>b.batchId===id)||null}
async function reverseBatch(){const b=activeBatch.value;if(!b?.canReverse||!canEdit.value)return;let reason;try{const r=await ElMessageBox.prompt('Reverse every cash and offset allocation in this registration. Downstream payment prerequisites must remain valid.','Reverse entire registration',{inputValidator:v=>!!v?.trim()||'A reason is required.'});reason=r.value}catch{return};const versions=[...new Map(b.allocations.map(a=>[a.caseUid,{caseUid:a.caseUid,rowVersion:a.caseRowVersion}])).values()];await write({action:'reverse_batch_payment',batchId:b.batchId,cases:versions,paymentDate:today(),note:reason})}
function replaceBatch(){const b=activeBatch.value;const keys=new Set(b.allocations.map(a=>a.caseUid+':'+a.txNo));const targets=rows.value.filter(r=>keys.has(r.caseUid+':'+r.txNo));if(!targets.length||targets.some(r=>!r.financeReviewed||!r.canRecord))return ElMessage.warning('Review the current accounts and their balances before re-registering.');activeBatch.value=null;openPayment(targets,b.batchId)}
async function recordFollowup(row){let note;try{note=(await ElMessageBox.prompt('Enter the claim follow-up record.','Claim follow-up',{inputValidator:v=>!!v?.trim()||'A follow-up record is required.'})).value}catch{return};await write({action:'record_claim_followup',caseUid:row.caseUid,rowVersion:row.caseRowVersion,txNo:row.txNo,note})}
function openCase(row){router.push(row.origin==='legacy'?{path:'/legacy',query:{id:row.legacyTransactionId}}:{path:'/cases',query:{case:row.caseUid,tab:'soa'}})}
function fillTerms(row,item){termsTarget.value={row,item};Object.assign(terms,{days:null,reason:''});termsVisible.value=true}
async function saveTerms(){const t=termsTarget.value;if(!t||!terms.reason.trim())return;await write({action:'complete_payment_terms',caseUid:t.row.caseUid,rowVersion:t.row.caseRowVersion,installmentId:t.item.installmentId,partyKey:t.item.partyKey,days:terms.days,reason:terms.reason},()=>termsVisible.value=false)}
const statementAllowed=item=>item.swissFacility&&item.collectionConfirmed&&item.amount>0&&item.outstanding>.004
const swissRows=computed(()=>rows.value.flatMap(r=>r.schedules||[]))
const accountReviews=computed(()=>historyRow.value?reviewBatches.value.flatMap(b=>b.members.filter(m=>m.caseUid===historyRow.value.caseUid&&m.txNo===historyRow.value.txNo).map(m=>({...b,date:m.reviewDate||b.date,reference:m.reviewReference??b.reference,note:m.reviewNote??b.note,createdByName:m.reviewedByName||b.createdByName}))):[])
onMounted(()=>{const saved=recall();if(saved){apply(saved.body);canEdit.value=false;refreshing.value=true;shownAt.value=saved.at.toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'})}load()})
</script>
<template>
<div class="overview-stack">
 <el-alert data-testid="accounting-refreshing" v-if="refreshing" type="info" :closable="false" :title="'Showing the list loaded at '+shownAt+'. Updating… Operations are available after the update.'" />
 <el-alert data-testid="accounting-load-error" v-if="loadError&&!loading" type="error" :closable="false" show-icon title="Accounting data could not be loaded"><p>{{ loadError }} {{ rows.length ? 'Showing the list loaded at '+(shownAt||'an earlier time')+'. Receipt, payment and review operations are disabled until Accounting reloads.' : 'Please retry. If it keeps failing, contact the System Administrator.' }}</p><el-button data-testid="accounting-retry" size="small" type="danger" plain :loading="loading" @click="load">Retry</el-button></el-alert>
 <el-alert v-if="warnings.length" type="error" :closable="false" title="Some cases could not be read and are not shown" :description="warnings.map(w=>w.twRef||w.caseUid).join(', ')+'. Contact the System Administrator.'" />
 <section class="table-card">
  <div class="section-heading"><div><h2>Accounting</h2><p>Finance reviews each account before recording receipts or payments. All cash accounts allow partial receipts and payments.</p></div><el-button :loading="loading" @click="load">Refresh</el-button></div>
  <el-tabs v-model="tab" class="accounting-tabs" data-testid="accounting-tabs">
   <el-tab-pane label="All Accounts" name="all"/><el-tab-pane label="Unreconciled Accounts" name="unreconciled"/><el-tab-pane label="Reconciled Accounts" name="reconciled"/><el-tab-pane label="Settled/Closed" name="settled"/><el-tab-pane label="Brokerage" name="brokerage"/>
  </el-tabs>
  <div class="form-grid cols-3 accounting-filters">
   <el-form-item label="TW Ref"><el-input v-model="filters.reference" clearable/></el-form-item>
   <el-form-item label="Original Insured (EN / CN)"><el-input v-model="filters.insured" clearable/></el-form-item>
   <el-form-item label="Cedant"><el-select v-model="filters.cedant" filterable clearable placeholder="All"><el-option v-for="name in cedantOptions" :key="name" :label="name" :value="name"/></el-select></el-form-item>
   <el-form-item label="Reinsurer / R/I Broker"><el-select v-model="filters.reinsurer" filterable clearable placeholder="All"><el-option v-for="name in reinsurerOptions" :key="name" :label="name" :value="name"/></el-select></el-form-item>
   <el-form-item label="Currency"><el-select v-model="filters.currency" clearable placeholder="All"><el-option v-for="c in currencies" :key="c" :label="c" :value="c"/></el-select></el-form-item>
   <el-form-item v-if="!isBrokerage" label="Direction"><el-select v-model="filters.direction" clearable placeholder="All"><el-option label="Payable" value="payable"/><el-option label="Receivable" value="receivable"/></el-select></el-form-item>
   <el-form-item label="Settlement"><el-select v-model="filters.settlement" :disabled="tab==='settled'" multiple clearable placeholder="All"><el-option v-for="s in ['open','settled']" :key="s" :label="label(s)" :value="s"/></el-select></el-form-item>
   <el-form-item label="Origin"><el-select v-model="filters.origin" clearable placeholder="All"><el-option label="Native" value="native"/><el-option label="Legacy" value="legacy"/></el-select></el-form-item>
   <el-form-item v-if="!isBrokerage" label="Type"><el-select v-model="filters.source" clearable placeholder="All"><el-option label="Premium" value="premium"/><el-option label="Claim" value="claim"/><el-option label="Oversea commission" value="brokerage"/></el-select></el-form-item>
   <el-form-item label="Due date"><el-date-picker v-model="filters.due" type="date" value-format="YYYY-MM-DD" placeholder="Due on or before" clearable/></el-form-item>
  </div>
 </section>
 <section class="table-card" v-loading="loading">
  <div class="section-heading"><div><h2>{{ accountTitle }} ({{ filtered.length }})</h2><p>{{ isBrokerage?'Retained brokerage settles after premium receipts and payments complete. Oversea cash accounts appear here once fully settled.':tab==='all'?'All premium, claim and Oversea cash accounts, including open and fully settled accounts.':tab==='settled'?'Fully settled T1 and T2 accounts. Open an account history to inspect its registrations.':tab==='unreconciled'?'Finance checks the account; counterparty confirmation is not required.':'Accounts for the same counterparty share one review batch across currencies. Receipts and payments are recorded separately.' }}</p></div>
   <div v-if="canSelect" class="selection-actions"><el-button :disabled="!selectionAvailable" @click="selectAll">Select all</el-button><el-button :disabled="!selected.length" @click="selected=[]">Deselect all</el-button><el-button class="primary-button" :disabled="!selected.length" @click="tab==='unreconciled'?openReview(selected):openPayment(selected)">{{ tab==='unreconciled'?'Mark reviewed':'Record selected' }} ({{ selected.length }})</el-button></div>
  </div>
  <p v-if="canSelect" class="selection-hint">Select all includes matching selectable accounts across currencies and pages{{selectedGroup?' · '+selectedGroup:''}}. When several counterparties match, select one account first or narrow the filters.</p>
  <el-table v-accounting-scroll :max-height="tableViewportHeight" scrollbar-always-on :data="pagedRows" row-key="key" data-testid="accounting-table" :empty-text="loadError?'Accounting data could not be loaded. Use Retry above.':'No matching accounts. Premium accounts are created at Announce.'">
   <el-table-column v-if="canSelect" width="44" fixed="left"><template #default="{row}"><el-checkbox v-if="active(row)" :model-value="selected.some(r=>r.key===row.key)" :disabled="!eligible(row)" :aria-label="'Select '+rowTitle(row)" @change="v=>toggle(row,v)"/></template></el-table-column>
   <el-table-column label="Transaction / SoA / TW Ref" :width="wideScreen?260:180" fixed="left"><template #default="{row}"><el-button v-if="can('cases.read.all')" text class="table-action" @click="openCase(row)">{{ rowTitle(row) }}</el-button><strong v-else>{{rowTitle(row)}}</strong><small v-if="!isT3(row)">SoA: {{soa(row)}}</small><small>{{displayTwRef(row)}} · {{row.accountDisplayDate||'—'}}</small><small v-if="row.legacyInstallmentNo">Installment No. {{row.legacyInstallmentNo}}</small><small v-if="row.financePreviousTxNo">Replaces {{transactionNumber(row.financePreviousTxNo)}}</small><small v-if="row.financeReversalOf">Reversal of {{transactionNumber(row.financeReversalOf)}}</small><small v-if="row.financeReplacementTxNo">Replaced by {{transactionNumber(row.financeReplacementTxNo)}}</small><small v-if="row.reversed||row.isReversalEntry">{{statusLabel(row)}}</small></template></el-table-column>
   <el-table-column label="Origin" width="85"><template #default="{row}">{{row.origin==='legacy'?'Legacy':'Native'}}</template></el-table-column>
   <el-table-column label="Original Insured (EN / CN)" min-width="240"><template #default="{row}"><div>{{row.originalInsured||'—'}}</div><div>{{row.originalInsuredCn||'—'}}</div></template></el-table-column>


   <el-table-column label="Party / Direction" min-width="210"><template #default="{row}">{{transactionParty(row)}}<small>{{paymentDirection(row)}}</small><small>{{isOverseaCash(row)?'Oversea commission':row.source==='claim'?'Claim':row.returnPremium?'Return premium':'Premium'}}</small></template></el-table-column>
   <el-table-column label="Amount" align="right" min-width="145"><template #default="{row}">{{row.currency}} {{money(row.amount,row.currency)}}</template></el-table-column>
   <el-table-column label="Receipt / Payment Amount" align="right" min-width="160"><template #default="{row}"><span v-if="row.legacyHistorical">{{row.currency}} {{money(row.paid,row.currency)}}<small>Historically settled</small></span><span v-else>{{row.currency}} {{money(row.cashPaid??row.paid,row.currency)}}</span><small v-if="row.nonCashPaid">Historical offset: {{row.currency}} {{money(row.nonCashPaid,row.currency)}}</small></template></el-table-column>
   <el-table-column label="Outstanding" align="right" min-width="145"><template #default="{row}"><strong>{{row.currency}} {{money(row.outstanding,row.currency)}}</strong></template></el-table-column>
  <el-table-column label="Due date" min-width="210"><template #default="{row}">
   <template v-if="row.schedules.length"><div v-for="item in row.schedules" :key="item.key" class="entry-dates"><small v-if="row.schedules.length>1">{{ item.installmentLabel }}</small>
    <el-button v-if="!row.legacyHistorical&&can('cases.write')&&row.historicalTermsMissing&&item.termsDays==null&&!row.reversed&&!row.isReversalEntry" text type="primary" @click="fillTerms(row,item)">Complete missing days</el-button><template v-if="item.swissFacility && !item.swissCgl"><div>Original Swiss: {{ item.originalDueDate||'—' }}</div><div>{{ item.projectedDueDate?'Projected':'Settlement' }}: {{ item.dueDate||'—' }}</div><small v-if="item.confirmationCutoff">Cutoff: {{ item.confirmationCutoff }}</small></template>
    <template v-else><div>Accounting: {{ item.dueDate||'—' }}</div><small v-if="item.contractDueDate">Contract: {{ item.contractDueDate }}</small></template>
    <small v-if="item.status==='reminder'">{{ ['swiss_cedant_80_90','allianz_month_end_90','great_american_quarter_end_90','qbe_underwriting_quarter_end_90'].includes(item.paymentRule)?(item.paymentRule==='allianz_month_end_90'?'Third following month-end minus 10 days':item.paymentRule==='swiss_cedant_80_90'?'80-day reminder':'10 days before due'):'Upcoming due' }}</small><small v-if="item.status==='overdue'" class="cash-overdue">Overdue</small><small v-if="item.statementNeedsRevision" class="cash-overdue">Statement moved from {{ item.statementDueDate }}. Revise manually.</small>
   </div></template>
   <template v-else-if="row.overseaBusiness"><div>Accounting Date: {{ row.accountingDate || '—' }}</div><small>Actual receipt / payment: {{ row.actualPaymentDate || '—' }}</small></template>
   <template v-else>{{ row.dueDate||'—' }}<small v-if="row.dueTime"> · {{ row.dueTime }} TW</small><small v-if="row.contractDueDate">{{ row.source==='claim'?'Claim due':row.partyType==='cedant'?'Cedant Due Date':row.swissFacility?(row.swissCgl?'Swiss due':'Swiss settlement'):row.allianzFacility?'Allianz due':row.qbeFacility?'QBE due':row.greatAmericanFacility?'Great American due':'Contract due' }}: {{ row.contractDueDate }}</small><small v-if="row.originalDueDate">Original Swiss: {{ row.originalDueDate }}</small><small v-if="row.projectedDueDate">Projected: {{ row.projectedDueDate }}</small><small v-if="row.paymentStatus==='reminder'">{{ row.paymentRule==='claim_created_15'?'Claim due-date reminder':['swiss_cedant_80_90','allianz_month_end_90','great_american_quarter_end_90','qbe_underwriting_quarter_end_90'].includes(row.paymentRule)?(row.paymentRule==='allianz_month_end_90'?'Third following month-end minus 10 days':row.paymentRule==='swiss_cedant_80_90'?'80-day reminder':'10 days before due'):'Upcoming due' }}</small><small v-if="row.paymentStatus==='overdue'" class="cash-overdue">Overdue</small><small v-if="row.statementNeedsRevision" class="cash-overdue">Revise statement period</small></template>
   <template v-if="row.source==='claim'"><small>Claim created: {{ row.baseDate||'Pending confirmation' }}</small><small v-if="row.nextTrackingDate">Next reminder: {{ row.nextTrackingDate }}</small><small v-if="row.trackingDue" class="cash-overdue">Claim reminder due today</small><small v-for="(item,index) in row.trackingHistory||[]" :key="index">{{ item.recordedAt?.slice(0,10) }} · {{ item.recordedByName }} · {{ item.note }}</small><el-button v-if="canEdit&&(Math.abs(row.outstanding)>.004)&&!row.reversed&&!row.isReversalEntry" text type="primary" @click="recordFollowup(row)">Record claim follow-up</el-button></template>
  </template></el-table-column>
   <el-table-column label="Settlement" min-width="200"><template #default="{row}"><el-tag :type="row.settlement==='settled'?'success':'info'">{{statusLabel(row)}}</el-tag><small v-if="row.paymentAllowed===false">{{row.paymentBlockedReason}}</small></template></el-table-column>
   <el-table-column v-if="!isBrokerage" label="Finance review" min-width="210"><template #default="{row}"><el-tag :type="row.financeReviewed?'success':'info'">{{row.legacyHistorical?'Historically Reconciled':row.financeReviewed?'Reviewed':'Not reviewed'}}</el-tag><small v-if="row.financeReviewed&&!row.legacyHistorical">{{row.reviewDate}} · {{row.reviewedByName}}</small><small>{{row.reviewReference}}</small><small>{{row.reviewNote}}</small><small v-if="row.financeReviewed&&!row.legacyHistorical">Batch: {{reviewBatches.find(b=>b.id===row.reviewBatchId)?.members.length||1}} accounts · {{(row.reviewCurrencies||[row.currency]).join(', ')}}</small></template></el-table-column>
   <el-table-column label="Action" min-width="245"><template #default="{row}">
    <el-tag v-if="row.legacyHistorical" type="info">Read-only</el-tag>
    <el-button v-if="row.origin!=='legacy'&&can('cases.write')&&['posted','closed'].includes(row.caseStatus)" text type="primary" @click="referenceEditor.open(row.caseUid)">Edit references</el-button>
    <el-button v-if="canEdit&&active(row)&&(!isBrokerage||row.overseaBusiness)&&!row.financeReviewed" text type="primary" @click="openReview([row])">Mark reviewed</el-button>
    <el-button v-if="canEdit&&row.financeReviewed&&row.canRecord" :disabled="row.paymentAllowed===false||row.statementNeedsRevision" text type="primary" @click="openPayment([row])">Record receipt / payment</el-button>
    <el-button v-if="!row.legacyHistorical&&canEdit&&row.financeReviewed" text @click="cancelReview(row)">Cancel review batch</el-button>
    <template v-for="item in row.schedules" :key="item.key"><el-button v-if="canEdit&&statementAllowed(item)" text type="primary" @click="entryActions.open(item,'statement')">Swiss statement reference</el-button></template>
    <el-button text @click="historyRow=row">{{isBrokerage?'Brokerage settlement details':'History'}}</el-button>
   </template></el-table-column>
  </el-table>
  <div v-if="filtered.length>50" class="table-pagination"><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[50,100,200,500]" :total="filtered.length" layout="total, sizes, prev, pager, next" background/></div>
 </section>
 <ReconciliationReferences ref="referenceEditor" @saved="load" @refresh="load"/>
 <AccountingEntryActions ref="entryActions" :rows="swissRows" :can-edit="canEdit" @refresh="load"/>
 <el-dialog class="accounting-modal" v-model="reviewVisible" title="Finance account review" width="min(850px,94vw)" :close-on-click-modal="false">
  <p>Finance has checked these accounts. Counterparty confirmation and receipt/payment are not required.</p>
  <el-form label-position="top"><div class="form-grid cols-2"><el-form-item label="Review date" required><el-date-picker v-model="review.date" type="date" value-format="YYYY-MM-DD"/></el-form-item><el-form-item label="Review reference"><el-input v-model="review.reference" maxlength="200"/></el-form-item></div><el-form-item label="Explanation"><el-input v-model="review.note" type="textarea" maxlength="1000"/></el-form-item></el-form><p>Review reference and explanation are optional.</p>
  <el-table :data="reviewTargets" max-height="420" data-testid="review-accounts"><el-table-column label="Account" min-width="260"><template #default="{row}">{{rowTitle(row)}}<small v-if="!isT3(row)">SoA: {{soa(row)}}</small><small>{{displayTwRef(row)}} · {{row.accountDisplayDate||'—'}}</small></template></el-table-column><el-table-column prop="originalInsured" label="Insured (EN)" min-width="180"/><el-table-column prop="originalInsuredCn" label="Insured (CN)" min-width="180"/><el-table-column label="Amount" align="right"><template #default="{row}">{{row.currency}} {{money(row.amount,row.currency)}}</template></el-table-column><el-table-column label="Action" width="100" fixed="right"><template #default="{row}"><el-button text type="danger" @click="removeReview(row)">Remove</el-button></template></el-table-column></el-table>
  <el-table :data="reviewTotals" data-testid="review-currency-totals"><el-table-column prop="currency" label="Currency"/><el-table-column label="Receivable amount" align="right"><template #default="{row}">{{row.currency}} {{money(row.receivable,row.currency)}}</template></el-table-column><el-table-column label="Payable amount" align="right"><template #default="{row}">{{row.currency}} {{money(row.payable,row.currency)}}</template></el-table-column></el-table>
  <template #footer><el-button @click="reviewVisible=false">Cancel</el-button><el-button type="primary" :loading="saving" :disabled="!reviewTargets.length" @click="saveReview">Mark reviewed</el-button></template>
 </el-dialog>
 <el-dialog class="accounting-modal" v-model="paymentVisible" title="Record receipts / payments" width="min(1150px,96vw)" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving">
  <p v-if="payment.allocations.length">{{transactionParty(payment.allocations[0].row)}}</p>
  <p>Adjust each Cash Amount. Receipts and payments are registered separately for each currency. Failed accounts stay here for correction; completed accounts are not submitted again.</p>
  <el-form label-position="top"><div class="form-grid cols-3">
   <el-form-item label="Receipt / payment date" required><el-date-picker v-model="payment.date" :disabled="saving" type="date" value-format="YYYY-MM-DD"/></el-form-item>
   <el-form-item label="Accounting Dept. Ref."><el-input v-model="payment.reference" :disabled="saving" maxlength="200"/></el-form-item>
   <el-form-item label="Note"><el-input v-model="payment.note" :disabled="saving" maxlength="1000"/></el-form-item>
  </div></el-form>
  <p>Enter an Accounting Dept. Ref. or note. The common details apply to all pending accounts; completed registrations retain their saved details.</p>
  <el-table class="compact-payment-table" :data="payment.allocations" max-height="420" data-testid="payment-accounts">
   <el-table-column label="Account" min-width="200"><template #default="{row}">{{rowTitle(row.row)}}<small v-if="!isT3(row.row)">SoA: {{soa(row.row)}}</small><small>{{displayTwRef(row.row)}} · {{row.row.accountDisplayDate||'—'}}</small></template></el-table-column>
   <el-table-column prop="row.originalInsured" label="Insured (EN)" min-width="120"/><el-table-column prop="row.originalInsuredCn" label="Insured (CN)" min-width="120"/>
   <el-table-column label="Direction" width="90"><template #default="{row}">{{paymentDirection(row.row)}}</template></el-table-column>
   <el-table-column label="Outstanding" class-name="payment-outstanding" width="130"><template #default="{row}">{{row.row.currency}} {{money(Math.abs(row.row.outstanding),row.row.currency)}}</template></el-table-column>
   <el-table-column label="Cash Amount" width="140"><template #default="{row}">
    <strong v-if="row.status==='recorded'">{{row.row.currency}} {{money(row.cashAmount,row.row.currency)}}</strong>
    <div v-else class="cash-input"><span>{{row.row.currency}}</span><el-input-number v-model="row.cashAmount" :disabled="saving" v-sync-input-number-aria :min="0" :precision="2" :controls="false" :formatter="value => row.row.currency === 'TWD' ? formatMoneyInput(value).replace(/\.00$/, '') : formatMoneyInput(value)" :parser="parseMoneyInput" :aria-label="'Cash Amount '+rowTitle(row.row)"/></div>
   </template></el-table-column>
   <el-table-column label="Result" min-width="145"><template #default="{row}"><el-tag :type="row.status==='recorded'?'success':row.status==='failed'?'danger':'info'">{{row.status==='recorded'?'Recorded':row.status==='failed'?'Failed':'Pending'}}</el-tag><small v-if="row.error" class="cash-overdue">{{row.error}}</small><template v-if="row.status==='recorded'"><small>{{row.savedDate}} · {{row.savedReference}}</small><el-button text type="primary" @click="showBatch(row.batchId)">View registration</el-button></template></template></el-table-column>
   <el-table-column label="Action" width="70" fixed="right"><template #default="{row}"><el-button :disabled="saving||row.status==='recorded'" text type="danger" @click="removeAllocation(row)">Remove</el-button></template></el-table-column>
  </el-table>
  <template v-for="section in [{title:'Pending totals — not yet recorded',rows:pendingTotals},{title:'Recorded totals',rows:recordedTotals}]" :key="section.title">
   <template v-if="section.rows.length"><h3>{{section.title}}</h3><el-table :data="section.rows" :data-testid="section.title.startsWith('Pending')?'pending-cash-totals':'recorded-cash-totals'">
    <el-table-column prop="currency" label="Currency" width="100"/>
    <el-table-column label="Receivable settled" align="right"><template #default="{row}">{{row.currency}} {{money(row.receivable,row.currency)}}</template></el-table-column>
    <el-table-column label="Payable settled" align="right"><template #default="{row}">{{row.currency}} {{money(row.payable,row.currency)}}</template></el-table-column>
    <el-table-column label="Net (reference only)" align="right"><template #default="{row}">{{row.currency}} {{money(row.net,row.currency)}}</template></el-table-column>
   </el-table></template>
  </template>
  <p v-if="payment.replacement">Replacement of registration {{payment.replacement}}</p>
  <template #footer><el-button :disabled="saving" @click="paymentVisible=false">{{recordedPayments.length?'Close':'Cancel'}}</el-button><el-button type="primary" :loading="saving" :disabled="!pendingPayments.length" @click="savePayment">{{payment.allocations.some(a=>a.status==='failed')?'Retry failed accounts':'Record registrations'}}</el-button></template>
 </el-dialog>
 <el-dialog :model-value="!!activeBatch" title="Receipt / payment registration details" width="min(1100px,96vw)" @close="activeBatch=null">
  <template v-if="activeBatch"><p>{{activeBatch.paymentDate}} · {{activeBatch.partyName}} · {{activeBatch.currency}} · {{activeBatch.status}}</p><p>Accounting Dept. Ref.: {{activeBatch.reference||'—'}} · {{activeBatch.note}}</p><p>Receivable settled: {{activeBatch.currency}} {{money(activeBatch.receivableSettled,activeBatch.currency)}} · Payable settled: {{activeBatch.currency}} {{money(activeBatch.payableSettled,activeBatch.currency)}} · {{activeBatch.pureOffset?'Pure offset':activeBatch.netCash<0?'Net paid':'Net received'}}: {{activeBatch.currency}} {{money(Math.abs(activeBatch.netCash),activeBatch.currency)}}</p>
   <p v-if="activeBatch.replacementOfBatchId">Replaces {{activeBatch.replacementOfBatchId}}</p><p v-if="activeBatch.replacementBatchIds?.length">Replaced by {{activeBatch.replacementBatchIds.join(', ')}}</p>
   <el-table :data="activeBatch.allocations"><el-table-column label="TW Ref" min-width="220"><template #default="{row}">{{displayTwRef(row)}}</template></el-table-column><el-table-column label="Transaction" min-width="260"><template #default="{row}">{{transactionNumber(row.txNo)||'Historical schedule'}}</template></el-table-column><el-table-column prop="paymentDirection" label="Direction"/><el-table-column label="Receipt / Payment Amount" align="right"><template #default="{row}">{{activeBatch.currency}} {{money(row.cashAmount,activeBatch.currency)}}</template></el-table-column><el-table-column v-if="activeBatch.allocations.some(a=>a.offsetAmount)" label="Historical offset" align="right"><template #default="{row}">{{activeBatch.currency}} {{money(row.offsetAmount,activeBatch.currency)}}</template></el-table-column><el-table-column v-if="activeBatch.allocations.some(a=>a.settlementDueDate)" prop="settlementDueDate" label="Swiss settlement due date" min-width="170"/></el-table>
  </template><template #footer><el-button @click="activeBatch=null">Close</el-button><el-button v-if="canEdit&&activeBatch?.canReverse" type="danger" :loading="saving" @click="reverseBatch">Reverse entire registration</el-button><el-button v-if="canEdit&&activeBatch?.status==='reversed'" type="primary" @click="replaceBatch">Re-register</el-button></template>
 </el-dialog>
 <el-dialog :model-value="!!historyRow" :title="historyRow?.cashTracking==='derived'?'Brokerage settlement details':'Account history'" width="min(1100px,96vw)" @close="historyRow=null">
  <template v-if="historyRow"><p>{{rowTitle(historyRow)}} · {{transactionParty(historyRow)}}</p>
   <template v-if="historyRow.cashTracking==='derived'"><p>Brokerage settles automatically after its own T1 and T2 complete. This creates no bank remittance.</p><p v-for="d in historyRow.settlementDependencies" :key="d.txNo">{{transactionNumber(d.txNo)}} · {{label(d.settlement)}}</p></template>
   <el-table v-else :data="historyRow.entries||[]"><el-table-column prop="paymentDate" label="Date"/><el-table-column prop="entryType" label="Type"/><el-table-column label="Receipt / Payment Amount"><template #default="{row}">{{row.nonCash?'—':historyRow.currency+' '+money(row.appliedAmount,historyRow.currency)}}</template></el-table-column><el-table-column v-if="historyRow.entries?.some(e=>e.nonCash)" label="Historical offset"><template #default="{row}">{{row.nonCash?historyRow.currency+' '+money(row.appliedAmount,historyRow.currency):'—'}}</template></el-table-column><el-table-column prop="reference" label="Accounting Dept. Ref."/><el-table-column prop="note" label="Note"/><el-table-column label="Action"><template #default="{row}"><el-button v-if="row.entryType==='payment'&&row.entryKind!=='legacy-import'" text @click="showBatch(row.batchId||row.offsetId||'legacy:'+row.id)">View registration</el-button><small v-else-if="row.entryKind==='legacy-import'">Settled before import</small></template></el-table-column></el-table>
   <template v-if="accountReviews.length"><h3>Finance review history</h3><el-table :data="accountReviews"><el-table-column prop="date" label="Review date"/><el-table-column prop="reference" label="Review reference"/><el-table-column prop="note" label="Explanation"/><el-table-column prop="createdByName" label="Finance"/><el-table-column prop="status" label="Status"/><el-table-column prop="cancelReason" label="Cancellation reason"/></el-table></template>
   <template v-if="caseHistories[historyRow.caseUid]?.length"><h3>Account correction history</h3><el-table :data="caseHistories[historyRow.caseUid]"><el-table-column prop="at" label="Changed at"/><el-table-column prop="byName" label="Operator"/><el-table-column prop="reason" label="Reason"/><el-table-column label="Changes"><template #default="{row}"><div v-for="(c,i) in row.ledgerChanges||[]" :key="i">{{transactionNumber(c.before.txNo)}}: {{money(c.before.amount,historyRow.currency)}} → {{c.after?money(c.after.amount,historyRow.currency):'Removed'}}</div></template></el-table-column><el-table-column prop="productionMonth" label="Production correction month"/></el-table></template>
   <el-table v-if="historyRow.paymentEditHistory?.length" :data="historyRow.paymentEditHistory"><el-table-column prop="changedAt" label="Historical change time"/><el-table-column prop="reason" label="Reason"/><el-table-column prop="changedByName" label="Operator"/></el-table>
   <el-table v-if="historyRow.settlementHistory?.length" :data="historyRow.settlementHistory"><el-table-column prop="confirmedAt" label="Historical settlement time"/><el-table-column prop="confirmedByName" label="Operator"/><el-table-column prop="note" label="Reference / reason"/></el-table>
  </template>
 </el-dialog>
 <el-dialog v-model="termsVisible" title="Complete historical missing contract days" width="min(560px,94vw)" :close-on-click-modal="false"><el-form label-position="top"><el-form-item label="Calendar days (minimum 15)" required><el-input-number v-model="terms.days" :min="15" :precision="0" :controls="false"/></el-form-item><el-form-item label="Reason" required><el-input v-model="terms.reason" type="textarea" maxlength="1000"/></el-form-item></el-form><template #footer><el-button @click="termsVisible=false">Cancel</el-button><el-button type="primary" :loading="saving" @click="saveTerms">Save with history</el-button></template></el-dialog>
</div>
</template>
<style scoped>
.compact-payment-table :deep(.cell){padding-left:6px;padding-right:6px;white-space:normal;overflow-wrap:anywhere;word-break:normal}
.compact-payment-table :deep(.payment-outstanding .cell){white-space:nowrap}
.compact-payment-table :deep(.el-table__cell){padding-top:7px;padding-bottom:7px}
.compact-payment-table .cash-input{flex-direction:row;align-items:center;flex-wrap:nowrap;gap:4px}
.compact-payment-table .cash-input>span{font-size:12px;flex:0 0 auto;white-space:nowrap}
.compact-payment-table .cash-input .el-input-number{flex:1; width:0;min-width:0}
.compact-payment-table :deep(.el-input__wrapper){padding-left:6px;padding-right:6px}
.compact-payment-table :deep(.el-button){white-space:normal;height:auto;line-height:1.4;padding:4px 2px}

:global(.accounting-modal .el-table-fixed-column--right){background-color:var(--el-bg-color,#fff)!important}

.cash-input{display:flex;align-items:center;gap:8px}.cash-input .el-input-number{min-width:0;width:150px}.selection-actions{display:flex;flex-wrap:wrap;gap:8px}.selection-hint{padding:0 16px}.accounting-tabs,.accounting-filters{padding:0 16px}.cash-overdue{display:block;color:var(--el-color-danger)}small{display:block}.entry-dates+.entry-dates{margin-top:8px}.table-pagination{display:flex;justify-content:flex-end;margin-top:12px;overflow-x:auto}
@media(max-width:760px){.section-heading{align-items:flex-start;flex-direction:column;gap:12px}.accounting-tabs{padding:0 8px}.accounting-filters{padding:0 12px}}
.table-card :deep(.el-scrollbar__bar.is-vertical){width:10px;right:0}
.table-card :deep(.el-scrollbar__thumb){background-color:#858b94;opacity:.8}
.table-card :deep(.accounting-top-scroll input){appearance:none;display:block;width:100%;height:18px;margin:0;padding:0;border:0;background:transparent;cursor:grab}
.table-card :deep(.accounting-top-scroll input::-webkit-slider-runnable-track){height:14px;background:#e5e7eb;border-radius:7px}
.table-card :deep(.accounting-top-scroll input::-webkit-slider-thumb){appearance:none;width:36px;height:14px;border:2px solid #e5e7eb;border-radius:7px;background:#858b94}
.table-card :deep(.accounting-top-scroll input::-moz-range-track){height:14px;background:#e5e7eb;border-radius:7px}
.table-card :deep(.accounting-top-scroll input::-moz-range-thumb){width:32px;height:10px;border:2px solid #e5e7eb;border-radius:7px;background:#858b94}
.table-card :deep(.accounting-top-scroll input:focus-visible){outline:2px solid var(--el-color-primary);outline-offset:1px;border-radius:7px}
/* Fixed cells must be opaque: the global table theme intentionally uses transparency. */
:deep([data-testid="accounting-table"] td.el-table-fixed-column--left),
:deep([data-testid="accounting-table"] th.el-table-fixed-column--left){background:var(--surface-card,#f7f6f2)!important}
:deep([data-testid="accounting-table"] td.el-table-fixed-column--left){z-index:2}
:deep([data-testid="accounting-table"] th.el-table-fixed-column--left){z-index:4}
:deep([data-testid="accounting-table"] tr.hover-row>td.el-table-fixed-column--left){background:#f0e7e6!important}
</style>
