<script setup>
// 移植自 Alpha index.html Personnel 頁的「Annual target settings」頁籤與 app.js 的 loadDashboardTargets()／openTargetDialog()／
// onTargetTypeChange()／saveDashboardTarget()／toggleDashboardTarget()。
//
// 與 Alpha 不同的地方（都記在 MIGRATION-STATUS.md）：
//   - fetch() → apiFetch()
//   - 說明文字改成 VM 的實際情況：Dashboard 已使用目標、每次變更都寫 Audit（Alpha 寫「之後才使用」「Audit 暫停」）
//   - 新增時的預設年份／月份用台北時間（Alpha 用 UTC）
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiFetch } from '../api'
import { can } from '../auth'
import { formatCurrency, reportWriteError } from '../alpha/format'
import { shell } from '../alpha/shell'

const targetLoading = ref(false)
const targetSaving = ref(false)
const targetDialogVisible = ref(false)
const dashboardTargets = ref([])
const targetForm = reactive({ id: null, periodType: 'annual', periodKey: '', amount: null, rowVersion: null, isActive: true })

function taipeiMonth() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit' }).format(new Date()).slice(0, 7)
}
function currentMonth() { return taipeiMonth() }
function currentYear() { return taipeiMonth().slice(0, 4) }

async function loadDashboardTargets() {
  targetLoading.value = true
  shell.error = ''
  try {
    const response = await apiFetch('/api/dashboard-targets', { headers: { Accept: 'application/json' } })
    const body = await response.json()
    if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
    dashboardTargets.value = Array.isArray(body.targets) ? body.targets : []
  } catch (err) {
    shell.error = err instanceof Error ? err.message : String(err)
    ElMessage.error(shell.error)
  } finally {
    targetLoading.value = false
  }
}

function openTargetDialog(row = null, periodType = 'annual') {
  Object.assign(targetForm, row
    ? {
        id: Number(row.id), periodType: row.periodType, periodKey: row.periodKey,
        amount: Number(row.amount), rowVersion: Number(row.rowVersion), isActive: Boolean(row.isActive)
      }
    : {
        id: null, periodType,
        periodKey: periodType === 'annual' ? currentYear() : currentMonth(),
        amount: null, rowVersion: null, isActive: true
      })
  targetDialogVisible.value = true
}

function onTargetTypeChange(value) {
  if (targetForm.id) return
  targetForm.periodKey = value === 'annual' ? currentYear() : currentMonth()
}

async function putOrPost(method, payload) {
  const response = await apiFetch('/api/dashboard-targets', {
    method, headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(payload)
  })
  const body = await response.json()
  if (!response.ok) {
    const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status))
    requestErr.status = response.status
    throw requestErr
  }
  return body
}

async function saveDashboardTarget() {
  const amount = Number(targetForm.amount)
  if (!Number.isFinite(amount) || amount < 0) return ElMessage.error('Target must be a non-negative amount')
  targetSaving.value = true
  shell.error = ''
  try {
    const updating = Boolean(targetForm.id)
    await putOrPost(updating ? 'PUT' : 'POST', { ...targetForm, amount })
    targetDialogVisible.value = false
    await loadDashboardTargets()
    ElMessage.success(updating ? 'Target updated' : 'Target added')
  } catch (err) {
    shell.error = err instanceof Error ? err.message : String(err)
    reportWriteError(err, () => loadDashboardTargets())
  } finally {
    targetSaving.value = false
  }
}

async function toggleDashboardTarget(row) {
  targetSaving.value = true
  shell.error = ''
  try {
    const body = await putOrPost('PUT', { ...row, isActive: !row.isActive })
    await loadDashboardTargets()
    ElMessage.success(body.target.isActive ? 'Target reactivated' : 'Target deactivated')
  } catch (err) {
    shell.error = err instanceof Error ? err.message : String(err)
    reportWriteError(err, () => loadDashboardTargets())
  } finally {
    targetSaving.value = false
  }
}

onMounted(loadDashboardTargets)
</script>

<template>
  <el-alert class="case-readiness-alert" type="info" :closable="false" show-icon title="Targets feed the Dashboard brokerage trend" description="Annual and monthly TWD targets are versioned, and every change is recorded in the Audit Log."></el-alert>
  <section class="table-card" v-loading="targetLoading">
    <div class="section-heading"><div><h2>Annual brokerage target settings</h2><p>Used by the Dashboard YTD Brokerage Trend chart. Deactivated settings remain in history.</p></div><div><el-button v-if="can('targets.write')" class="primary-button" @click="openTargetDialog(null, 'annual')">+ Add target</el-button><el-button v-if="can('targets.write')" class="secondary-button" @click="openTargetDialog(null, 'monthly')">+ Monthly target</el-button><el-button class="secondary-button" :loading="targetLoading" @click="loadDashboardTargets">Refresh</el-button></div></div>
    <el-table :data="dashboardTargets" class="case-table" row-key="id" empty-text="No target settings yet.">
      <el-table-column prop="periodKey" label="Period" min-width="180"><template #default="{ row }"><span class="case-ref">{{ row.periodKey }}</span></template></el-table-column>
      <el-table-column prop="periodType" label="Type" width="130"><template #default="{ row }">{{ row.periodType === 'annual' ? 'Annual' : 'Monthly' }}</template></el-table-column>
      <el-table-column label="Target (TWD)" min-width="200" align="right"><template #default="{ row }">{{ formatCurrency(row.amount, 'TWD') }}</template></el-table-column>
      <el-table-column label="Status" width="130"><template #default="{ row }"><span class="status-badge" :class="row.isActive ? 'status-posted' : 'status-archived'">{{ row.isActive ? 'Active' : 'Inactive' }}</span></template></el-table-column>
      <el-table-column prop="rowVersion" label="Version" width="100"></el-table-column>
      <el-table-column v-if="can('targets.write')" label="Action" width="220"><template #default="{ row }"><el-button text type="primary" @click="openTargetDialog(row)">Edit</el-button><el-button text :type="row.isActive ? 'danger' : 'success'" :loading="targetSaving" @click="toggleDashboardTarget(row)">{{ row.isActive ? 'Deactivate' : 'Reactivate' }}</el-button></template></el-table-column>
    </el-table>
  </section>
  <el-dialog v-model="targetDialogVisible" class="master-dialog" width="min(560px, 94vw)" :close-on-click-modal="false">
    <template #header><div class="review-heading"><span class="pending-badge">{{ targetForm.id ? 'Versioned target update' : 'New target setting' }}</span><h2>{{ targetForm.id ? 'Edit' : 'Add' }} dashboard target</h2><p>Saving creates an immutable snapshot and an Audit Log event.</p></div></template>
    <el-form label-position="top" @submit.prevent>
      <el-form-item label="Period type" required><el-select v-model="targetForm.periodType" :disabled="Boolean(targetForm.id)" @change="onTargetTypeChange"><el-option label="Annual" value="annual"></el-option><el-option label="Monthly" value="monthly"></el-option></el-select></el-form-item>
      <el-form-item label="Period" required><el-input v-if="targetForm.periodType === 'annual'" v-model="targetForm.periodKey" maxlength="4" placeholder="YYYY" :disabled="Boolean(targetForm.id)"></el-input><el-date-picker v-else v-model="targetForm.periodKey" type="month" value-format="YYYY-MM" format="MMM YYYY" placeholder="YYYY-MM" :disabled="Boolean(targetForm.id)" style="width:100%"></el-date-picker></el-form-item>
      <el-form-item label="Target amount (TWD)" required><el-input-number v-model="targetForm.amount" :min="0" :precision="2" :controls="false" style="width:100%"></el-input-number></el-form-item>
      <el-form-item v-if="targetForm.id" label="Active"><el-switch v-model="targetForm.isActive" inline-prompt active-text="Yes" inactive-text="No"></el-switch></el-form-item>
    </el-form>
    <template #footer><div class="review-footer"><p>Target settings are retained; no physical delete action is available.</p><div><el-button class="secondary-button" @click="targetDialogVisible = false">Cancel</el-button><el-button class="primary-button" :loading="targetSaving" @click="saveDashboardTarget">{{ targetForm.id ? 'Save changes' : 'Add target' }}</el-button></div></div></template>
  </el-dialog>
</template>
