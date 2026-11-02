<script setup>
defineProps({ modelValue: Boolean, groups: { type: Array, default: () => [] }, common: { type: Array, default: () => [] }, clauseHint: Boolean })
const emit = defineEmits(['update:modelValue'])
</script>
<template>
  <el-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)" title="Facility Rules" width="min(760px, 94vw)" destroy-on-close class="facility-rules-dialog">
    <div data-testid="facility-rules-content" class="facility-rules-content">
      <section v-if="common.length"><h3>Case payment terms</h3><p v-for="text in common" :key="text">{{ text }}</p></section>
      <section v-for="group in groups" :key="group.name" data-testid="facility-rule-group"><h3>{{ group.name }}</h3><p v-for="text in group.notes" :key="text">{{ text }}</p></section>
      <p v-if="clauseHint">Facility Clause Rules (Case-specific clauses can be added after at least one non-Facility reinsurer is selected.)</p>
    </div>
    <template #footer><el-button @click="emit('update:modelValue', false)">Close</el-button></template>
  </el-dialog>
</template>
<style scoped>
.facility-rules-content { display: grid; gap: 16px; max-height: 65vh; overflow-y: auto; overflow-wrap: anywhere; }
h3 { margin: 0 0 8px; font-size: 14px; }
p { margin: 6px 0; line-height: 1.5; }
</style>
