<script setup>
defineProps({
  files: { type: Array, default: () => [] },
  history: { type: Array, default: () => [] },
  issues: { type: Array, default: () => [] },
  busy: Boolean,
  formatDate: { type: Function, required: true },
  formatSize: { type: Function, required: true },
})
defineEmits(['download'])
const label = kind => kind === 'generated_cover' ? 'Cover Note' : 'Debit Note'
</script>

<template>
  <section class="overview-card" data-testid="generated-word-documents">
    <div class="section-heading">
      <div><h2>Generated Word documents</h2><p>Latest Cover Note and Debit Note. Previous versions remain available below.</p></div>
    </div>
    <el-alert v-if="issues.length" type="warning" :closable="false" show-icon title="Complete the following document data before generating Word.">
      <ul data-testid="document-generation-issues"><li v-for="(issue, index) in issues" :key="issue.field + ':' + index">{{ issue.message }}</li></ul>
    </el-alert>
    <el-table :data="files" empty-text="No generated Word documents saved yet." row-key="id" class="document-table" data-testid="generated-word-latest">
      <el-table-column label="Document" min-width="270"><template #default="{ row }"><div class="document-name"><strong>{{ row.filename }}</strong><span>{{ label(row.kind) }} · Version {{ row.version }} · {{ formatSize(row.byte_size) }}</span></div></template></el-table-column>
      <el-table-column label="Generated" min-width="175"><template #default="{ row }">{{ formatDate(row.uploaded_at) }}</template></el-table-column>
      <el-table-column label="Action" width="120"><template #default="{ row }"><el-button text :disabled="busy" @click="$emit('download', row)">Download</el-button></template></el-table-column>
    </el-table>
    <el-collapse v-if="history.length" style="margin-top:12px">
      <el-collapse-item :title="'Previous versions (' + history.length + ')'" name="generated-history">
        <el-table :data="history" row-key="id" class="document-table" data-testid="generated-word-history">
          <el-table-column label="Document" min-width="270"><template #default="{ row }"><div class="document-name"><strong>{{ row.filename }}</strong><span>{{ label(row.kind) }} · Version {{ row.version }} · {{ formatSize(row.byte_size) }}</span></div></template></el-table-column>
          <el-table-column label="Generated" min-width="175"><template #default="{ row }">{{ formatDate(row.uploaded_at) }}</template></el-table-column>
          <el-table-column label="Action" width="120"><template #default="{ row }"><el-button text :disabled="busy" @click="$emit('download', row)">Download</el-button></template></el-table-column>
        </el-table>
      </el-collapse-item>
    </el-collapse>
    <p class="document-help">Generated Word files and their history do not use the 50 manually uploaded evidence slots.</p>
  </section>
</template>
