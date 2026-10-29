<script setup>
import { computed, useAttrs } from 'vue'
defineOptions({ inheritAttrs: false })
const props = defineProps({ modelValue: [String, Date], relaxed: Boolean, type: {type: String, default: 'date'} })
const emit = defineEmits(['update:modelValue', 'change'])
const attrs = useAttrs()
const pickerValue = computed(() => String(props.modelValue || '').match(props.type === 'month' ? /^\d{4}-\d{2}$/ : /^\d{4}-\d{2}-\d{2}$/) ? props.modelValue : '')
function picked(event) {
  emit('update:modelValue',event.target.value)
  emit('change',event.target.value)
}
</script>

<template>
  <el-input v-if="relaxed" v-bind="attrs" :model-value="modelValue || ''" class="el-date-editor draft-date"
    :placeholder="attrs.placeholder || (type === 'month' ? 'YYYY-MM' : 'YYYY-MM-DD')"
    @update:model-value="emit('update:modelValue',$event)" @change="emit('change',$event)">
    <template #append><span class="draft-calendar">▦<input :type="type === 'month' ? 'month' : 'date'" :value="pickerValue" :disabled="attrs.disabled" aria-label="Choose date" @change="picked" /></span></template>
  </el-input>
  <el-date-picker v-else v-bind="attrs" :type="type" :model-value="modelValue" @update:model-value="emit('update:modelValue',$event)" @change="emit('change',$event)" />
</template>

<style scoped>
.draft-calendar { position:relative; display:inline-block; width:20px; text-align:center; }
.draft-calendar input { position:absolute; inset:0; width:100%; opacity:0; cursor:pointer; }
.draft-date { width:100%; }
</style>
