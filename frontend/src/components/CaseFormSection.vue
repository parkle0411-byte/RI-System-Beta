<script>
export const SECTION_EDIT_CONTEXT = Symbol('case-section-edit')
</script>
<script setup>
import { computed, defineComponent, h, inject, provide, reactive, toRefs, unref } from 'vue'
import { formContextKey } from 'element-plus'
defineOptions({ inheritAttrs: false })
const props = defineProps({ name: { type: String, required: true }, title: { type: String, required: true }, fixed: Boolean, direct: Boolean })
const editor = inject(SECTION_EDIT_CONTEXT, null)
const guarded = computed(() => Boolean(unref(editor?.guarded)) && !props.direct)
const editing = computed(() => guarded.value && !props.fixed && unref(editor?.active) === props.name)
const locked = computed(() => guarded.value && !editing.value)
const busy = computed(() => Boolean(unref(editor?.busy)))
// The context affects body controls and their teleported popups, not the Edit
// button or collapse header. Keep the existing root Form validation methods.
const FieldGuard = defineComponent({
  props: { disabled: Boolean },
  setup(fieldProps, { slots }) {
    const form = inject(formContextKey, undefined)
    if (form) provide(formContextKey, reactive({ ...toRefs(form), disabled: computed(() => fieldProps.disabled || form.disabled) }))
    return () => h('fieldset', { class: 'case-fieldset', disabled: fieldProps.disabled, inert: fieldProps.disabled, 'aria-disabled': String(fieldProps.disabled) }, slots.default?.())
  }
})
</script>
<template>
  <div class="case-form-section" :class="{ guarded }" :data-testid="'case-section-' + name">
    <div v-if="guarded" class="section-edit-actions">
      <el-tag v-if="fixed" size="small" type="info">Fixed by source</el-tag>
      <el-button v-else size="small" :type="editing ? 'primary' : 'default'" :disabled="busy" :loading="editing && busy" :aria-label="(editing ? 'Done editing ' : 'Edit ') + title" @click.stop="editing ? editor.done() : editor.edit(name)">{{ editing ? 'Done' : 'Edit' }}</el-button>
    </div>
    <el-collapse-item v-bind="$attrs" :name="name" :title="title">
      <FieldGuard :disabled="locked || (guarded && busy)"><slot /></FieldGuard>
    </el-collapse-item>
  </div>
</template>
<style scoped>
.case-form-section { position: relative; min-width: 0; }
.section-edit-actions { position: absolute; right: 34px; top: 15px; z-index: 2; }
.guarded :deep(.el-collapse-item__header) { box-sizing: border-box; height: auto; min-height: 54px; line-height: 1.4; padding-block: 12px; padding-right: 150px; }
.case-fieldset { min-width: 0; padding: 0; margin: 0; border: 0; }
</style>
