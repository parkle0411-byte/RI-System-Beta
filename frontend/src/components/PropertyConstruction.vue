<script setup>
import { computed, watch } from 'vue'
import { CONSTRUCTION_OPTIONS, constructionScope, constructionLegacyText, constructionText } from '../alpha/construction'
const props=defineProps({payload:{type:Object,required:true},invalid:Boolean,disabled:Boolean})
const old=computed(()=>constructionLegacyText(props.payload))
watch(()=>[props.payload.constructionSelections,props.payload.constructionLegacyConfirmed,props.payload.classOfBusiness,props.payload.reinsuranceStructure],()=>{
  if(constructionScope(props.payload)) props.payload.construction=constructionText(props.payload)
},{deep:true})
</script>
<template>
  <el-form-item label="Construction" required :class="{'is-required-error':invalid}" data-testid="property-construction" style="min-width:0">
    <template v-if="constructionScope(payload)">
      <el-select :disabled="disabled" v-model="payload.constructionSelections" multiple placeholder="Select construction classes" style="width:100%"><el-option v-for="item in CONSTRUCTION_OPTIONS" :key="item" :value="item" :label="item" /></el-select>
      <div v-if="old.trim()" style="width:100%;margin-top:8px">
        <p style="margin:0 0 6px;white-space:pre-wrap;overflow-wrap:anywhere">Previous Construction: {{ old }}</p>
        <el-checkbox class="construction-confirm" :disabled="disabled" v-model="payload.constructionLegacyConfirmed">I have reviewed the previous text and confirm the new Construction selections.</el-checkbox>
      </div>
    </template>
    <el-input :disabled="disabled" v-else v-model="payload.construction" type="textarea" :rows="3" maxlength="3000" />
  </el-form-item>
</template>

<style scoped>
.construction-confirm { width:100%;height:auto;align-items:flex-start;white-space:normal; }
.construction-confirm :deep(.el-checkbox__label) { white-space:normal;line-height:1.5; }
.construction-confirm :deep(.el-checkbox__input) { margin-top:3px; }
</style>
