<script setup>
defineProps({ endorsement: Boolean, documents: Array, coverage: Object, loading: Boolean, saving: Boolean, writable: Boolean, canDelete: Boolean, kind: String, fileList: Array })
const emit = defineEmits(['update:kind', 'file-change', 'file-remove', 'upload', 'select', 'download', 'delete'])
const label = kind => ({ broker_credit: 'RI Broker Credit Note', broker_debit: 'RI Broker Debit Note', offer: 'Other evidence', signed: 'Signed Slip', confirmation: 'Confirmation E-mail' }[kind] || kind)
</script>
<template>
  <section data-testid="oversea-broker-evidence" v-loading="loading">
    <h3>Foreign RI Broker Note</h3>
    <p>{{ endorsement ? 'Upload the Debit Note or Credit Note provided by the foreign RI Broker for this endorsement.' : 'Upload the Credit Note provided by the foreign RI Broker for this Original.' }} Uploaded files are automatically selected.</p>
    <el-form v-if="writable" label-position="top" :disabled="saving">
      <el-form-item label="Broker Note Type">
        <el-select :model-value="kind" @update:model-value="emit('update:kind', $event)">
          <el-option label="Credit Note" value="broker_credit" />
          <el-option v-if="endorsement" label="Debit Note" value="broker_debit" />
        </el-select>
      </el-form-item>
      <el-form-item label="Broker Note File">
        <el-upload action="#" :auto-upload="false" :limit="1" accept=".pdf,.docx,.png,.jpg,.jpeg,.eml,.msg,.xlsx,.xls" :file-list="fileList" :on-change="file => emit('file-change', file)" :on-remove="() => emit('file-remove')">
          <el-button>Select file</el-button>
          <template #tip><div>Maximum 10 MB per file.</div></template>
        </el-upload>
      </el-form-item>
      <el-button type="primary" :loading="saving" @click="emit('upload')">Upload Broker Note</el-button>
    </el-form>
    <el-alert :title="coverage?.ready ? 'RI Broker note selected — ready for Announce review.' : 'Required RI Broker note missing or not selected. Announce is blocked.'" :type="coverage?.ready ? 'success' : 'warning'" :closable="false" />
    <div v-for="file in documents" :key="file.id" class="broker-note-row">
      <el-checkbox v-if="writable" :model-value="file.is_selected" :disabled="saving" :aria-label="'Select ' + file.filename" @change="value => emit('select', file, value)" />
      <strong>{{ label(file.kind) }}</strong> · <el-button link @click="emit('download', file)">{{ file.filename }}</el-button>
      <span v-if="file.contentAvailable === false">File missing</span>
      <el-button v-if="writable && canDelete" link type="danger" :disabled="saving" @click="emit('delete', file)">Delete</el-button>
    </div>
  </section>
</template>
<style scoped>
section { display: grid; gap: 12px; }
h3, p { margin: 0; }
.broker-note-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
</style>
