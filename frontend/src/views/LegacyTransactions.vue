<script setup>
import { computed,onMounted,ref,watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, apiFetch } from '../api'
import { can } from '../auth'
import LegacyEntryEditor from './LegacyEntryEditor.vue'

const route=useRoute(),loading=ref(false),error=ref(''),rows=ref([]),total=ref(0),q=ref(''),page=ref(1)
const dialog=ref(false),selected=ref(null),batchOpen=ref(false),batches=ref([])
const importFile=ref(null),importList=ref([]),importPreview=ref(null),importing=ref(false)
const transferOpen=ref(false),transferTarget=ref(null),transferReason=ref('')
const reasonOpen=ref(false),reason=ref({code:'',label:'',active:true})
const entryOpen=ref(false),entry=ref(null),options=ref({people:[],parties:[],rules:[],reasons:[]})
const amounts=computed(()=>selected.value?.data?.amounts || {})
const moneyLabels={gross:'100% Premium',premium:'Our Share Premium',commission:'R/I Comm.',tax:'Tax',
  brokerage:'Bkg. (Original Currency)',brokeragePct:'Bkg.(%)',claim:'Claim',cedantNet:'Net Premium from Cedant',reinsurerNet:'Net Premium to Reinsurer'}
const fields={reference:'Old Reference',classOfBusiness:'Class',newRenew:'New / Renew',statementNo:'Statement No.',insured:'Insured (English)',insuredCn:'Insured (Chinese)',
  cedant:'Cedant',party:'Settlement Party',effectiveDate:'Effective Date',expiryDate:'Expiry Date',currency:'Currency',
  revenueMonth:'Revenue Month (Production)',share:'Share (%)',ae:'AE',subAe:'Sub AE',installmentNo:'Installment No.',
  endorsementNo:'Endorsement No.',reinsurerRef:"Reinsurer's Ref. No.",remark:'Remark'}
const visibleFields=computed(()=>({...fields,...Object.fromEntries(Object.entries({lossDate:'DOL',claimNote:'Note for Claim',claimReason:'Negative Claim Reason',brokerageNote:'Note for Bkg.',oldReasonText:'Endorsement Reason Details'}).filter(([key])=>selected.value?.data?.[key]!=null && selected.value.data[key]!==''))}))
const number=v=>v==null?'—':new Intl.NumberFormat('en-US',{maximumFractionDigits:8}).format(v)
async function load(){
  loading.value=true;error.value=''
  try {const r=await api('/api/legacy?'+new URLSearchParams({q:q.value,page:String(page.value)}));rows.value=r.rows;total.value=r.count}
  catch(e){error.value=e.message}finally{loading.value=false}
}
async function open(uid){
  error.value=''
  try{selected.value=await api('/api/legacy?id='+encodeURIComponent(uid));dialog.value=true}
  catch(e){error.value=e.message}
}
async function showReasons(){
 try{options.value=await api('/api/legacy/options');reasonOpen.value=true}catch(e){error.value=e.message}
}
function newReason(){const id=Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');reason.value={code:'custom_'+id,label:'',active:true}}
function chooseReason(code){const r=options.value.reasons.find(r=>r.code===code);if(r)reason.value={...r}}
async function transfer(){
 try{await api('/api/legacy',{method:'PATCH',body:{id:selected.value.uid,version:selected.value.version,action:'transfer',ownerId:transferTarget.value,reason:transferReason.value}});transferOpen.value=false;await open(selected.value.uid);await load()}
 catch(e){error.value=e.message}
}
async function openTransfer(){
 try{options.value=await api('/api/legacy/options');transferTarget.value=null;transferReason.value='';transferOpen.value=true}catch(e){error.value=e.message}
}
async function saveReason(){
 error.value=''
 try{await api('/api/legacy/options',{method:'POST',body:reason.value});reasonOpen.value=false}
 catch(e){error.value=e.message}
}
async function retract(){
  error.value=''
  try{selected.value=await api('/api/legacy',{method:'PATCH',body:{id:selected.value.uid,version:selected.value.version,action:'retract'}});await load();await edit()}
  catch(e){error.value=e.message}
}
async function start(kind){
  error.value=''
  try{
    options.value=await api('/api/legacy/options')
    entry.value=await api('/api/legacy',{method:'POST',body:{referenceTransaction:selected.value.uid,kind}})
    dialog.value=false;entryOpen.value=true;await load()
  }catch(e){error.value=e.message}
}
async function edit(){
  error.value=''
  try{options.value=await api('/api/legacy/options');entry.value=selected.value;dialog.value=false;entryOpen.value=true}
  catch(e){error.value=e.message}
}
async function saved(t){selected.value=t;await load()}
async function showBatches(){
  try{batches.value=(await api('/api/legacy/imports')).batches;batchOpen.value=true}
  catch(e){error.value=e.message}
}
// 2026-11-11：系統管理員網頁匯入（先預覽，無錯誤與警告才可確認匯入）。
function chooseImport(file){importFile.value=file.raw;importList.value=[file];importPreview.value=null}
function clearImport(){importFile.value=null;importList.value=[];importPreview.value=null}
async function previewImport(){
  if(!importFile.value)return ElMessage.error('Select a Register XLSX file first.')
  if(importFile.value.size>30*1024*1024)return ElMessage.error('The file must be no larger than 30 MiB.')
  importing.value=true
  try{
    const body=new FormData();body.append('file',importFile.value)
    const response=await apiFetch('/api/legacy/imports',{method:'POST',body});const data=await response.json()
    if(!response.ok)throw new Error(data.message||data.detail||'Preview failed.')
    importPreview.value=data;batches.value=(await api('/api/legacy/imports')).batches
  }catch(e){ElMessage.error(e.message)}finally{importing.value=false}
}
const importBlocked=computed(()=>!importPreview.value||importPreview.value.status!=='preview'||!importPreview.value.manifest.eligible||importPreview.value.manifest.errors.length>0||importPreview.value.manifest.warnings.length>0)
async function commitImport(){
  const b=importPreview.value;if(importBlocked.value)return
  try{await ElMessageBox.confirm(`Import ${b.manifest.eligible} transactions from ${b.filename}? Imported transactions cannot be edited or withdrawn on the web.`,'Confirm Import',{type:'warning',confirmButtonText:'Import',cancelButtonText:'Cancel'})}catch{return}
  importing.value=true
  try{
    const done=await api('/api/legacy/imports',{method:'POST',body:{action:'commit',id:b.id,sha256:b.sha256}})
    ElMessage.success(`Imported ${done.manifest.imported} transactions.`)
    clearImport();batches.value=(await api('/api/legacy/imports')).batches;page.value=1;await load()
  }catch(e){ElMessage.error(e.message)}finally{importing.value=false}
}
watch(()=>route.query.id,id=>{if(id)open(id)})
onMounted(async()=>{await load();if(route.query.id)await open(route.query.id)})
</script>

<template>
  <section class="legacy-page">
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon/>
    <el-alert title="Imported transactions are read-only. Accounts settled in the Register are shown as reconciled and settled; unsettled imported balances continue in Accounting." type="info" :closable="false" show-icon/>
    <div class="legacy-toolbar">
      <el-input v-model="q" placeholder="Search old reference, transaction number, Statement No., insured or settlement party" clearable @keyup.enter="page=1;load()"/>
      <el-button @click="page=1;load()">Search</el-button><el-button v-if="can('accounts.manage')" @click="showBatches">Import Batches</el-button><el-button v-if="can('accounts.manage')" @click="showReasons">Endorsement Reasons</el-button>
    </div>
    <el-table v-loading="loading" :data="rows" row-key="uid" @row-dblclick="r=>open(r.uid)">
      <el-table-column label="Transaction No." min-width="125"><template #default="{row}"><el-button link type="primary" @click="open(row.uid)">{{row.number || 'Draft'}}</el-button></template></el-table-column>
      <el-table-column prop="reference" label="Old Reference" min-width="135"/><el-table-column prop="data.statementNo" label="Statement No." min-width="170"/>
      <el-table-column prop="data.insured" label="Insured" min-width="240"/><el-table-column prop="data.party" label="Settlement Party" min-width="240"/>
      <el-table-column prop="currency" label="Currency" width="80"/><el-table-column prop="revenueMonth" label="Revenue Month" width="110"/>
      <el-table-column prop="data.kind" label="Type" width="130"/><el-table-column label="Status" min-width="170"><template #default="{row}"><el-tag :type="row.historical?'success':row.status==='draft'?'info':'primary'">{{row.historical?'Historically Reconciled / Settled':row.imported?'Imported · Open in Accounting':row.status==='draft'?'Draft':'Confirmed'}}</el-tag><el-tag v-if="row.performance?.awaitingFx" type="warning">Awaiting FX</el-tag></template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page" :total="total" :page-size="25" layout="prev,pager,next,total" @current-change="load"/>
    <el-dialog v-model="dialog" width="min(1100px,96vw)" :title="selected?.number || 'Historical Transaction'">
      <template v-if="selected"><p v-if="selected.referenceSource">Source Transaction: <el-button link type="primary" @click="open(selected.referenceSource.uid)">{{selected.referenceSource.number}}</el-button> · {{selected.referenceSource.reference}}</p>
        <el-descriptions :title="selected.historical?'Historical Transaction Details':'Transaction Details'" :column="2" border><el-descriptions-item v-for="(label,key) in visibleFields" :key="key" :label="label">{{selected.data[key]==null||selected.data[key]===''?'—':selected.data[key]}}</el-descriptions-item></el-descriptions>
        <el-descriptions title="Transaction Amounts" :column="3" border><el-descriptions-item v-for="(label,key) in moneyLabels" :key="key" :label="label">{{number(key==='gross'?selected.data.gross:amounts[key])}}</el-descriptions-item></el-descriptions>
        <el-alert v-if="selected.performance?.awaitingFx" title="Awaiting FX for the selected Revenue Month. Original-currency Accounting remains available." type="warning" :closable="false"/><el-descriptions title="Performance Conversion" :column="2" border><el-descriptions-item label="Exchange Rate">{{number(selected.performance?.rate)}}</el-descriptions-item><el-descriptions-item label="Total Brokerage (TWD)">{{number(selected.performance?.incomeTwd)}}</el-descriptions-item></el-descriptions>
        <el-table :data="selected.performance?.people || []" style="margin-top:18px"><el-table-column prop="name" label="Performance Recipient"/><el-table-column label="Role"><template #default="{$index}">{{$index===0?'AE':'Sub AE'}}</template></el-table-column><el-table-column label="Brokerage (TWD)"><template #default="{row}">{{number(row.income)}}</template></el-table-column></el-table>
        <el-descriptions title="Original Accounting Information" :column="2" border><el-descriptions-item label="Collection Reminder Date">{{selected.data.receiveReminder||'—'}}</el-descriptions-item><el-descriptions-item label="Payment Reminder Date">{{selected.data.payReminder||'—'}}</el-descriptions-item><el-descriptions-item v-for="(value,key) in selected.data.accountingReferences||{}" :key="key" :label="key">{{value||'—'}}</el-descriptions-item></el-descriptions>
        <el-collapse><el-collapse-item v-if="selected.historical||selected.imported" title="Original Excel Data" name="original"><el-descriptions :column="2" border><el-descriptions-item v-for="(value,key) in selected.original" :key="key" :label="key">{{value}}</el-descriptions-item></el-descriptions></el-collapse-item><el-collapse-item title="History and Reasons" name="audit"><el-table :data="selected.audit||[]"><el-table-column prop="at" label="Time"/><el-table-column prop="actor" label="Actor"/><el-table-column prop="action" label="Action"/><el-table-column prop="reason" label="Reason"/></el-table></el-collapse-item></el-collapse>
      </template>
      <template #footer><el-button v-if="selected?.permissions?.transfer" @click="openTransfer">Transfer Draft</el-button><el-button v-if="selected?.permissions?.retract" @click="retract">Return to Draft</el-button><el-button v-if="selected?.permissions?.edit" type="primary" @click="edit">Edit Draft</el-button><template v-if="selected?.status==='confirmed' && can('cases.write')"><el-button type="primary" @click="start('endorsement')">New Endorsement</el-button><el-button type="primary" @click="start('claim')">New Claim</el-button></template><el-button @click="dialog=false">Close</el-button></template>
    </el-dialog>
    <el-dialog v-model="entryOpen" :title="entry?.data.kind==='claim'?'Claim Draft':'Endorsement Draft'" width="min(1100px,96vw)" :close-on-click-modal="false" :close-on-press-escape="false"><LegacyEntryEditor v-if="entryOpen" :transaction="entry" :options="options" @saved="saved" @close="entryOpen=false"/></el-dialog>
    <el-dialog v-model="transferOpen" title="Transfer Draft" width="min(600px,96vw)"><el-form label-position="top"><el-form-item label="New Owner"><el-select v-model="transferTarget" filterable><el-option v-for="p in options.people.filter(p=>['sales','general_manager','admin'].includes(p.role_code))" :key="p.id" :label="p.name" :value="p.id"/></el-select></el-form-item><el-form-item label="Transfer Reason"><el-input v-model="transferReason" type="textarea"/></el-form-item></el-form><template #footer><el-button @click="transferOpen=false">Close</el-button><el-button type="primary" @click="transfer">Transfer Draft</el-button></template></el-dialog>
    <el-dialog v-model="reasonOpen" title="Configure Endorsement Reasons" width="min(600px,96vw)"><el-select :model-value="reason.code" placeholder="Select a reason to edit" @change="chooseReason"><el-option v-for="r in options.reasons" :key="r.code" :label="r.label+(r.active?'':' (Inactive)')" :value="r.code"/></el-select><el-button @click="newReason">Add New Reason</el-button><el-form label-position="top"><el-form-item label="English Label"><el-input v-model="reason.label"/></el-form-item><el-form-item label="Active"><el-switch v-model="reason.active"/></el-form-item></el-form><template #footer><el-button @click="reasonOpen=false">Close</el-button><el-button type="primary" :disabled="!reason.code" @click="saveReason">Save Reason</el-button></template></el-dialog>
    <el-dialog v-model="batchOpen" title="Import Batches" width="min(1100px,96vw)">
      <section class="legacy-import" data-testid="legacy-import">
        <h3>Import a Register</h3>
        <p>Upload the reinsurer's Register (Facultative worksheet). Preview first; import is available only when the preview has no errors or warnings. Serial numbers already imported are skipped.</p>
        <div class="legacy-import-actions"><el-upload :auto-upload="false" :limit="1" :file-list="importList" accept=".xlsx" :on-change="chooseImport" :on-remove="clearImport"><el-button>Select XLSX</el-button></el-upload>
          <el-button type="primary" :loading="importing" :disabled="!importFile" @click="previewImport">Preview</el-button></div>
        <template v-if="importPreview">
          <el-descriptions :column="3" border title="Preview">
            <el-descriptions-item label="File">{{importPreview.filename}}</el-descriptions-item>
            <el-descriptions-item label="Rows in file">{{importPreview.manifest.sourceRows}}</el-descriptions-item>
            <el-descriptions-item label="To import">{{importPreview.manifest.eligible}}</el-descriptions-item>
            <el-descriptions-item label="Fully settled">{{importPreview.manifest.settlement?.fully ?? 0}}</el-descriptions-item>
            <el-descriptions-item label="With open balances">{{importPreview.manifest.settlement?.open ?? 0}}</el-descriptions-item>
            <el-descriptions-item label="Class">{{Object.entries(importPreview.manifest.classes||{}).map(([k,v])=>k+' '+v).join(' · ')||'—'}}</el-descriptions-item>
            <el-descriptions-item label="Already imported (skipped)">{{importPreview.manifest.duplicates.length}}</el-descriptions-item>
            <el-descriptions-item label="Excluded by owner">{{importPreview.manifest.excluded.length}}</el-descriptions-item>
            <el-descriptions-item label="Owner corrections">{{(importPreview.manifest.corrections||[]).map(c=>c.serial+': '+Object.entries(c.changes).map(([k,v])=>k+' → '+v.after).join(', ')).join('; ')||'—'}}</el-descriptions-item>
          </el-descriptions>
          <el-table :data="Object.entries(importPreview.manifest.totals||{}).map(([currency,t])=>({currency,...t}))" style="margin-top:12px"><el-table-column prop="currency" label="Currency"/><el-table-column prop="count" label="Rows"/><el-table-column label="Net from Cedant"><template #default="{row}">{{number(row.cedantNet)}}</template></el-table-column><el-table-column label="Net to Reinsurer"><template #default="{row}">{{number(row.reinsurerNet)}}</template></el-table-column><el-table-column label="Brokerage"><template #default="{row}">{{number(row.brokerage)}}</template></el-table-column></el-table>
          <el-alert v-if="importPreview.manifest.errors.length" type="error" :closable="false" show-icon :title="importPreview.manifest.errors.length+' row(s) have errors. Correct the Register and preview again.'"/>
          <el-table v-if="importPreview.manifest.errors.length" :data="importPreview.manifest.errors" max-height="260" data-testid="legacy-import-errors"><el-table-column prop="row" label="Row" width="80"/><el-table-column prop="serial" label="Serial" width="120"/><el-table-column prop="message" label="Error"/></el-table>
          <el-alert v-if="importPreview.manifest.warnings.length" type="warning" :closable="false" show-icon :title="importPreview.manifest.warnings.length+' warning(s) block the import. Correct the Register or master data and preview again.'"/>
          <el-table v-if="importPreview.manifest.warnings.length" :data="importPreview.manifest.warnings" max-height="260"><el-table-column prop="row" label="Row" width="80"/><el-table-column prop="serial" label="Serial" width="120"/><el-table-column prop="message" label="Warning"/></el-table>
          <div class="legacy-import-actions"><el-button type="primary" :loading="importing" :disabled="importBlocked" data-testid="legacy-import-commit" @click="commitImport">Import {{importPreview.manifest.eligible}} Transactions</el-button><el-button @click="clearImport">Clear</el-button></div>
        </template>
      </section>
      <h3>Import History</h3>
      <el-collapse><el-collapse-item v-for="b in batches" :key="b.id" :name="b.id" :title="b.filename+' · '+b.status+' · '+b.createdAt"><p>SHA256：{{b.sha256}}</p><pre class="legacy-manifest">{{JSON.stringify(b.manifest,null,2)}}</pre><el-button tag="a" :href="'/api/legacy/imports?download='+encodeURIComponent(b.id)">Download Original File</el-button></el-collapse-item></el-collapse>
    </el-dialog>
  </section>
</template>
<style scoped>
.legacy-page{display:grid;gap:18px}.legacy-toolbar{display:flex;gap:12px;align-items:center}.legacy-toolbar>.el-input{max-width:650px}.el-descriptions,.el-collapse{margin-top:18px}.legacy-manifest{max-height:400px;overflow:auto;white-space:pre-wrap}.legacy-import{display:grid;gap:12px;margin-bottom:18px}.legacy-import h3{margin:0}.legacy-import p{margin:0}.legacy-import-actions{display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap}@media(max-width:700px){.legacy-toolbar{flex-wrap:wrap}}
</style>
