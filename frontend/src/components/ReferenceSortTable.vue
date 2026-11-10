<script setup>
import { ref } from 'vue'
import ReferenceSortHandle from './ReferenceSortHandle.vue'

defineOptions({ inheritAttrs: false })
const props = defineProps({ rows: { type: Array, required: true }, disabled: Boolean })
const emit = defineEmits(['reorder'])
const dragging = ref(null)
const over = ref(null)

function reset() { dragging.value = null; over.value = null }
function rowClass({ row, rowIndex }) {
  return `reference-sort-row reference-sort-index-${rowIndex}${row.id === dragging.value ? ' reference-sort-dragging' : ''}${row.id === over.value ? ' reference-sort-over' : ''}`
}
function rowAt(event) {
  const row = event.target.closest('.reference-sort-row')
  if (!row || row.closest('.reference-sort-table') !== event.currentTarget) return null
  const index = /reference-sort-index-(\d+)/.exec(row.className)?.[1]
  return props.rows[Number(index)] || null
}
function dragOver(event) {
  if (props.disabled || dragging.value === null) return
  const row = rowAt(event)
  if (!row) return
  event.preventDefault()
  event.dataTransfer.dropEffect = 'move'
  over.value = row.id
}
function move(id, destination) {
  const source = props.rows.findIndex(row => row.id === id)
  if (props.disabled || source < 0 || destination < 0 || destination >= props.rows.length || source === destination) return
  const next = [...props.rows]
  next.splice(destination, 0, next.splice(source, 1)[0])
  emit('reorder', next)
}
function drop(event) {
  if (dragging.value === null) return
  event.preventDefault()
  const row = rowAt(event)
  if (row) move(dragging.value, props.rows.findIndex(item => item.id === row.id))
  reset()
}
</script>

<template>
  <div class="reference-sort-table" @dragover="dragOver" @drop="drop" @dragend="reset"
    @dragleave="event => { if (!event.currentTarget.contains(event.relatedTarget)) over = null }">
    <el-table :data="rows" row-key="id" :row-class-name="rowClass" v-bind="$attrs">
      <el-table-column label="Order" width="76" align="center">
        <template #default="{ row, $index }">
          <ReferenceSortHandle :label="row.filename" :disabled="disabled || rows.length < 2"
            @start="dragging = row.id" @end="reset" @move="offset => move(row.id, $index + offset)" />
        </template>
      </el-table-column>
      <slot />
    </el-table>
  </div>
</template>

<style scoped>
.reference-sort-table :deep(.reference-sort-dragging) { opacity: .45; }
.reference-sort-table :deep(.reference-sort-over > td) { box-shadow: inset 0 2px #409eff; background: #edf4ff; }
</style>
