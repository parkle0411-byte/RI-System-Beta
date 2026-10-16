<script setup>
defineProps({ combined: Boolean })
const sections = [
  { name: 'occupation', title: 'Occupation & Construction' },
  { name: 'sumInsured', title: 'Breakdown of Sum Insured' },
  { name: 'loss', title: 'Loss Record' },
  { name: 'specialAgreement', title: 'Special Agreement' },
]
</script>

<template>
  <el-collapse-item v-if="combined" name="information" title="Information" data-testid="property-information">
    <section v-for="section in sections" :key="section.name" class="information-section" :data-section="section.name">
      <h3>{{ section.title }}</h3>
      <slot :name="section.name" />
    </section>
  </el-collapse-item>
  <template v-else>
    <el-collapse-item v-for="section in sections" :key="section.name" :name="section.name" :title="section.title">
      <slot :name="section.name" />
    </el-collapse-item>
  </template>
</template>

<style scoped>
.information-section + .information-section { margin-top: 24px; }
.information-section > h3 { margin: 0 0 16px; }
</style>
