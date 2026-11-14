<script setup>
import { ElMessageBox } from 'element-plus'
import DraftNumber from './DraftNumber.vue'
import { clientKey } from '../alpha/constants'
const props = defineProps({ payload: { type: Object, required: true }, relaxed: Boolean })
const add = (group) => props.payload.productRecall[group].push({ id: clientKey(), name: '', selected: true, fixed: false, ...(group === 'events' ? {} : { amount: null }) })
const move = (rows, i, direction) => { const j = i + direction; if (j < 0 || j >= rows.length) return; [rows[i], rows[j]] = [rows[j], rows[i]] }
async function remove(rows, i) {
  if (rows[i].amount != null && String(rows[i].amount) !== '') {
    try { await ElMessageBox.confirm('Remove this item and its amount?', 'Remove item', { type: 'warning' }) } catch { return }
  }
  rows.splice(i, 1)
}
</script>

<template>
  <div v-if="payload.productRecall" data-testid="product-recall-risk">
    <section v-for="group in ['events', 'losses']" :key="group">
      <div class="repeat-heading"><h3>{{ group === 'events' ? 'Covered Events' : 'Covered Loss' }}</h3><el-button @click="add(group)">Add item</el-button></div>
      <div v-for="(row, i) in payload.productRecall[group]" :key="row.id" class="repeat-row">
        <el-checkbox v-model="row.selected" :aria-label="`Select ${row.name || 'item'}`" />
        <span v-if="row.fixed">{{ row.name }}</span><el-input v-else v-model="row.name" maxlength="240" placeholder="Item name" />
        <template v-if="group === 'losses' && row.selected"><span>{{ payload.currency }}</span><DraftNumber v-model="row.amount" :relaxed="relaxed" :min="0" :controls="false" /></template>
        <el-button :disabled="i === 0" @click="move(payload.productRecall[group], i, -1)">↑</el-button>
        <el-button :disabled="i === payload.productRecall[group].length - 1" @click="move(payload.productRecall[group], i, 1)">↓</el-button>
        <el-button v-if="!row.fixed" text type="danger" @click="remove(payload.productRecall[group], i)">Remove</el-button>
      </div>
    </section>
    <section>
      <div class="repeat-heading"><h3>Additional Sub-limits</h3><el-button @click="add('additionalSublimits')">Add sub-limit</el-button></div>
      <div v-for="(row, i) in payload.productRecall.additionalSublimits" :key="row.id" class="repeat-row">
        <el-input v-model="row.name" maxlength="240" placeholder="Item name" /><span>{{ payload.currency }}</span><DraftNumber v-model="row.amount" :relaxed="relaxed" :min="0" :controls="false" />
        <el-button :disabled="i === 0" @click="move(payload.productRecall.additionalSublimits, i, -1)">↑</el-button>
        <el-button :disabled="i === payload.productRecall.additionalSublimits.length - 1" @click="move(payload.productRecall.additionalSublimits, i, 1)">↓</el-button>
        <el-button text type="danger" @click="remove(payload.productRecall.additionalSublimits, i)">Remove</el-button>
      </div>
    </section>
  </div>
</template>
