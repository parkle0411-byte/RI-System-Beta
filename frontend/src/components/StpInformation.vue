<script setup>
import { computed } from 'vue'
import DraftNumber from './DraftNumber.vue'
import { sumStpAmounts } from '../alpha/stp'
const props = defineProps({ payload: { type: Object, required: true }, relaxed: Boolean })
const currencies = ['TWD', 'USD', 'EUR', 'JPY', 'GBP', 'HKD', 'MYR']
const hubs = computed(() => props.payload.stpHubs || [])
const turnover = computed(() => props.payload.stpTurnover || [])
function move(rows, index, delta) {
  const target = index + delta
  if (target < 0 || target >= rows.length) return
  const [item] = rows.splice(index, 1)
  rows.splice(target, 0, item)
}
function addHub() { props.payload.stpHubs.push({ name: '', address: '', currency: '', amount: null }) }
function addTurnover() { props.payload.stpTurnover.push({ company: '', currency: '', amount: null }) }
const totals = computed(() => turnover.value.reduce((acc, row) => {
  if (row.currency && row.amount !== null && row.amount !== '' && Number.isFinite(Number(row.amount))) {
    ;(acc[row.currency] ||= []).push(row.amount)
  }
  return acc
}, {}))
</script>

<template>
  <div class="stp-information">
    <el-form-item label="Attachment and Termination"><el-input v-model="payload.attachmentTermination" type="textarea" :rows="2" maxlength="5000" /></el-form-item>
    <el-form-item label="Conveyance" required><el-input v-model="payload.conveyance" type="textarea" :rows="2" maxlength="5000" /></el-form-item>
    <el-form-item label="Voyage" required><el-input v-model="payload.voyage" type="textarea" :rows="2" maxlength="5000" /></el-form-item>
    <el-form-item label="Storage"><el-input v-model="payload.storage" type="textarea" :rows="2" maxlength="5000" /></el-form-item>
    <el-form-item label="Geographical Scope"><el-input v-model="payload.geographicalScope" type="textarea" :rows="2" maxlength="5000" /></el-form-item>
    <el-form-item label="Premium Rate"><el-input v-model="payload.stpPremiumRate" type="textarea" :rows="2" maxlength="5000" /></el-form-item>
    <el-form-item label="Insured’s Website"><el-input v-model="payload.stpWebsite" maxlength="5000" /></el-form-item>
    <section class="stp-list">
      <h3>Estimated Turnover <span aria-label="required">*</span></h3>
      <el-radio-group v-model="payload.stpTurnoverMode">
        <el-radio value="combined">Combined</el-radio><el-radio value="companies">By company</el-radio>
      </el-radio-group>
      <div v-for="(row, index) in turnover" :key="index" class="stp-row">
        <span>{{ index + 1 }}.</span>
        <el-input v-if="payload.stpTurnoverMode === 'companies'" v-model="row.company" maxlength="240" placeholder="Company name *" />
        <el-select v-model="row.currency" placeholder="Currency *"><el-option v-for="c in currencies" :key="c" :label="c" :value="c" /></el-select>
        <DraftNumber :relaxed="relaxed" v-model="row.amount" :min="0" :controls="false" placeholder="Amount > 0 *" />
        <el-button @click="move(payload.stpTurnover,index,-1)" :disabled="index === 0" aria-label="Move up">↑</el-button>
        <el-button @click="move(payload.stpTurnover,index,1)" :disabled="index === turnover.length - 1" aria-label="Move down">↓</el-button>
        <el-button text type="danger" @click="payload.stpTurnover.splice(index,1)">Remove</el-button>
      </div>
      <el-button @click="addTurnover">+ Add turnover</el-button>
      <p v-if="turnover.length > 1" v-for="(total,currency) in totals" :key="currency">{{ currency }} total: {{ sumStpAmounts(total) }}</p>
    </section>
    <section class="stp-list">
      <h3>HUB List <span aria-label="required">*</span></h3>
      <div v-for="(row, index) in hubs" :key="index" class="stp-hub">
        <strong>Location {{ index + 1 }}</strong>
        <el-input v-model="row.name" maxlength="240" placeholder="Location name *" />
        <el-input v-model="row.address" maxlength="500" type="textarea" placeholder="Full address *" />
        <el-select v-model="row.currency" placeholder="Currency *"><el-option v-for="c in currencies" :key="c" :label="c" :value="c" /></el-select>
        <DraftNumber :relaxed="relaxed" v-model="row.amount" :min="0" :controls="false" placeholder="Insured amount > 0 *" />
        <el-button text type="danger" @click="payload.stpHubs.splice(index,1)">Remove</el-button>
      </div>
      <el-button @click="addHub">+ Add location</el-button>
    </section>
  </div>
</template>

<style scoped>
.stp-list { margin-top: 20px; }
.stp-row, .stp-hub { display:flex; gap:8px; align-items:center; margin:8px 0; }
.stp-hub { flex-wrap:wrap; padding:12px; border:1px solid var(--border); border-radius:8px; }
.stp-hub > strong { width:100%; }
@media (max-width: 800px) { .stp-row, .stp-hub { flex-wrap:wrap; } }
</style>
