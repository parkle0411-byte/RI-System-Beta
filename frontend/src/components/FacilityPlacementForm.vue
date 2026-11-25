<script setup>
import { ALL_CURRENCIES } from '../alpha/currencies'
const props = defineProps({ draft: { type: Object, required: true }, reinsuredOptions: { type: Array, default: () => [] }, reinsurerOptions: { type: Array, default: () => [] }, personnel: { type: Array, default: () => [] } })
const emit = defineEmits(['owner-change', 'ae-change'])
const textFields = [
  ['periodConditions', 'Period Conditions'], ['interest', 'Interest'], ['coverageLimits', 'Coverage / Limits'],
  ['eventLimit', 'Event Limit'], ['reinsuredRetention', 'Retention'], ['territorialScope', 'Territorial Scope'],
  ['conditions', 'Conditions'], ['exclusions', 'Exclusions'], ['expressWarranties', 'Express Warranties'],
  ['conditionsPrecedent', 'Conditions Precedent'], ['subjectivities', 'Subjectivities'],
  ['choiceOfLaw', 'Choice of Law and Jurisdiction'], ['premiumRates', 'Premium Rates'],
  ['premiumPaymentTerms', 'Premium Payment Terms'], ['bordereaux', 'Bordereaux'], ['accounts', 'Accounts'],
  ['cashLossLimit', 'Cash Loss Limit'], ['recordingText', 'Recording and Contract Document'],
  ['facilityInformation', 'Information']
]
function addReinsurer() { props.draft.reinsurers.push({ name: '', sharePct: '', deductionPct: '', facilityReference: '' }) }
function removeReinsurer(index) { props.draft.reinsurers.splice(index, 1) }
</script>

<template>
  <section class="overview-card" data-testid="facility-placement-form">
    <div class="section-heading"><h2>Facility Placement</h2></div>
    <div class="form-grid cols-2">
      <el-form-item label="Facility Name" required><el-input v-model="draft.facilityName" maxlength="240" /></el-form-item>
      <el-form-item label="Currency" required><el-select v-model="draft.currency" clearable><el-option v-for="c in ALL_CURRENCIES" :key="c" :label="c" :value="c" /></el-select></el-form-item>
      <el-form-item label="Case Owner" required><el-select v-model="draft.ownerPersonnelId" filterable @change="emit('owner-change', $event)"><el-option v-for="person in personnel" :key="person.id" :label="person.name" :value="person.id" /></el-select></el-form-item>
      <el-form-item label="Account Executive" required><el-select v-model="draft.aePersonnelId" filterable @change="emit('ae-change', $event)"><el-option v-for="person in personnel" :key="person.id" :label="person.name" :value="person.id" /></el-select></el-form-item>
      <el-form-item label="New / Renew"><el-select v-model="draft.newOrRenew"><el-option label="New" value="New" /><el-option label="Renew" value="Renew" /></el-select></el-form-item>
      <el-form-item label="Type"><el-input v-model="draft.facilityTypePrefix" placeholder="Enter prefix"><template #append>{{ draft.classOfBusiness }} Facultative Facility Reinsurance</template></el-input></el-form-item>
      <el-form-item label="Reinsured" required><el-select v-model="draft.reinsured" filterable clearable><el-option v-for="item in reinsuredOptions" :key="item.id" :label="item.name" :value="item.name" /></el-select></el-form-item>
      <el-form-item label="Reinsured Location"><el-input v-model="draft.reinsuredLocation" type="textarea" /></el-form-item>
      <el-form-item label="Original Insured" required><el-input v-model="draft.originalAssuredDescription" type="textarea" /></el-form-item>
    </div>
    <div class="form-grid cols-2 facility-period">
      <el-form-item label="Period From" required><el-date-picker v-model="draft.policyFrom" type="date" value-format="YYYY-MM-DD" /><small>Changing the start date also updates the first Declaration. Closed accounting is corrected by reversal and replacement.</small></el-form-item>
      <el-form-item label="Period To" required><el-date-picker v-model="draft.policyTo" type="date" value-format="YYYY-MM-DD" /></el-form-item>
    </div>
    <div v-for="[key, label] in textFields" :key="key"><el-form-item :label="label"><el-input v-model="draft[key]" type="textarea" :autosize="{minRows: 2}" /></el-form-item></div>
    <div class="form-grid cols-2">
      <el-form-item label="Cedant R/I Comm (%)"><el-input v-model="draft.riCommPct" inputmode="decimal" /></el-form-item>
      <el-form-item label="PPW (days)"><el-input v-model="draft.ppwDays" inputmode="numeric" /></el-form-item>
      <el-form-item label="Cedant Tax (%)"><el-input v-model="draft.taxPct" inputmode="decimal" /></el-form-item>
    </div>
    <h3>Security Details</h3>
    <div v-for="(row, index) in draft.reinsurers" :key="index" class="form-grid cols-4">
      <el-form-item label="Reinsurer" required><el-select v-model="row.name" filterable clearable><el-option v-for="item in reinsurerOptions" :key="item.id" :label="item.name" :value="item.name" /></el-select></el-form-item>
      <el-form-item label="Share (%)" required><el-input v-model="row.sharePct" inputmode="decimal" /></el-form-item>
      <el-form-item label="Deduction (%)" required><el-input v-model="row.deductionPct" inputmode="decimal" /></el-form-item>
      <el-form-item label="Reinsurer Tax (%)" required><el-input v-model="row.taxPct" inputmode="decimal" /></el-form-item>
      <el-form-item label="Reinsurer’s Ref. No." required><el-input v-model="row.facilityReference" /><el-button text @click="removeReinsurer(index)">Remove</el-button></el-form-item>
    </div>
    <el-button @click="addReinsurer">Add Reinsurer</el-button>
  </section>
</template>

<style scoped>
.form-grid.facility-period { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.facility-period :deep(.el-date-editor.el-input) { width: 100%; min-width: 0; }
</style>
