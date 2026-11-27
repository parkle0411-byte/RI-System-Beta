<script setup>
import { watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import DraftNumber from './DraftNumber.vue'
import { clientKey } from '../alpha/constants'
import { orderedRecallRows, RECALL_CURRENCIES, initialRecall } from '../alpha/productRecall'
const props = defineProps({ payload: { type: Object, required: true }, relaxed: Boolean })
watch(() => props.payload.productRecall, risk => {
  if (!risk) return
  const defaults = initialRecall()
  for (const group of ['events', 'losses']) if (!Array.isArray(risk[group])) risk[group] = defaults[group]
  risk.losses.forEach(row => { if (row.selected && !row.currency) { row.currency = props.payload.currency; row.currencyAuto = true } })
}, { immediate: true })
const otherKey = group => group === 'events' ? 'eventsOtherSelected' : 'lossesOtherSelected'
const otherChecked = group => props.payload.productRecall[otherKey(group)] ?? props.payload.productRecall[group].some(r => !r.fixed && r.selected)
function toggleOther(group, enabled) {
  props.payload.productRecall[otherKey(group)] = enabled
  props.payload.productRecall[group].filter(r => !r.fixed).forEach(r => { r.selected = enabled })
}
function toggleFixed(row, selected) {
  row.selected = selected
  if (selected && (!row.currency || (row.currencyAuto === true && (row.amount == null || String(row.amount).trim() === '')))) { row.currency = props.payload.currency; row.currencyAuto = true }
}
function add(group) {
  props.payload.productRecall[group].push({ id: clientKey(), name: '', selected: true, fixed: false, ...(group === 'events' ? {} : { amount: null, currency: props.payload.currency, currencyAuto: true }) })
}
async function remove(group, row) {
  try { await ElMessageBox.confirm('Remove this item and its details?', 'Remove item', { type: 'warning' }) } catch { return }
  const rows = props.payload.productRecall[group]
  rows.splice(rows.indexOf(row), 1)
}
</script>

<template>
  <div v-if="payload.productRecall" data-testid="product-recall-risk">
    <section v-for="group in ['events', 'losses']" :key="group">
      <div class="repeat-heading"><h3>{{ group === 'events' ? 'Covered Events' : 'Covered Loss' }} <span class="required-star" aria-label="required">*</span></h3></div>
      <small v-if="group === 'losses'" class="either-note">Each selected Covered Loss needs a currency and an amount greater than 0.</small>
      <div v-for="row in orderedRecallRows(payload.productRecall[group], group).filter(r => r.fixed)" :key="row.id" class="repeat-row">
        <el-checkbox :model-value="row.selected" @update:model-value="toggleFixed(row, $event)">{{ row.name }}</el-checkbox>
        <template v-if="group === 'losses' && row.selected">
          <el-select v-model="row.currency" placeholder="Currency" @change="row.currencyAuto = false"><el-option v-for="currency in RECALL_CURRENCIES" :key="currency" :label="currency" :value="currency" /></el-select>
          <DraftNumber v-model="row.amount" :relaxed="relaxed" :min="0" :controls="false" />
        </template>
      </div>
      <div class="repeat-row"><el-checkbox :model-value="otherChecked(group)" @update:model-value="toggleOther(group, $event)">Other</el-checkbox></div>
      <template v-if="otherChecked(group)">
        <div v-for="row in payload.productRecall[group].filter(r => !r.fixed)" :key="row.id" class="repeat-row">
          <el-input v-model="row.name" maxlength="240" placeholder="Item name" @blur="row.name = row.name.trim()" />
          <template v-if="group === 'losses'"><el-select v-model="row.currency" placeholder="Currency" @change="row.currencyAuto = false"><el-option v-for="currency in RECALL_CURRENCIES" :key="currency" :label="currency" :value="currency" /></el-select><DraftNumber v-model="row.amount" :relaxed="relaxed" :min="0" :controls="false" /></template>
          <el-button text type="danger" @click="remove(group, row)">Remove</el-button>
        </div>
        <el-button @click="add(group)">Add item</el-button>
      </template>
    </section>
  </div>
</template>
