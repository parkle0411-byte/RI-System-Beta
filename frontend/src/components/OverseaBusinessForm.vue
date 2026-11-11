<script setup>
import { computed } from 'vue'
import { overseaPeriods } from '../alpha/oversea'
import { RICaseCalculations } from '../alpha/caseCalculations'
import { formatMoney } from '../alpha/format'
import DraftNumber from './DraftNumber.vue'
import DraftDate from './DraftDate.vue'
const emit = defineEmits(['policy-from-time-change'])
const props = defineProps({payload:{type:Object,required:true},brokers:{type:Array,default:()=>[]},cedants:{type:Array,default:()=>[]},aes:{type:Array,default:()=>[]}})
const periods=computed(()=>overseaPeriods(props.payload))
const addPeriod=()=>{props.payload.performanceInstallments ||= [];props.payload.performanceInstallments.push({id:'I'+Date.now()+'-'+Math.random().toString(36).slice(2,8),ratio:null,premium:null,paymentBaseDate:'',performanceMonth:''})}
function togglePeriods(enabled) {
  props.payload.installmentEnabled=enabled
  if(enabled && !props.payload.performanceInstallments?.length){addPeriod();addPeriod();props.payload.performanceInstallments.forEach(r=>r.ratio=50);props.payload.performanceInstallments[0].paymentBaseDate=props.payload.receiptPaymentDate || ''}
  if(!enabled)props.payload.performanceInstallments=[]
}
</script>
<template>
  <section class="overview-card" data-testid="oversea-business-form">
    <div class="form-grid cols-3">
      <el-form-item label="Insured (EN)" required><el-input v-model="payload.originalInsured" maxlength="240" /></el-form-item>
      <el-form-item label="Insured (CN)" required><el-input v-model="payload.originalInsuredCn" maxlength="240" /></el-form-item>
      <el-form-item label="Account Executive" required><el-select v-model="payload.ae" filterable clearable><el-option v-for="item in aes" :key="item.id" :label="item.name" :value="item.name" /></el-select></el-form-item>
      <el-form-item label="Policy Period" required style="grid-column:1 / -1"><div class="form-grid cols-2" style="width:100%">
        <div><span>Effective Date</span><div class="policy-date-time"><DraftDate v-model="payload.policyFrom" :disabled="!!payload.parentTwRef" type="date" value-format="YYYY-MM-DD" placeholder="YYYY-MM-DD" aria-label="Policy effective date" /><el-select v-model="payload.policyFromTime" :disabled="!!payload.parentTwRef" @change="emit('policy-from-time-change',$event)" aria-label="Policy effective time"><el-option label="12:00" value="12:00" /><el-option label="00:00" value="00:00" /></el-select></div></div>
        <div><span>Expiration Date</span><div class="policy-date-time"><DraftDate v-model="payload.policyTo" :disabled="!!payload.parentTwRef" type="date" value-format="YYYY-MM-DD" placeholder="YYYY-MM-DD" aria-label="Policy expiration date" /><el-select v-model="payload.policyToTime" :disabled="!!payload.parentTwRef" aria-label="Policy expiration time"><el-option label="12:00" value="12:00" /><el-option label="00:00" value="00:00" /></el-select></div></div>
      </div></el-form-item>
      <el-form-item label="100% Premium" required><div style="display:flex;gap:8px;width:100%"><el-select v-model="payload.currency" :disabled="!!payload.parentTwRef" style="width:100px" aria-label="Premium currency"><el-option v-for="c in ['USD','TWD','EUR','JPY','GBP','HKD','MYR']" :key="c" :label="c" :value="c" /></el-select><DraftNumber v-model="payload.originalPremium" :disabled="!!payload.parentTwRef" :min="0" :controls="false" style="flex:1" /></div></el-form-item>
      <el-form-item label="Share (%)" required><DraftNumber v-model="payload.reinsurers[0].sharePct" :disabled="!!payload.parentTwRef" :min="0" :max="100" :precision="8" :controls="false" /></el-form-item>
      <el-form-item :label="payload.parentTwRef ? 'Brokerage Adjustment' : 'Brokerage'" required><DraftNumber v-model="payload.reinsurers[0].brokerageAmount" :controls="false" /></el-form-item>
      <el-form-item label="Reinsurance Broker" required><el-select v-model="payload.reinsurers[0].name" :disabled="!!payload.parentTwRef" filterable clearable><el-option v-for="item in brokers" :key="item.id" :label="item.name" :value="item.name" /></el-select></el-form-item>
      <el-form-item label="Cedant" required><el-select v-model="payload.reinsured" :disabled="!!payload.parentTwRef" filterable clearable><el-option v-for="item in cedants" :key="item.id" :label="item.name" :value="item.name" /></el-select></el-form-item>
      <el-form-item v-if="!payload.installmentEnabled" label="Receipt / Payment Date" required><DraftDate v-model="payload.receiptPaymentDate" type="date" value-format="YYYY-MM-DD" placeholder="YYYY-MM-DD" /></el-form-item>
    </div>
    <section v-if="payload.parentTwRef" data-testid="oversea-endorsement-fields">
      <h3>Endorsement to {{ payload.parentTwRef }}</h3>
      <div class="form-grid cols-2"><el-form-item label="Endorsement Effective Date" required><DraftDate v-model="payload.endoEffectiveDate" type="date" value-format="YYYY-MM-DD" placeholder="YYYY-MM-DD" /></el-form-item><el-form-item label="Endorsement Description" required><el-input v-model="payload.endoText" type="textarea" maxlength="5000" /></el-form-item></div>
      <p class="document-help">Enter this endorsement's Brokerage movement: positive for an additional receipt; negative for a refund.</p>
    </section>
    <section data-testid="oversea-installments">
      <el-switch :model-value="payload.installmentEnabled" @update:model-value="togglePeriods" active-text="Brokerage Installments" />
      <div v-if="payload.installmentEnabled">
        <p>Enter ratios totaling 100%. Each installment has its own actual receipt / payment date. Rounding differences are adjusted in the first installment.</p>
        <div v-for="(row,index) in payload.performanceInstallments" :key="row.id" class="form-grid cols-3" data-testid="oversea-installment-row">
          <el-form-item :label="`Installment ${index+1} Ratio (%)`" required><DraftNumber v-model="row.ratio" :min="0" :max="100" :precision="6" :controls="false" /></el-form-item>
          <el-form-item :label="`Installment ${index+1} Receipt / Payment Date`" required><DraftDate v-model="row.paymentBaseDate" type="date" value-format="YYYY-MM-DD" placeholder="YYYY-MM-DD" /></el-form-item>
          <div><p>Brokerage: {{ formatMoney(periods[index]?.amount,payload.currency) }}</p><p>Accounting Date: {{ periods[index]?.accountingDate || '—' }}</p><el-button @click="payload.performanceInstallments.splice(index,1)">Remove installment {{ index+1 }}</el-button></div>
        </div>
        <el-button @click="addPeriod">Add installment</el-button>
      </div>
    </section>
    <p class="document-help">Brokerage is the T3 amount. Positive amounts are receipts; negative amounts are payments. Accounting Date is 10 calendar days before the actual receipt / payment date.</p>
    <div class="calculation-row leg" data-testid="oversea-t3"><span>T3 Brokerage</span><strong>{{ formatMoney(RICaseCalculations.totals(payload).brokerage,payload.currency) }}</strong></div>
  </section>
</template>

<style scoped>
.policy-date-time { display:flex; gap:8px; min-width:0; margin-top:6px; }
.policy-date-time :deep(.el-date-editor) { flex:1; min-width:0; width:auto; }
.policy-date-time .el-select { width:100px; flex-shrink:0; }
</style>
