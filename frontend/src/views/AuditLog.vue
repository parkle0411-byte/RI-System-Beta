<script setup>
// 移植自 Alpha index.html 的 activeView === 'audit' 與 app.js 的 loadAuditLog()。
// VM：說明文字改為如實描述（VM 已啟用 Audit，Alpha 是暫停中）。
import { onMounted, ref } from 'vue'
import { apiFetch } from '../api'
import { formatDateTime } from '../alpha/format'
import { shell } from '../alpha/shell'

const auditLoading = ref(false)
const auditEvents = ref([])

async function loadAuditLog() {
  auditLoading.value = true
  shell.error = ''
  try {
    const response = await apiFetch('/api/audit-log?limit=250', { headers: { Accept: 'application/json' } })
    const body = await response.json()
    if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
    auditEvents.value = Array.isArray(body.events) ? body.events : []
  } catch (err) {
    shell.error = err instanceof Error ? err.message : String(err)
  } finally {
    auditLoading.value = false
  }
}
onMounted(loadAuditLog)
</script>

<template>
  <section class="table-card" v-loading="auditLoading">
    <div class="section-heading"><div><h2>Audit events</h2><p>Append-only on the company VM: recorded with every change and retained for at least 20 years. The latest 250 events are shown.</p></div><el-button class="secondary-button" :loading="auditLoading" @click="loadAuditLog">Refresh</el-button></div>
    <el-table :data="auditEvents" class="case-table" row-key="id" empty-text="No audit events yet.">
      <el-table-column prop="occurred_at" label="Occurred" min-width="180"><template #default="{ row }">{{ formatDateTime(row.occurred_at) }}</template></el-table-column>
      <el-table-column prop="entity_type" label="Entity" min-width="150"></el-table-column>
      <el-table-column prop="entity_id" label="Entity ID" min-width="180"></el-table-column>
      <el-table-column prop="action" label="Action" min-width="190"></el-table-column>
      <el-table-column prop="actor_name" label="Actor" min-width="180"><template #default="{ row }">{{ row.actor_name || row.actor_id }}</template></el-table-column>
      <el-table-column prop="actor_role" label="Role" width="140"></el-table-column>
      <el-table-column prop="retention_until" label="Retained until" min-width="180"><template #default="{ row }">{{ formatDateTime(row.retention_until) }}</template></el-table-column>
    </el-table>
  </section>
</template>
