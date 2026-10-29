<script setup>
import { computed, useAttrs } from 'vue'
defineOptions({ inheritAttrs: false })
const props = defineProps({ modelValue: [String, Number], relaxed: Boolean })
const emit = defineEmits(['update:modelValue', 'change', 'blur'])
const attrs = useAttrs()
const text = computed(() => props.modelValue == null ? '' : String(props.modelValue))
function update(value) {
  // Preserve incomplete signs, decimals and invalid text until formal checks.
  emit('update:modelValue', String(value).replace(/,/g, ''))
}
function commit(event) {
  const value = text.value.trim()
  if (!value) emit('update:modelValue', null)
  else if (Number.isFinite(Number(value))) emit('update:modelValue', Number(value))
  emit('blur',event)
}
</script>

<template>
  <el-input v-if="relaxed" v-bind="attrs" :model-value="text" inputmode="decimal" class="draft-number"
    @update:model-value="update" @change="emit('change', modelValue)" @blur="commit" />
  <el-input-number v-else v-bind="attrs" :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)" @change="emit('change', $event)" @blur="emit('blur', $event)" />
</template>
