<script setup>
import { cglInformationRows } from '../alpha/cglInformation'
import { formatAmount } from '../alpha/format'
defineProps({ payload: { type: Object, required: true } })
</script>
<template>
  <div class="cgl-information-summary" data-testid="cgl-information-summary">
    <dl><template v-for="row in cglInformationRows(payload)" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></template></dl>
    <h3>Loss Record</h3>
    <dl><dt>Advised by broker on</dt><dd>{{ payload.lossAdvisedDate || '—' }}</dd><dt>Past Year(s)</dt><dd>{{ payload.lossRecordYears ?? '—' }}</dd></dl>
    <p v-if="!payload.lossRecord?.length">Clean — No losses recorded.</p>
    <dl v-for="(row, index) in payload.lossRecord || []" :key="index"><dt>Date of Loss</dt><dd>{{ row.date || '—' }}</dd><dt>Cause</dt><dd>{{ row.cause || '—' }}</dd><dt>Loss Paid</dt><dd>{{ payload.currency }} {{ formatAmount(row.lossPaid) }}</dd></dl>
    <p v-if="payload.lossRecordText" class="notes">{{ payload.lossRecordText }}</p>
    <h3>Special Agreement</h3>
    <p class="notes">{{ payload.cglInformation?.specialAgreementApplies === 'applicable' ? payload.specialAgreement || '—' : payload.cglInformation?.specialAgreementApplies === 'notApplicable' ? 'Not applicable' : '—' }}</p>
  </div>
</template>
<style scoped>
dl { display: grid; grid-template-columns: minmax(150px, 1fr) minmax(0, 2fr); gap: 8px 16px; }
dt { color: var(--muted); }
dd { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.notes { white-space: pre-wrap; overflow-wrap: anywhere; }
@media (max-width: 600px) { dl { grid-template-columns: 1fr; } dd { margin-bottom: 8px; } }
</style>
