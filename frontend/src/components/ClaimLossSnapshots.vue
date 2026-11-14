<script setup>
import { reactive, ref } from 'vue'
import DraftDate from './DraftDate.vue'
import DraftNumber from './DraftNumber.vue'

const props = defineProps({ rows: { type: Array, default: () => [] }, editable: Boolean, canRetry: Boolean, busy: Boolean })
const emit = defineEmits(['save', 'retry'])
const editing = ref(-1)
const form = reactive({ date: '', cause: '', currency: '', lossPaid: null })
function edit(index) {
  const row = props.rows[index]
  Object.assign(form, { date: row.date || '', cause: row.cause || '', currency: row.currency || '', lossPaid: row.lossPaid ?? null })
  editing.value = index
}
function save(index) {
  emit('save', index, { ...form }, () => { editing.value = -1 })
}
function decide(index, field, choice, sync) {
  emit('retry', index, { [field]: { choice, observed: sync.observed ?? '' } })
}
</script>

<template>
  <section v-if="rows.length" class="overview-card" data-testid="renewal-claim-loss-snapshots">
    <h3>Claims from prior policy periods</h3>
    <div v-for="(row, index) in rows" :key="row.sourceCaseUid + ':' + row.claimId" class="repeat-card">
      <div class="repeat-heading"><strong>{{ row.sourceTwRef }} · Claim #{{ row.claimId }}</strong><el-button v-if="editable && editing !== index" :disabled="busy" @click="edit(index)">Edit</el-button></div>
      <div v-if="editing === index" class="form-grid cols-2">
        <el-form-item label="Date of Loss"><DraftDate v-model="form.date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item label="Cause"><el-input v-model="form.cause" maxlength="1000" /></el-form-item>
        <el-form-item label="Currency"><el-select v-model="form.currency"><el-option v-for="currency in ['TWD','USD','EUR','JPY','GBP','HKD','MYR']" :key="currency" :label="currency" :value="currency" /></el-select></el-form-item>
        <el-form-item label="Loss Amount"><DraftNumber v-model="form.lossPaid" :min="0" :controls="false" /></el-form-item>
        <el-button :disabled="busy" @click="editing = -1">Cancel</el-button><el-button type="primary" :loading="busy" @click="save(index)">Save loss detail</el-button>
      </div>
      <p v-else>{{ row.date || '—' }} · {{ row.cause || '—' }} · {{ row.currency || '—' }} {{ row.lossPaid ?? '—' }}</p>
      <template v-for="field in ['date', 'cause']" :key="field">
        <div v-if="row.sync?.[field]?.state === 'pending'" class="document-help">
          {{ field }}: synchronization pending. {{ row.sync[field].message || 'Retry the synchronization.' }}
          <el-button v-if="canRetry" text :disabled="busy" @click="emit('retry', index, {})">Retry</el-button>
        </div>
        <div v-if="row.sync?.[field]?.state === 'conflict'" class="document-help">
          {{ field }} conflict — renewal: {{ row.sync[field].desired || '—' }}; source: {{ row.sync[field].observed || '—' }}.
          <el-button v-if="canRetry" text :disabled="busy" @click="decide(index, field, 'use_renewal', row.sync[field])">Use renewal value</el-button>
          <el-button v-if="canRetry" text :disabled="busy" @click="decide(index, field, 'keep_source', row.sync[field])">Keep source value</el-button>
        </div>
        <div v-if="row.sync?.[field]?.state === 'cancelled'" class="document-help">{{ field }}: synchronization cancelled; renewal value retained.</div>
      </template>
    </div>
  </section>
</template>
