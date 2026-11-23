<script setup>
defineProps({ payload: { type: Object, required: true } })
const fields = [ ['newOrRenew','New / Renew'], ['ownerPersonnelName','Case Owner'], ['ae','Account Executive'], ['currency','Currency'],
  ['type','Type'], ['reinsured','Reinsured'], ['reinsuredLocation','Reinsured Location'],
  ['originalAssuredDescription','Original Assured'], ['policyFrom','Period From'], ['policyTo','Period To'],
  ['periodConditions','Period Conditions'], ['interest','Interest'], ['coverageLimits','Coverage / Limits'],
  ['eventLimit','Event Limit'], ['reinsuredRetention','Retention'], ['territorialScope','Territorial Scope'],
  ['conditions','Conditions'], ['exclusions','Exclusions'], ['expressWarranties','Express Warranties'],
  ['conditionsPrecedent','Conditions Precedent'], ['subjectivities','Subjectivities'], ['choiceOfLaw','Choice of Law and Jurisdiction'],
  ['premiumRates','Premium Rates'], ['premiumPaymentTerms','Premium Payment Terms'], ['bordereaux','Bordereaux'],
  ['accounts','Accounts'], ['cashLossLimit','Cash Loss Limit'], ['taxesText','Taxes'], ['recordingText','Recording and Contract Document'],
  ['facilityInformation','Information'], ['riCommPct','Cedant R/I Comm (%)'], ['taxPct','Cedant Tax (%)'], ['ppwDays','PPW (days)'] ]
</script>
<template>
  <section class="overview-card" data-testid="facility-summary">
    <h2>{{ payload.facilityName || 'Facility' }}</h2>
    <dl class="detail-list"><template v-for="[key, label] in fields" :key="key"><dt>{{ label }}</dt><dd style="white-space: pre-wrap">{{ payload[key] ?? '—' }}</dd></template></dl>
    <h3>Security Details</h3>
    <el-table :data="payload.reinsurers || []"><el-table-column prop="name" label="Reinsurer" /><el-table-column prop="sharePct" label="Share (%)" /><el-table-column prop="deductionPct" label="Deduction (%)" /><el-table-column prop="taxPct" label="Tax (%)" /><el-table-column prop="facilityReference" label="Reinsurer’s Ref. No." /></el-table>
  </section>
</template>
