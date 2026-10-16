<script setup>
import { computed, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { CGL_CURRENCIES, CGL_POLICY_FORMS, CGL_TERRITORIES, cglInformationIssues } from '../alpha/cglInformation'
import { clientKey } from '../alpha/constants'
import { formatMoneyInput, parseMoneyInput } from '../alpha/format'
const props = defineProps({ payload: { type: Object, required: true }, reviewAttempted: Boolean })
const info = computed(() => props.payload.cglInformation)
const issues = computed(() => props.reviewAttempted ? cglInformationIssues(props.payload) : [])
const invalid = key => ({ 'is-required-error': issues.value.some(issue => issue.field === (key === 'specialAgreement' ? key : 'cglInformation.' + key)) })
const switching = ref(false)
async function changeChoice(key, value) {
  const previous = info.value[key]
  if (previous === value || switching.value) return
  let clear = []
  if (key === 'policyForm') clear = ['retroactiveDate', 'extendedReportingApplies', 'extendedReportingPeriod']
  if (key === 'extendedReportingApplies' && value !== 'applicable') clear = ['extendedReportingPeriod']
  if (key === 'territorialLimits' && value !== 'Other') clear = ['territorialOther']
  const special = key === 'specialAgreementApplies' && value !== 'applicable'
  const needsConfirmation = (key === 'policyForm' && previous) || (key === 'extendedReportingApplies' && previous === 'applicable' && value !== 'applicable')
    || (special && previous === 'applicable') || clear.some(field => info.value[field]) || (special && props.payload.specialAgreement)
  switching.value = true
  try {
    if (needsConfirmation) await ElMessageBox.confirm('Changing this selection will clear the related date, applicability or text. This cannot be undone.', 'Clear related information?', { type: 'warning', confirmButtonText: 'Change and clear', cancelButtonText: 'Keep current selection' })
    clear.forEach(field => { info.value[field] = '' })
    if (special) props.payload.specialAgreement = ''
    info.value[key] = value
  } catch { /* Cancel leaves the selection and all related data intact. */ }
  finally { switching.value = false }
}
function addTurnover() {
  if (info.value.estimatedTurnover.length < 50) info.value.estimatedTurnover.push({ clientKey: clientKey(), region: '', currency: props.payload.currency || '', amount: null })
}
</script>

<template>
  <div data-testid="cgl-information">
    <div class="form-grid cols-2">
      <el-form-item label="Policy Form" required :class="invalid('policyForm')">
        <el-select :model-value="info.policyForm" :disabled="switching" placeholder="Select" @update:model-value="value => changeChoice('policyForm', value)"><el-option v-for="item in CGL_POLICY_FORMS" :key="item" :label="item" :value="item" /></el-select>
      </el-form-item>
      <el-form-item v-if="info.policyForm === 'Claims-Made Form'" label="Retroactive Date" required :class="invalid('retroactiveDate')"><el-date-picker v-model="info.retroactiveDate" type="date" value-format="YYYY-MM-DD" placeholder="YYYY-MM-DD" /></el-form-item>
    </div>
    <template v-if="info.policyForm === 'Claims-Made Form'">
      <el-form-item label="Extended Reporting Period" required :class="invalid('extendedReportingApplies')"><el-select :model-value="info.extendedReportingApplies" :disabled="switching" placeholder="Select" @update:model-value="value => changeChoice('extendedReportingApplies', value)"><el-option label="Not applicable" value="notApplicable" /><el-option label="Applicable" value="applicable" /></el-select></el-form-item>
      <el-form-item v-if="info.extendedReportingApplies === 'applicable'" label="Extended Reporting Period — Period and Description" required :class="invalid('extendedReportingPeriod')"><el-input v-model="info.extendedReportingPeriod" type="textarea" :autosize="{ minRows: 2 }" maxlength="3000" show-word-limit /></el-form-item>
    </template>
    <el-form-item label="Territorial / Jurisdiction Limits" required :class="invalid('territorialLimits')"><el-select :model-value="info.territorialLimits" :disabled="switching" placeholder="Select" @update:model-value="value => changeChoice('territorialLimits', value)"><el-option v-for="item in CGL_TERRITORIES" :key="item" :label="item" :value="item" /></el-select></el-form-item>
    <el-form-item v-if="info.territorialLimits === 'Other'" label="Territorial / Jurisdiction Limits — Other" required :class="invalid('territorialOther')"><el-input v-model="info.territorialOther" type="textarea" :autosize="{ minRows: 2 }" maxlength="3000" show-word-limit /></el-form-item>
    <el-form-item label="Insured’s Business" required :class="invalid('insuredBusiness')"><el-input v-model="info.insuredBusiness" type="textarea" :autosize="{ minRows: 3 }" maxlength="3000" show-word-limit /></el-form-item>
    <el-form-item label="Insured’s Products" required :class="invalid('insuredProducts')"><el-input v-model="info.insuredProducts" type="textarea" :autosize="{ minRows: 3 }" maxlength="3000" show-word-limit /></el-form-item>
    <div class="repeat-heading"><h3>Estimated Turnover <span class="required-star">*</span></h3><el-button class="secondary-button" :disabled="info.estimatedTurnover.length >= 50" @click="addTurnover">+ Add turnover</el-button></div>
    <div v-for="(row, index) in info.estimatedTurnover" :key="row.clientKey" class="repeat-card" data-testid="cgl-turnover-row">
      <div class="repeat-heading"><h4>Turnover {{ index + 1 }}</h4><el-button text type="danger" :disabled="info.estimatedTurnover.length <= 1" @click="info.estimatedTurnover.splice(index, 1)">Remove</el-button></div>
      <div class="form-grid cols-3">
        <el-form-item label="Region" required :class="invalid(`estimatedTurnover.${index}.region`)"><el-input v-model="row.region" maxlength="240" placeholder="e.g. USA/Canada" /></el-form-item>
        <el-form-item label="Currency" required :class="invalid(`estimatedTurnover.${index}.currency`)"><el-select v-model="row.currency" placeholder="Select"><el-option v-for="currency in CGL_CURRENCIES" :key="currency" :label="currency" :value="currency" /></el-select></el-form-item>
        <el-form-item label="Amount" required :class="invalid(`estimatedTurnover.${index}.amount`)"><el-input-number v-model="row.amount" :formatter="formatMoneyInput" :parser="parseMoneyInput" :min="0" :controls="false" /></el-form-item>
      </div>
    </div>
    <p v-if="invalid('estimatedTurnover')['is-required-error']" class="turnover-error">Add at least one Estimated Turnover entry.</p>
    <el-form-item label="Insured’s Website"><el-input v-model="info.insuredWebsite" maxlength="1000" /></el-form-item>
    <h3>Loss Record</h3>
    <slot name="loss" />
    <h3>Special Agreement</h3>
    <el-form-item label="Special Agreement Applicability" required :class="invalid('specialAgreementApplies')"><el-select :model-value="info.specialAgreementApplies" :disabled="switching" placeholder="Select" @update:model-value="value => changeChoice('specialAgreementApplies', value)"><el-option label="Not applicable" value="notApplicable" /><el-option label="Applicable" value="applicable" /></el-select></el-form-item>
    <el-form-item v-if="info.specialAgreementApplies === 'applicable'" label="Special Agreement" required :class="invalid('specialAgreement')"><el-input v-model="payload.specialAgreement" type="textarea" :autosize="{ minRows: 3 }" maxlength="5000" show-word-limit /></el-form-item>
  </div>
</template>
<style scoped>
.el-select, .el-date-editor, .el-input-number { width: 100%; }
.turnover-error { color: var(--el-color-danger); }
</style>
