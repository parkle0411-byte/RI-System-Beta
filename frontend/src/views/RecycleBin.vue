<script setup>
// 移植自 Alpha index.html 的 activeView === 'recycle' 與 app.js 的 loadRecycleBin()／restoreDraft()。
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiFetch } from '../api'
import { can } from '../auth'
import { formatDateTime, jsonOrThrow, reportWriteError } from '../alpha/format'
import { shell } from '../alpha/shell'

const recycleLoading = ref(false)
const recycleSaving = ref(false)
const recycleItems = ref([])
const recyclePolicy = ref({ retentionYears: 5, permanentDeleteAllowed: false })

async function loadRecycleBin() {
  recycleLoading.value = true
  shell.error = ''
  try {
    const response = await apiFetch('/api/draft-recycle-bin', { headers: { Accept: 'application/json' } })
    const body = await response.json()
    if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
    recycleItems.value = Array.isArray(body.items) ? body.items : []
    recyclePolicy.value = { retentionYears: Number(body.retentionYears || 5), permanentDeleteAllowed: body.permanentDeleteAllowed === true }
  } catch (err) {
    shell.error = err instanceof Error ? err.message : String(err)
  } finally {
    recycleLoading.value = false
  }
}

async function restoreDraft(row) {
  recycleSaving.value = true
  try {
    await jsonOrThrow(await apiFetch('/api/draft-recycle-bin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ action: 'restore', recycleId: Number(row.id) })
    }))
    ElMessage.success('Draft restored to Account List.')
    await loadRecycleBin()
  } catch (err) {
    reportWriteError(err, () => loadRecycleBin())
  } finally {
    recycleSaving.value = false
  }
}

onMounted(loadRecycleBin)
</script>

<template>
  <div class="overview-stack">
    <div class="mdm-intro">
      <div><span class="pending-badge">Placement governance · five-year restore window</span><h2>Retained Drafts</h2><p>Recycled Drafts remain recoverable for five years. Permanent deletion is prohibited for every role and is not exposed by the application.</p></div>
      <el-button class="secondary-button" :loading="recycleLoading" @click="loadRecycleBin">Refresh</el-button>
    </div>
    <el-alert class="case-readiness-alert" type="info" :closable="false" show-icon title="No permanent delete" :description="'Retention: ' + recyclePolicy.retentionYears + ' years. Records remain retained; only Restore is available.'"></el-alert>
    <section class="table-card" v-loading="recycleLoading">
      <div class="section-heading"><div><h2>Draft Recycle Bin</h2><p>{{ recycleItems.length }} retained Draft{{ recycleItems.length === 1 ? '' : 's' }}</p></div></div>
      <el-table :data="recycleItems" class="case-table" row-key="id" empty-text="No Drafts in the recycle bin.">
        <el-table-column prop="originalInsured" label="Insured" min-width="200"><template #default="{ row }">{{ row.originalInsured || 'Unnamed Draft' }}<br><small class="case-ref">{{ row.caseUid }}</small></template></el-table-column>
        <el-table-column prop="deletedBy" label="Recycled by" min-width="140"><template #default="{ row }">{{ row.deletedBy }}<br><small>{{ formatDateTime(row.deletedAt) }}</small></template></el-table-column>
        <el-table-column label="Restore deadline" min-width="150"><template #default="{ row }">{{ formatDateTime(row.restoreDeadline) }}</template></el-table-column>
        <el-table-column label="Action" width="100"><template #default="{ row }"><el-button v-if="row.canRestore && can('recycle.write')" text type="primary" :loading="recycleSaving" @click="restoreDraft(row)">Restore</el-button><span v-else>Retained</span></template></el-table-column>
      </el-table>
    </section>
  </div>
</template>
