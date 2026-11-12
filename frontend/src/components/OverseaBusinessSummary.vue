<script setup>
import { overseaDates, overseaPeriods } from '../alpha/oversea'
import { RICaseCalculations } from '../alpha/caseCalculations'
import { formatMoney, formatPolicyPeriod } from '../alpha/format'
defineProps({payload:{type:Object,required:true}})
</script>
<template><section class="overview-card" data-testid="oversea-business-summary"><h2>Oversea Business</h2><dl class="overview-kv">
<dt>Class</dt><dd>{{ payload.classOfBusiness || '—' }}</dd>
<dt>Insured (EN)</dt><dd>{{ payload.originalInsured || '—' }}</dd>
<dt>Insured (CN)</dt><dd>{{ payload.originalInsuredCn || '—' }}</dd>
<dt>Policy Period</dt><dd>{{ formatPolicyPeriod(payload) }}</dd>
<dt>Account Executive</dt><dd>{{ payload.ae || '—' }}</dd>
<dt>100% Premium</dt><dd>{{ payload.currency }} {{ formatMoney(payload.originalPremium,payload.currency) }}</dd>
<template v-if="payload.parentTwRef && payload.premiumAdjustment != null"><dt>100% Premium Adjustment</dt><dd>{{ payload.currency }} {{ formatMoney(payload.premiumAdjustment,payload.currency) }}</dd></template>
<dt>Share (%)</dt><dd>{{ payload.reinsurers?.[0]?.sharePct ?? '—' }}</dd>
<dt>Brokerage</dt><dd>{{ payload.reinsurers?.[0]?.brokerageAmount ?? '—' }}</dd>
<dt>Reinsurance Broker</dt><dd>{{ payload.reinsurers?.[0]?.name || '—' }}</dd>
<dt>Cedant</dt><dd>{{ payload.reinsured || '—' }}</dd>
<dt v-if="!payload.installmentEnabled">Receipt / Payment Date</dt><dd v-if="!payload.installmentEnabled">{{ payload.receiptPaymentDate || '—' }}</dd>
<dt v-if="!payload.installmentEnabled">Accounting Date</dt><dd v-if="!payload.installmentEnabled">{{ overseaDates(payload).accountingDate || '—' }}</dd>
<dt>T3 Brokerage</dt><dd>{{ payload.currency }} {{ formatMoney(RICaseCalculations.totals(payload).brokerage,payload.currency) }}</dd>
</dl>
<div v-if="payload.parentTwRef"><p>Endorsement to {{ payload.parentTwRef }} · {{ payload.endoEffectiveDate }}</p><p>{{ payload.endoText }}</p></div>
<div v-if="payload.installmentEnabled" class="overview-table-wrap"><table class="overview-table" data-testid="oversea-installment-summary"><thead><tr><th>Installment</th><th>Ratio (%)</th><th>Brokerage</th><th>Receipt / Payment Date</th><th>Accounting Date</th></tr></thead><tbody><tr v-for="row in overseaPeriods(payload)" :key="row.id"><td>{{ row.label }}</td><td>{{ row.ratio }}</td><td>{{ formatMoney(row.amount,payload.currency) }}</td><td>{{ row.actualPaymentDate }}</td><td>{{ row.accountingDate }}</td></tr></tbody></table></div>
</section></template>
