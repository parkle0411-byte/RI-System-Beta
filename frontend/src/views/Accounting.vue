<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiFetch } from '../api'
import { can } from '../auth'
import { formatMoney, formatMoneyInput, parseMoneyInput, reportWriteError } from '../alpha/format'
import { shell } from '../alpha/shell'
import { displayTwRef } from '../alpha/manualTwRef'
import { transactionNumber } from '../alpha/transactionNumber'
import { transactionParty, paymentDirection } from '../alpha/transactionParty'
import vSyncInputNumberAria from '../directives/syncInputNumberAria'
import AccountingEntryActions from '../components/AccountingEntryActions.vue'
import { accountingRows } from '../alpha/accountingRows'
const router=useRouter()
const loading=ref(false), saving=ref(false), rows=ref([]), batches=ref([]), currencies=ref([]), canEdit=ref(false), selected=ref([])
const filters=reactive({reference:'',party:'',currency:'',leg:'',settlement:'',source:'',from:'',to:''})
const swissRows=ref([])
const dataWarnings=ref([])
const entryActions=ref(null)
const paymentVisible=ref(false), historyRow=ref(null), batchVisible=ref(false), activeBatch=ref(null)
const payment=reactive({date:today(),amount:null,reference:'',note:'',allocations:[]})
function today(){return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())}
const filtered=computed(()=>rows.value.filter(r=>{
  const includes=(values,query)=>values.some(v=>String(v||'').toLowerCase().includes(query.trim().toLowerCase()))
  return (!filters.reference||includes([r.statementNo,r.txNo,transactionNumber(r.txNo),r.reconciliationRef,displayTwRef(r)],filters.reference)) && (!filters.party||includes([transactionParty(r),r.reinsurer],filters.party)) && (!filters.currency||r.currency===filters.currency) && (!filters.leg||String(r.legType||'').startsWith(filters.leg)) && (!filters.settlement||r.settlement===filters.settlement) && (!filters.source||r.source===filters.source) && (!filters.from||!r.announcedAt||String(r.announcedAt).slice(0,10)>=filters.from) && (!filters.to||!r.announcedAt||String(r.announcedAt).slice(0,10)<=filters.to)
}))
const toCents=v=>Math.round(Number(v||0)*100)
const allocated=computed(()=>payment.allocations.reduce((sum,a)=>sum+toCents(a.amount),0)/100)
const difference=computed(()=>(toCents(payment.amount)-toCents(allocated.value))/100)
function statusLabel(r){return r.reversed?'Reversed':r.isReversalEntry?'Reversal entry':({settled:'Settled',partial:'Partial',open:'Open',pending_confirmation:'Awaiting confirmation',not_tracked:'Not tracked'})[r.settlement]||'Open'}
function eligible(row){return canEdit.value&&!row.scheduleOnly&&row.canRecord&&row.paymentAllowed!==false&&!row.statementNeedsRevision&&(!selected.value.length||selected.value[0].paymentGroup===row.paymentGroup)}
const rowTitle=row=>row.scheduleOnly?'Premium · '+row.installmentLabel:transactionNumber(row.txNo)
const needsCollection=row=>row.schedules?.some(item=>item.requiresCollectionConfirmation)
const feeAllowed=item=>item.requiresCollectionConfirmation&&Math.abs(item.outstanding)>.004
const offsetAllowed=item=>item.amount<0&&Math.abs(item.outstanding)>.004&&(item.partyType==='cedant'||item.swissFacility)&&item.rootCaseUid!==item.caseUid
const statementAllowed=item=>item.swissFacility&&item.amount>0&&item.outstanding>.004
const hasEntryActions=row=>row.schedules?.some(item=>feeAllowed(item)||offsetAllowed(item)||statementAllowed(item))
function toggle(row,value){selected.value=value?[...selected.value,row]:selected.value.filter(r=>r.key!==row.key)}
async function load(){
 loading.value=true;shell.error=''
 try{const response=await apiFetch('/api/accounting');const body=await response.json();if(!response.ok)throw new Error(body.message||body.error);swissRows.value=body.swissRows||[];dataWarnings.value=(body.warnings||[]).filter(w=>w.dataError);rows.value=accountingRows(body);batches.value=body.cashBatches||[];currencies.value=[...new Set([...(body.currencies||[]),...rows.value.map(row=>row.currency).filter(Boolean)])].sort();canEdit.value=!!body.scope?.canEdit;selected.value=[]
 if(historyRow.value)historyRow.value=rows.value.find(r=>r.key===historyRow.value.key)||null
 if(activeBatch.value)activeBatch.value=batches.value.find(b=>b.batchId===activeBatch.value.batchId)||null
 }catch(err){shell.error=err.message;ElMessage.error(err.message)}finally{loading.value=false}
}
async function post(body){const response=await apiFetch('/api/accounting',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const result=await response.json();if(!response.ok){const err=new Error(result.message||result.error);err.status=response.status;throw err}return result}
function openPayment(targets){if(!targets.length)return;payment.date=today();payment.reference='';payment.note='';payment.amount=targets.every(r=>r.fullPaymentRequired)?targets.reduce((s,r)=>s+Math.abs(r.outstanding),0):targets.length===1?Math.abs(targets[0].outstanding):null;payment.allocations=targets.map(row=>({row,amount:row.fullPaymentRequired||targets.length===1?Math.abs(row.outstanding):null}));paymentVisible.value=true}
async function savePayment(){
 if(payment.allocations.length===1)payment.allocations[0].amount=payment.amount
 if(!payment.date||toCents(payment.amount)<=0||difference.value!==0||payment.allocations.some(a=>toCents(a.amount)<=0||toCents(a.amount)>Math.abs(toCents(a.row.outstanding))||(a.row.fullPaymentRequired&&toCents(a.amount)!==Math.abs(toCents(a.row.outstanding)))))return ElMessage.warning('Enter positive allocations within each balance. The allocation total must equal the remittance amount.')
 saving.value=true
 try{const single=payment.allocations.length===1&&payment.allocations[0].row.scheduleOnly?payment.allocations[0].row:null
 await post(single?{action:'record_payment',caseUid:single.caseUid,rowVersion:single.caseRowVersion,scheduleKey:single.scheduleKey,paymentDate:payment.date,amount:payment.amount,reference:payment.reference,note:payment.note}:{action:'record_transaction_payments',paymentDate:payment.date,amount:payment.amount,reference:payment.reference,note:payment.note,allocations:payment.allocations.map(a=>({caseUid:a.row.caseUid,txNo:a.row.txNo,rowVersion:a.row.caseRowVersion,amount:a.amount}))});paymentVisible.value=false;ElMessage.success('Payment recorded');await load()}
 catch(err){if(err.status===409)paymentVisible.value=false;reportWriteError(err,()=>load());await load()}finally{saving.value=false}
}
function showBatch(id){activeBatch.value=batches.value.find(b=>b.batchId===id)||null;if(activeBatch.value)batchVisible.value=true}
async function reverseBatch(){const batch=activeBatch.value;if(!batch?.canReverse||!canEdit.value)return
 try{await ElMessageBox.confirm('Reverse the entire remittance, including all allocations across cases. Original entries remain in history.','Reverse remittance',{type:'warning',confirmButtonText:'Create reversal'})}catch{return}
 saving.value=true
 try{const versions=new Map(batch.allocations.map(a=>[a.caseUid,a.caseRowVersion]));await post({action:'reverse_batch_payment',batchId:batch.batchId,cases:[...versions].map(([caseUid,rowVersion])=>({caseUid,rowVersion})),paymentDate:today()});ElMessage.success('Entire remittance reversed');await load()}catch(err){reportWriteError(err,()=>load());await load()}finally{saving.value=false}
}
async function reverseLegacy(row,entry){
 try{await ElMessageBox.confirm('Reverse the complete original schedule payment. All transaction balances sharing this payment will be recalculated.','Reverse legacy payment',{type:'warning'})}catch{return}
 saving.value=true
 try{await post({action:'reverse_payment',caseUid:row.caseUid,rowVersion:row.caseRowVersion,entryId:entry.id,paymentDate:today(),note:'Correction reversal'});await load()}catch(err){reportWriteError(err,()=>load());await load()}finally{saving.value=false}
}
async function confirmSettlement(row,undo=false){
 if(!canEdit.value)return
 let note
 try{const result=await ElMessageBox.prompt(undo?'Enter the reason for cancelling this settlement confirmation.':'Confirm the reconciliation and enter its reference or reason.',undo?'Cancel settlement confirmation':'Confirm settlement',{inputValidator:v=>!!v?.trim()||'A reference or reason is required.'});note=result.value}catch{return}
 saving.value=true
 try{await post({action:undo?'unconfirm_facility_settlement':'confirm_facility_settlement',caseUid:row.caseUid,rowVersion:row.caseRowVersion,...(row.scheduleOnly?{scheduleKey:row.scheduleKey}:{txNo:row.txNo}),note});ElMessage.success(undo?'Settlement confirmation cancelled':'Settlement confirmed by Accounting');await load()}catch(err){reportWriteError(err,()=>load());await load()}finally{saving.value=false}
}
function openCase(row){router.push({path:'/cases',query:{case:row.caseUid,tab:'soa'}})}
onMounted(load)
</script>
<template>
<div class="overview-stack">
<el-alert v-if="dataWarnings.length" type="error" :closable="false" show-icon title="Some cases could not be read and are not shown" :description="dataWarnings.map(w=>(w.twRef||w.caseUid)).join(', ')+'. Contact the System Administrator.'" />
<section class="table-card">
 <div class="section-heading"><div><h2>Accounting · SoA / Transactions</h2><p>Transactions, announced premium entries, due dates and cash balances in one list. Receipts, payments, reversals, clearance and offsets are entered manually by Accounting. Nothing settles automatically: every premium and claim entry needs Accounting to confirm settlement, even at a zero balance.</p></div><el-button :loading="loading" @click="load">Refresh</el-button></div>
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
 <div class="section-heading"><div><h2>SoA / Transactions ({{ filtered.length }})</h2><p>Select transactions with the same currency, cash direction and counterparty to record one remittance.</p></div><el-button v-if="canEdit" class="primary-button" :disabled="!selected.length" @click="openPayment(selected)">Record selected ({{ selected.length }})</el-button></div>
 <el-table :data="filtered" row-key="key" data-testid="accounting-table" empty-text="No accounting entries. Premium transactions appear after Production close; announced Swiss Facility Property entries can be handled before close.">
  <el-table-column v-if="canEdit" width="44"><template #default="{row}"><el-checkbox v-if="!row.scheduleOnly" :model-value="selected.some(r=>r.key===row.key)" :disabled="!eligible(row)" :aria-label="'Select '+transactionNumber(row.txNo)" @change="value=>toggle(row,value)" /></template></el-table-column>
  <el-table-column label="Transaction / SoA / TW Ref" min-width="250" fixed="left"><template #default="{row}"><el-button v-if="can('cases.read.all')" text class="table-action" @click="openCase(row)">{{ rowTitle(row) }}</el-button><strong v-else>{{ rowTitle(row) }}</strong><br><small>SoA: {{ row.statementNo||'—' }}<br>{{ displayTwRef(row) }} · {{ row.installmentLabel|| (row.source==='claim'?'Claim':'Premium') }}</small><small v-if="row.scheduleOnly">Awaiting Production close</small><small v-if="row.reversed||row.isReversalEntry">{{ statusLabel(row) }}</small></template></el-table-column>
  <el-table-column label="Original Insured (EN / CN)" min-width="240"><template #default="{row}"><div>{{ row.originalInsured||'—' }}</div><div>{{ row.originalInsuredCn||'—' }}</div></template></el-table-column>
  <el-table-column label="Reconciliation Ref" min-width="140"><template #default="{row}">{{ row.reconciliationRef||'—' }}</template></el-table-column>
  <el-table-column label="Party / Leg" min-width="190"><template #default="{row}">{{ transactionParty(row) }}<br><small>{{ row.legType }} · {{ paymentDirection(row) }}</small><br><small>{{ row.source==='claim'?'Claim':row.returnPremium?'Return premium':'Premium' }}</small></template></el-table-column>
  <el-table-column label="Amount" align="right" min-width="135"><template #default="{row}">{{ row.currency }} {{ formatMoney(row.amount) }}</template></el-table-column>
  <el-table-column label="Paid / received" align="right" min-width="110"><template #default="{row}">{{ formatMoney(row.cashPaid??row.paid) }}<small v-if="row.nonCashPaid">Cleared by fee / offset: {{ formatMoney(row.nonCashPaid) }}</small></template></el-table-column>
  <el-table-column label="Outstanding" align="right" min-width="140"><template #default="{row}"><strong>{{ row.currency }} {{ formatMoney(row.outstanding) }}</strong></template></el-table-column>
  <el-table-column label="Due date" min-width="210"><template #default="{row}">
   <template v-if="row.schedules.length"><div v-for="item in row.schedules" :key="item.key" class="entry-dates"><small v-if="row.schedules.length>1">{{ item.installmentLabel }}</small>
    <template v-if="item.swissFacility"><div>Original Swiss: {{ item.originalDueDate||'—' }}</div><div>{{ item.projectedDueDate?'Projected':'Settlement' }}: {{ item.dueDate||'—' }}</div><small v-if="item.confirmationCutoff">Cutoff: {{ item.confirmationCutoff }}</small></template>
    <template v-else><div>Accounting: {{ item.dueDate||'—' }}</div><small v-if="item.contractDueDate">Contract: {{ item.contractDueDate }}</small></template>
    <small v-if="item.status==='reminder'">75-day reminder</small><small v-if="item.status==='overdue'" class="cash-overdue">Overdue</small><small v-if="item.statementNeedsRevision" class="cash-overdue">Statement moved from {{ item.statementDueDate }}. Revise manually.</small>
   </div></template>
   <template v-else>{{ row.dueDate||'—' }}<small v-if="row.dueTime"> · {{ row.dueTime }} TW</small><small v-if="row.contractDueDate">{{ row.partyType==='cedant'?'Cedant Due Date':row.swissFacility?'Swiss settlement':'AUW due' }}: {{ row.contractDueDate }}</small><small v-if="row.originalDueDate">Original Swiss: {{ row.originalDueDate }}</small><small v-if="row.projectedDueDate">Projected: {{ row.projectedDueDate }}</small><small v-if="row.paymentStatus==='reminder'">75-day reminder</small><small v-if="row.paymentStatus==='overdue'" class="cash-overdue">Overdue</small><small v-if="row.statementNeedsRevision" class="cash-overdue">Revise statement period</small></template>
  </template></el-table-column>
  <el-table-column label="Settlement / collection" min-width="200"><template #default="{row}"><el-tag :type="row.settlement==='settled'?'success':row.settlement==='partial'?'warning':'info'">{{ statusLabel(row) }}</el-tag>
   <template v-for="item in row.schedules" :key="item.key"><div v-if="item.requiresCollectionConfirmation"><small v-if="row.schedules.length>1">{{ item.installmentLabel }}</small><el-tag :type="item.collectionConfirmed?'success':'warning'">{{ item.collectionConfirmed?'Confirmed collected':'Confirmation needed' }}</el-tag><small v-if="item.collectionConfirmedAt">{{ item.collectionConfirmedAt }} · {{ item.collectionConfirmationSource }}</small><small v-if="item.latestReceiptDate">Latest receipt: {{ item.latestReceiptDate }}</small></div></template>
   <small v-if="row.paymentAllowed===false">{{ row.paymentBlockedReason }}</small>
  </template></el-table-column>
  <el-table-column label="Action" min-width="220"><template #default="{row}">
   <el-button v-if="canEdit&&row.canRecord" :disabled="row.paymentAllowed===false||row.statementNeedsRevision" text type="primary" @click="openPayment([row])">Record payment</el-button>
   <template v-if="canEdit" v-for="item in row.schedules" :key="item.key"><el-button v-if="item.requiresCollectionConfirmation" text type="primary" :disabled="!item.collectionConfirmed&&!item.canConfirmCollection" @click="entryActions.confirm(item,item.collectionConfirmed)">{{ item.collectionConfirmed?'Cancel confirmation':'Confirm collected' }}{{ row.schedules.length>1?' · '+item.installmentLabel:'' }}</el-button></template>
   <el-button v-if="canEdit&&row.manualSettlementRequired&&!needsCollection(row)&&!row.reversed&&!row.isReversalEntry&&!row.manualSettlementConfirmed" text type="primary" :disabled="!row.canConfirmSettlement||saving" @click="confirmSettlement(row)">Confirm settlement</el-button>
   <el-button v-if="canEdit&&row.manualSettlementConfirmed&&!needsCollection(row)&&!row.reversed&&!row.isReversalEntry" text @click="confirmSettlement(row,true)">Cancel settlement</el-button>
   <el-dropdown v-if="canEdit&&hasEntryActions(row)" trigger="click" @command="command=>entryActions.open(command.item,command.kind)"><el-button text>More</el-button><template #dropdown><el-dropdown-menu><template v-for="item in row.schedules" :key="item.key">
    <el-dropdown-item v-if="feeAllowed(item)" :command="{item,kind:'clearance'}">Fee / shortfall{{ row.schedules.length>1?' · '+item.installmentLabel:'' }}</el-dropdown-item>
    <el-dropdown-item v-if="offsetAllowed(item)" :command="{item,kind:'offset'}">Offset with original{{ row.schedules.length>1?' · '+item.installmentLabel:'' }}</el-dropdown-item>
    <el-dropdown-item v-if="statementAllowed(item)" :command="{item,kind:'statement'}">{{ item.statementNeedsRevision?'Confirm revised statement':'Statement reference' }}{{ row.schedules.length>1?' · '+item.installmentLabel:'' }}</el-dropdown-item>
   </template></el-dropdown-menu></template></el-dropdown>
   <el-button v-if="row.entries?.length||row.cashTracking==='derived'||row.settlementHistory?.length" text @click="historyRow=row">{{ row.cashTracking==='derived'?(row.manualSettlementRequired?'Settlement history':'Auto settlement'):'History' }}</el-button>
  </template></el-table-column>
 </el-table>
</section>
<AccountingEntryActions ref="entryActions" :rows="swissRows" :can-edit="canEdit" @refresh="load" />
<el-dialog v-model="paymentVisible" title="Record remittance" width="min(900px, 94vw)" :close-on-click-modal="false">
 <p v-if="payment.allocations.length">{{ payment.allocations[0].row.currency }} · {{ paymentDirection(payment.allocations[0].row) }} · {{ transactionParty(payment.allocations[0].row) }}</p>
 <el-form label-position="top"><div class="form-grid cols-2">
 <el-form-item label="Payment date" required><el-date-picker v-model="payment.date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
 <el-form-item label="Remittance amount (positive magnitude)" required><el-input-number v-model="payment.amount" :min="0.01" :precision="2" :controls="false" :formatter="formatMoneyInput" :parser="parseMoneyInput" @change="value=>{if(payment.allocations.length===1)payment.allocations[0].amount=value}" /></el-form-item>
 <el-form-item label="Bank / remittance reference"><el-input v-model="payment.reference" maxlength="200" /></el-form-item><el-form-item label="Note"><el-input v-model="payment.note" maxlength="1000" /></el-form-item>
 </div></el-form>
 <el-table :data="payment.allocations"><el-table-column label="Transaction" min-width="260"><template #default="{row}">{{ rowTitle(row.row) }}<br><small>{{ displayTwRef(row.row) }}</small></template></el-table-column><el-table-column label="Outstanding" align="right"><template #default="{row}">{{ formatMoney(Math.abs(row.row.outstanding)) }}</template></el-table-column><el-table-column label="Allocated amount" width="210"><template #default="{row}"><el-input-number v-sync-input-number-aria v-model="row.amount" :disabled="payment.allocations.length===1||row.row.fullPaymentRequired" :min="0.01" :max="Math.abs(row.row.outstanding)" :precision="2" :controls="false" :formatter="formatMoneyInput" :parser="parseMoneyInput" /></template></el-table-column></el-table>
 <el-alert :type="difference===0?'success':'warning'" :closable="false" style="margin-top:16px" :title="'Allocated: '+formatMoney(allocated)+' · Difference: '+formatMoney(difference)" />
 <p>Allocate the complete remittance. Swiss premium payables and Cedant refunds must each be paid in full.</p>
 <template #footer><el-button @click="paymentVisible=false">Cancel</el-button><el-button class="primary-button" :loading="saving" @click="savePayment">Record payment</el-button></template>
</el-dialog>
<el-dialog :model-value="!!historyRow" :title="historyRow?.cashTracking==='derived'?'Brokerage settlement':'Payment history'" width="min(850px,94vw)" @close="historyRow=null">
 <template v-if="historyRow"><p>{{ rowTitle(historyRow) }} · {{ transactionParty(historyRow) }}</p>
 <template v-if="historyRow.cashTracking==='derived'"><el-alert :title="historyRow.manualSettlementRequired?'Brokerage requires Accounting to confirm settlement after the matching T1 and T2 are manually settled. This creates no bank remittance.':'Brokerage is retained from premium cash flows. It settles automatically after the matching T1 and T2 transactions settle.'" :closable="false" type="info" /><p v-for="dependency in historyRow.settlementDependencies" :key="dependency.txNo">{{ transactionNumber(dependency.txNo) }} · {{ dependency.settlement }}</p></template>
 <el-table v-else :data="historyRow.entries||[]"><el-table-column prop="paymentDate" label="Date" /><el-table-column label="Type"><template #default="{row}">{{ row.entryType }}{{ row.entryKind?' · '+row.entryKind:'' }}</template></el-table-column><el-table-column label="Applied amount" align="right"><template #default="{row}">{{ formatMoney(row.appliedAmount) }}</template></el-table-column><el-table-column prop="settlementDueDate" label="Swiss period" /><el-table-column prop="reference" label="Reference" /><el-table-column prop="note" label="Note" /><el-table-column label="Action" width="160"><template #default="{row}"><el-button v-if="row.batchId&&row.entryType==='payment'" text @click="showBatch(row.batchId)">View remittance</el-button><el-button v-else-if="canEdit&&row.entryType==='payment'&&!row.offsetId&&!historyRow.reversed&&!historyRow.isReversalEntry&&!historyRow.entries.some(e=>e.reversalOf===row.id)" text type="danger" @click="reverseLegacy(historyRow,row)">Reverse original</el-button></template></el-table-column></el-table>
 <el-table v-if="historyRow.settlementHistory?.length" :data="historyRow.settlementHistory"><el-table-column prop="confirmedAt" label="Confirmation time" /><el-table-column label="Action"><template #default="{row}">{{ row.confirmed?'Confirmed settlement':'Cancelled settlement' }}</template></el-table-column><el-table-column prop="confirmedByName" label="Accountant" /><el-table-column prop="note" label="Reference / reason" /></el-table>
 </template>
</el-dialog>
<el-dialog v-model="batchVisible" title="Remittance details" width="min(900px,94vw)">
 <template v-if="activeBatch"><p>{{ activeBatch.paymentDate }} · {{ activeBatch.currency }} {{ formatMoney(activeBatch.amount) }} · {{ activeBatch.partyName }} · {{ activeBatch.status }}</p><p>{{ activeBatch.reference }} · {{ activeBatch.note }}</p><el-table :data="activeBatch.allocations"><el-table-column prop="twRef" label="TW Ref" min-width="210" /><el-table-column label="Transaction" min-width="230"><template #default="{row}">{{ transactionNumber(row.txNo) }}</template></el-table-column><el-table-column label="Amount" align="right"><template #default="{row}">{{ formatMoney(row.amount) }}</template></el-table-column></el-table></template>
 <template #footer><el-button @click="batchVisible=false">Close</el-button><el-button v-if="canEdit&&activeBatch?.canReverse" type="danger" :loading="saving" @click="reverseBatch">Reverse entire remittance</el-button></template>
</el-dialog>
</div>
</template>
<style scoped>.cash-overdue{display:block;color:var(--el-color-danger)}small{display:block}.entry-dates+.entry-dates{margin-top:8px}</style>
