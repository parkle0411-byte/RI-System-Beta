<script setup>
import { computed } from 'vue'
import { ElMessageBox } from 'element-plus'
import { CGL_COVERAGES, cglRiskDetailsIssues, cglMultiOther, cglOtherItems } from '../alpha/cglRiskDetails'
const props = defineProps({ payload: { type: Object, required: true }, reviewAttempted: Boolean })
const issues = computed(() => props.reviewAttempted ? cglRiskDetailsIssues(props.payload) : [])
if (cglMultiOther(props.payload) && !Array.isArray(props.payload.coveragesOtherItems)) props.payload.coveragesOtherItems = cglOtherItems(props.payload)
async function removeOther(i) { try { await ElMessageBox.confirm('Remove this coverage?', 'Remove item', { type: 'warning' }) } catch { return }; props.payload.coveragesOtherItems.splice(i, 1) }
const invalid = key => ({ 'is-required-error': issues.value.some(issue => issue.field === key) })
</script>

<template>
  <div data-testid="cgl-coverages">
    <el-form-item label="Coverages" required :class="invalid('coverages')">
      <el-checkbox-group v-model="payload.coverages" class="coverage-options" aria-label="Coverages">
        <el-checkbox v-for="item in CGL_COVERAGES" :key="item" :value="item">{{ item }}</el-checkbox>
      </el-checkbox-group>
      <small>Select at least one coverage.</small>
    </el-form-item>
    <el-form-item v-if="payload.coverages.includes('Other')" label="Coverages — Other" required :class="invalid('coveragesOther')">
      <template v-if="cglMultiOther(payload)">
        <div v-for="(item, index) in payload.coveragesOtherItems" :key="index" class="coverage-other-row"><el-input v-model="payload.coveragesOtherItems[index]" maxlength="240" @blur="payload.coveragesOtherItems[index] = payload.coveragesOtherItems[index].trim()" /><el-button text type="danger" @click="removeOther(index)">Remove</el-button></div>
        <el-button @click="payload.coveragesOtherItems.push('')">Add coverage</el-button>
      </template>
      <el-input v-else v-model="payload.coveragesOther" type="textarea" :autosize="{ minRows: 2 }" maxlength="3000" show-word-limit />
    </el-form-item>
  </div>
</template>

<style scoped>
.coverage-options { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; width: 100%; min-width: 0; }
.coverage-options .el-checkbox { height: auto; margin: 0; max-width: 100%; align-items: flex-start; }
.coverage-options :deep(.el-checkbox__input) { margin-top: 3px; }
.coverage-options :deep(.el-checkbox__label) { white-space: normal; overflow-wrap: anywhere; line-height: 1.5; }
.coverage-other-row { display: flex; width: 100%; }
small { display: block; width: 100%; }
</style>
