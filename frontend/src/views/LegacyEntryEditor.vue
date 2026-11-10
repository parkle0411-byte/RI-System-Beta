<script setup>
import {computed,ref,watch} from 'vue'
import {api} from '../api'
import {premiumMoney} from '../alpha/lib/accounting'
const props=defineProps({transaction:Object,options:Object})
const emit=defineEmits(['saved','close'])
const current=ref(null),form=ref({}),busy=ref(false),error=ref('')
const inputKeys=['reference','currency','revenueMonth','kind','insured','insuredCn','cedant','party','statementNo','reinsurerRef','effectiveDate','lossDate','claimNote','gross','share','commissionRate','taxRate','brokerage','claim','claimReason','brokerageNote','ae','subAe','aePct','rule','cedantDays','reinsurerDays','endorsementNo','installmentNo','newRenew','remark','oldReason','oldReasonText']
watch(()=>props.transaction,t=>{if(t){current.value=t;form.value=JSON.parse(JSON.stringify(t.data));error.value=''}},{immediate:true})
watch(()=>form.value.rule,rule=>{if(rule && rule!=='ordinary')form.value.cedantDays=90})
watch(()=>form.value.party,(name,previous)=>{
 if(previous==null || name===previous)return
 const normalized=v=>String(v||'').trim().replace(/\s+/g,' ').toLowerCase()
 const rule=props.options.rules.find(r=>normalized(r.label)===normalized(name))
 if(rule)form.value.rule=rule.code
 else if(props.options.parties.some(p=>p.entity_type==='reinsurer' && normalized(p.name)===normalized(name)))form.value.rule='ordinary'
 else form.value.rule=''
})
const claim=computed(()=>form.value.kind==='claim')
const texts={reference:'Old Reference',insured:'Insured (English)',insuredCn:'Insured (Chinese)',statementNo:'Statement No.',reinsurerRef:"Reinsurer's Ref. No.",installmentNo:'Installment No.'}
const amounts=computed(()=>{
 const d=form.value,r=v=>premiumMoney(Number(v),d)
 if(claim.value)return {Claim:d.claim,'Receivable / Payable':d.claim}
 const p=r(r(d.gross)*Number(d.share)/100),c=r(p*Number(d.commissionRate)/100),t=r(p*Number(d.taxRate)/100),b=r(d.brokerage)
 return {'Our Share Premium':p,'R/I Comm.':c,Tax:t,'Bkg.(%)':p?b/p*100:b>0?100:b<0?-100:null,'Net Premium from Cedant':r(p-c-t),'Net Premium to Reinsurer':r(p-c-t-b)}
})
async function save(confirm=false){
 busy.value=true;error.value=''
 try{
  const data=Object.fromEntries(inputKeys.filter(k=>k in form.value).map(k=>[k,form.value[k]]))
  let t=await api('/api/legacy',{method:'PATCH',body:{id:current.value.uid,version:current.value.version,action:'save',data}})
  current.value=t
  if(confirm)t=await api('/api/legacy',{method:'PATCH',body:{id:t.uid,version:t.version,action:'confirm'}})
  current.value=t;emit('saved',t)
  if(confirm)emit('close')
 }catch(e){error.value=e.message}finally{busy.value=false}
}
</script>
<template>
 <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon/>
 <el-alert title="Only the draft owner can edit and confirm. Confirmation creates Accounting accounts." type="info" :closable="false"/>
 <el-form v-if="current" label-position="top" class="entry-form" :disabled="busy">
  <el-form-item label="Source Old Reference"><el-input :model-value="form.sourceReference" disabled/></el-form-item>
  <el-form-item label="Transaction Type"><el-input :model-value="claim?'Claim':'Endorsement'" disabled/></el-form-item>
  <el-form-item v-for="(label,key) in texts" :key="key" :label="label"><el-input v-model="form[key]" :maxlength="key==='reference'?192:240"/></el-form-item>
  <el-form-item label="Cedant"><el-select v-model="form.cedant" filterable allow-create default-first-option><el-option v-for="p in options.parties.filter(p=>p.entity_type==='reinsured')" :key="p.name" :label="p.name" :value="p.name"/></el-select></el-form-item>
  <el-form-item label="Settlement Party"><el-select v-model="form.party" filterable allow-create default-first-option><el-option v-for="p in options.parties.filter(p=>p.entity_type!=='reinsured')" :key="p.entity_type+p.name" :label="p.name" :value="p.name"/></el-select></el-form-item>
  <el-form-item label="Currency"><el-select v-model="form.currency"><el-option v-for="c in ['TWD','USD','MYR','EUR','JPY','GBP','HKD']" :key="c" :label="c" :value="c"/></el-select></el-form-item>
  <el-form-item label="Effective Date"><el-date-picker v-model="form.effectiveDate" :disabled="claim" value-format="YYYY-MM-DD"/></el-form-item>
  <el-form-item label="Expiry Date (Source)"><el-input :model-value="form.expiryDate" disabled/></el-form-item>
  <template v-if="claim">
   <el-form-item label="DOL"><el-date-picker v-model="form.lossDate" value-format="YYYY-MM-DD"/></el-form-item>
   <el-form-item label="Claim Amount (Our Share)"><el-input-number v-model="form.claim" :controls="false" :precision="2"/></el-form-item>
   <el-form-item label="Negative Claim Reason"><el-input v-model="form.claimReason" type="textarea"/></el-form-item>
   <el-form-item label="Note for Claim"><el-input v-model="form.claimNote" type="textarea"/></el-form-item>
  </template>
  <template v-else>
   <el-form-item label="Endorsement No."><el-input v-model="form.endorsementNo"/></el-form-item>
   <el-form-item label="100% Premium (This Endorsement Adjustment)"><el-input-number v-model="form.gross" :controls="false"/></el-form-item>
   <el-form-item label="Share (%)"><el-input-number v-model="form.share" :controls="false"/></el-form-item>
   <el-form-item label="R/I Commission (%)"><el-input-number v-model="form.commissionRate" :controls="false"/></el-form-item>
   <el-form-item label="Tax (%)"><el-input-number v-model="form.taxRate" :controls="false"/></el-form-item>
   <el-form-item label="Brokerage Amount (Original Currency)"><el-input-number v-model="form.brokerage" :controls="false"/></el-form-item>
   <el-form-item label="Note for Bkg."><el-input v-model="form.brokerageNote" type="textarea"/></el-form-item>
   <el-form-item label="Revenue Month"><el-date-picker v-model="form.revenueMonth" type="month" value-format="YYYY-MM" placeholder="Select an unclosed month"/></el-form-item>
   <el-form-item label="Endorsement Over 5 Years After Expiry — Reason"><el-select v-model="form.oldReason" clearable><el-option v-for="r in options.reasons.filter(r=>r.active!==false)" :key="r.code" :label="r.label" :value="r.code"/></el-select></el-form-item>
   <el-form-item label="Reason Details"><el-input v-model="form.oldReasonText" type="textarea"/></el-form-item>
  </template>
  <el-form-item label="AE"><el-select v-model="form.ae" filterable><el-option v-for="p in options.people" :key="p.id" :label="p.name" :value="p.name"/></el-select><small>Source AE: {{form.sourceAe||'—'}}</small></el-form-item>
  <template v-if="!claim">
   <el-form-item label="Sub AE"><el-select v-model="form.subAe" filterable clearable><el-option v-for="p in options.people" :key="p.id" :label="p.name" :value="p.name"/></el-select></el-form-item>
   <el-form-item v-if="form.subAe" label="AE / Sub AE Split"><el-select v-model="form.aePct"><el-option label="40 / 60" :value="40"/><el-option label="70 / 30" :value="70"/></el-select></el-form-item>
  </template>
  <el-form-item label="Payment Rule"><el-select v-model="form.rule" placeholder="Awaiting Payment Rule"><el-option v-for="r in options.rules" :key="r.code" :label="r.label" :value="r.code"/></el-select></el-form-item>
  <el-form-item v-if="!claim" label="Cedant Terms (Days)"><el-input-number v-model="form.cedantDays" :disabled="form.rule!=='ordinary'" :min="15" :precision="0"/></el-form-item>
  <el-form-item v-if="!claim && form.rule==='ordinary'" label="Reinsurer Terms (Days)"><el-input-number v-model="form.reinsurerDays" :min="15" :precision="0"/></el-form-item>
  <el-form-item label="Remark"><el-input v-model="form.remark" type="textarea"/></el-form-item>
 </el-form>
 <el-descriptions title="Calculated Amounts" :column="2" border><el-descriptions-item v-for="(v,k) in amounts" :key="k" :label="k">{{Number.isFinite(v)?new Intl.NumberFormat('en-US',{maximumFractionDigits:8}).format(v):'—'}}</el-descriptions-item></el-descriptions>
 <div class="entry-actions"><el-button :loading="busy" @click="save(false)">Save Draft</el-button><el-button type="primary" :loading="busy" @click="save(true)">Confirm Transaction</el-button><el-button :disabled="busy" @click="emit('close')">Close</el-button></div>
</template>
<style scoped>.entry-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 20px;margin-top:18px}.el-select,.el-input-number,.el-date-editor{width:100%}.entry-actions{display:flex;gap:12px;margin-top:20px}small{display:block;color:var(--el-text-color-secondary)}@media(max-width:700px){.entry-form{grid-template-columns:1fr}}</style>
