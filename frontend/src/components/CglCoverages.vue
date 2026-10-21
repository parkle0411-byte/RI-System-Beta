<script setup>
import { computed } from 'vue'
import { CGL_COVERAGES, cglRiskDetailsIssues } from '../alpha/cglRiskDetails'
const props = defineProps({ payload: { type: Object, required: true }, reviewAttempted: Boolean })
const issues = computed(() => props.reviewAttempted ? cglRiskDetailsIssues(props.payload) : [])
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
      <el-input v-model="payload.coveragesOther" type="textarea" :autosize="{ minRows: 2 }" maxlength="3000" show-word-limit />
    </el-form-item>
  </div>
</template>

<style scoped>
.coverage-options { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; width: 100%; min-width: 0; }
.coverage-options .el-checkbox { height: auto; margin: 0; max-width: 100%; align-items: flex-start; }
.coverage-options :deep(.el-checkbox__input) { margin-top: 3px; }
.coverage-options :deep(.el-checkbox__label) { white-space: normal; overflow-wrap: anywhere; line-height: 1.5; }
small { display: block; width: 100%; }
</style>
