<script setup>
// 版面與人員維護移植自 Alpha index.html 的 activeView === 'personnel' 與 app.js 的人員函式
// （loadPersonnel、openPersonnelDialog、onPersonnelDepartmentChange、onPersonnelRoleChange、onSupervisorSelected、
//   savePersonnel、togglePersonnelStatus、accountStatusLabel、sortedPersonnelRecords）。
// VM 專有（Alpha 的登入由 Hatchable 代管）：登入帳號的建立／重設密碼／停用／重新啟用、重新啟用在職、Email 鎖定規則。
// Alpha 的「Annual target settings」頁籤需要 dashboard-targets API，VM 尚未移植，先顯示「Queued for migration」。
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, apiFetch } from '../api'
import { can } from '../auth'
import { PASSWORD_RULE_TEXT, checkPassword } from '../passwordRule'
import {
  DEFAULT_ROLE_BY_DEPARTMENT, PERSONNEL_DEPARTMENT_ORDER, PERSONNEL_DEPARTMENTS, PERSONNEL_ROLE_ORDER,
  PERSONNEL_ROLES, defaultSplitEligibility
} from '../alpha/constants'
import { departmentLabel, jsonOrThrow, reportWriteError, roleLabel } from '../alpha/format'
import { shell } from '../alpha/shell'

const personnelDepartments = PERSONNEL_DEPARTMENTS
const personnelRoles = PERSONNEL_ROLES
const personnelLoading = ref(false)
const personnelSaving = ref(false)
const personnelDialogVisible = ref(false)
const personnelRecords = ref([])
const sortedPersonnelRecords = computed(() => {
  const deptRank = (dept) => {
    const idx = PERSONNEL_DEPARTMENT_ORDER.indexOf(dept)
    return idx === -1 ? PERSONNEL_DEPARTMENT_ORDER.length : idx
  }
  const roleRank = (role) => {
    const idx = PERSONNEL_ROLE_ORDER.indexOf(role)
    return idx === -1 ? PERSONNEL_ROLE_ORDER.length : idx
  }
  return personnelRecords.value.slice().sort((a, b) => {
    const deptDiff = deptRank(a.department) - deptRank(b.department)
    if (deptDiff !== 0) return deptDiff
    const roleDiff = roleRank(a.roleCode) - roleRank(b.roleCode)
    if (roleDiff !== 0) return roleDiff
    return String(a.name || '').localeCompare(String(b.name || ''))
  })
})
const personnelTab = ref('roster')
const editingPersonnelId = ref(null)
const editingPersonnelRowVersion = ref(null)
const editingAccountStatus = ref('not_configured')
const personnelForm = reactive({
  name: '', email: '', department: 'reinsurance', roleCode: 'sales',
  isActive: false, isSplitEligible: false, supervisorName: '', supervisorEmail: ''
})
const supervisorOptions = computed(() => personnelRecords.value
  .filter((person) => person.isActive
    && (person.department === personnelForm.department || person.roleCode === 'general_manager')
    && Number(person.id) !== Number(editingPersonnelId.value))
  .slice()
  .sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''))))
// VM：已綁定（邀請中或啟用中）帳號的人，要先停用帳號才能改 Email
const emailLocked = computed(() => ['pending', 'active'].includes(editingAccountStatus.value))

function accountStatusLabel(value) {
  return {
    not_configured: 'Not enabled yet',
    pending: 'Pending activation',
    active: 'Active',
    disabled: 'Disabled'
  }[value] || value || 'Not enabled yet'
}
function accountStatusClass(value) {
  return { active: 'status-posted', disabled: 'status-reversed', pending: 'status-draft' }[value] || 'status-archived'
}

async function loadPersonnel() {
  personnelLoading.value = true
  shell.error = ''
  try {
    const response = await apiFetch('/api/personnel', { headers: { Accept: 'application/json' } })
    const body = await response.json()
    if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
    personnelRecords.value = Array.isArray(body.personnel) ? body.personnel : []
  } catch (err) {
    shell.error = err instanceof Error ? err.message : String(err)
    ElMessage.error(shell.error)
  } finally {
    personnelLoading.value = false
  }
}

function openPersonnelDialog(row = null) {
  editingPersonnelId.value = row ? Number(row.id) : null
  editingPersonnelRowVersion.value = row ? Number(row.rowVersion) : null
  editingAccountStatus.value = row ? row.accountStatus : 'not_configured'
  Object.assign(personnelForm, row
    ? {
        name: row.name || '', email: row.email || '', department: row.department,
        roleCode: row.roleCode, isActive: Boolean(row.isActive),
        isSplitEligible: Boolean(row.isSplitEligible),
        supervisorName: row.supervisorName || '', supervisorEmail: row.supervisorEmail || ''
      }
    : {
        name: '', email: '', department: 'reinsurance', roleCode: 'sales',
        isActive: false, isSplitEligible: defaultSplitEligibility('reinsurance', 'sales'), supervisorName: '', supervisorEmail: ''
      })
  personnelDialogVisible.value = true
}

function onPersonnelDepartmentChange(value) {
  if (!editingPersonnelId.value) personnelForm.roleCode = DEFAULT_ROLE_BY_DEPARTMENT[value] || 'viewer'
  personnelForm.isSplitEligible = defaultSplitEligibility(value, personnelForm.roleCode)
  personnelForm.supervisorName = ''
  personnelForm.supervisorEmail = ''
}

function onPersonnelRoleChange(value) {
  personnelForm.isSplitEligible = defaultSplitEligibility(personnelForm.department, value)
}

function onSupervisorSelected(value) {
  const supervisor = supervisorOptions.value.find((person) => person.name === value)
  personnelForm.supervisorEmail = supervisor?.email || ''
}

async function savePersonnel() {
  if (!String(personnelForm.name || '').trim()) return ElMessage.error('Personnel name is required')
  personnelSaving.value = true
  shell.error = ''
  try {
    const updating = Boolean(editingPersonnelId.value)
    await jsonOrThrow(await apiFetch('/api/personnel', {
      method: updating ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ ...personnelForm, id: editingPersonnelId.value, rowVersion: editingPersonnelRowVersion.value })
    }))
    personnelDialogVisible.value = false
    await loadPersonnel()
    ElMessage.success(updating ? 'Personnel updated' : 'Personnel added')
  } catch (err) {
    shell.error = err instanceof Error ? err.message : String(err)
    reportWriteError(err, () => loadPersonnel())
  } finally {
    personnelSaving.value = false
  }
}

async function togglePersonnelStatus(row) {
  personnelSaving.value = true
  shell.error = ''
  try {
    const body = await jsonOrThrow(await apiFetch('/api/personnel', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ ...row, roleCode: row.roleCode, rowVersion: row.rowVersion, isActive: !row.isActive })
    }))
    await loadPersonnel()
    ElMessage.success(body.person.isActive ? 'Personnel reactivated' : 'Personnel deactivated')
  } catch (err) {
    shell.error = err instanceof Error ? err.message : String(err)
    reportWriteError(err, () => loadPersonnel())
  } finally {
    personnelSaving.value = false
  }
}

// ---------- VM 專有：登入帳號（System Administrator，accounts.manage） ----------
const accountDialog = reactive({ visible: false, person: null, username: '', email: '', password: '' })
const secretDialog = reactive({ visible: false, title: '', username: '', password: '' })

function openCreateAccount(row) {
  Object.assign(accountDialog, { visible: true, person: row, username: (row.email || '').toLowerCase(), email: row.email || '', password: '' })
}
function showSecret(title, username, password) {
  Object.assign(secretDialog, { visible: true, title, username, password })
}
function closeSecret() {
  // 關閉後就再也看不到密碼；同時清掉記憶體中的值
  Object.assign(secretDialog, { visible: false, username: '', password: '' })
}
async function accountError(e) {
  ElMessage.error(e.message || 'The account action failed.')
  if (e.status === 409) await loadPersonnel() // 狀態已變：重新載入最新資料
}

async function createAccount() {
  const password = accountDialog.password
  const problem = password ? checkPassword(password) : ''
  if (problem) return ElMessage.error(`${problem} (Leave it blank to have the system generate one.)`)
  personnelSaving.value = true
  try {
    const body = await api('/api/personnel-accounts', {
      method: 'POST',
      body: {
        personnelId: accountDialog.person.id, username: accountDialog.username, email: accountDialog.email,
        // 留空 = 由系統隨機產生；有填 = 管理員指定的初始密碼
        ...(password ? { initialPassword: password } : {})
      }
    })
    accountDialog.visible = false
    if (body.initialPassword) {
      showSecret('Account created', body.username, body.initialPassword)
    } else {
      ElMessage.success(`Account ${body.username} created. Give the initial password you set to the person; they must change it at first sign-in.`)
    }
    await loadPersonnel()
  } catch (e) {
    await accountError(e)
  } finally {
    accountDialog.password = '' // 密碼不留在畫面的記憶體裡
    personnelSaving.value = false
  }
}

async function confirmAction(message, title, button) {
  try {
    await ElMessageBox.confirm(message, title, { type: 'warning', confirmButtonText: button, cancelButtonText: 'Cancel' })
    return true
  } catch {
    return false
  }
}

async function resetPassword(row) {
  if (!await confirmAction(`Resetting the password of “${row.name}” signs them out everywhere immediately. Continue?`, 'Reset password', 'Reset')) return
  personnelSaving.value = true
  try {
    const body = await api('/api/personnel-accounts/reset-password', { method: 'POST', body: { personnelId: row.id } })
    showSecret('Password reset', body.username, body.newPassword)
    await loadPersonnel()
  } catch (e) {
    await accountError(e)
  } finally {
    personnelSaving.value = false
  }
}

async function disableAccount(row) {
  if (!await confirmAction(`After the account of “${row.name}” is disabled they cannot sign in, and current sessions end immediately. Continue?`, 'Disable account', 'Disable account')) return
  personnelSaving.value = true
  try {
    await api('/api/personnel-accounts/disable', { method: 'POST', body: { personnelId: row.id } })
    ElMessage.success('Account disabled')
    await loadPersonnel()
  } catch (e) {
    await accountError(e)
  } finally {
    personnelSaving.value = false
  }
}

async function enableAccount(row) {
  if (!await confirmAction(
    `After re-enabling, “${row.name}” can sign in with the existing username and password, but must change the password at first sign-in. If the password has been forgotten, use Reset password afterwards. Continue?`,
    'Re-enable account', 'Re-enable')) return
  personnelSaving.value = true
  try {
    await api('/api/personnel-accounts/enable', { method: 'POST', body: { personnelId: row.id } })
    ElMessage.success('Account re-enabled (password change required at first sign-in)')
    await loadPersonnel()
  } catch (e) {
    await accountError(e)
  } finally {
    personnelSaving.value = false
  }
}

// 內網是 http（不是安全環境），navigator.clipboard 不可用，退回舊的複製方式
async function copy(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
    } else {
      const area = document.createElement('textarea')
      area.value = text
      area.style.position = 'fixed'
      area.style.opacity = '0'
      document.body.appendChild(area)
      area.select()
      document.execCommand('copy')
      document.body.removeChild(area)
    }
    ElMessage.success('Copied')
  } catch {
    ElMessage.warning('Could not copy automatically. Select the text and copy it manually.')
  }
}

onMounted(loadPersonnel)
</script>

<template>
  <!-- Development begins this page with Personnel / Target tabs. -->

  <div class="mdm-tabs" role="tablist" aria-label="Personnel and target settings">
    <button type="button" class="mdm-tab" :class="{ active: personnelTab === 'roster' }" @click="personnelTab = 'roster'">
      <span>Personnel roster</span>
    </button>
    <button type="button" class="mdm-tab" :class="{ active: personnelTab === 'targets' }" @click="personnelTab = 'targets'">
      <span>Annual target settings</span>
    </button>
  </div>

  <template v-if="personnelTab === 'roster'">
    <section class="table-card personnel-card" v-loading="personnelLoading">
      <div class="section-heading"><div><h2>Personnel &amp; Accounts</h2><p>Every company person is maintained once. Login accounts are enabled on the company VM and managed by the System Administrator; there is no permanent deletion.</p></div><div><el-button v-if="can('personnel.write')" class="primary-button" @click="openPersonnelDialog()">+ Add personnel</el-button><el-button class="secondary-button" :loading="personnelLoading" @click="loadPersonnel">Refresh</el-button></div></div>
      <div class="personnel-table-scroll">
      <el-table :data="sortedPersonnelRecords" class="case-table personnel-table" row-key="id" empty-text="No personnel records yet.">
        <el-table-column prop="name" label="Name" min-width="150"><template #default="{ row }"><span class="case-ref">{{ row.name }}</span><br v-if="row.email"><small v-if="row.email">{{ row.email }}</small></template></el-table-column>
        <el-table-column label="Department" min-width="110"><template #default="{ row }">{{ departmentLabel(row.department) }}</template></el-table-column>
        <el-table-column label="Role" min-width="100"><template #default="{ row }">{{ roleLabel(row.roleCode) }}</template></el-table-column>
        <el-table-column label="Personnel" width="85"><template #default="{ row }"><span class="status-badge" :class="row.isActive ? 'status-posted' : 'status-archived'">{{ row.isActive ? 'Active' : 'Inactive' }}</span></template></el-table-column>
        <el-table-column label="Login Account" min-width="150"><template #default="{ row }"><span class="status-badge" :class="accountStatusClass(row.accountStatus)">{{ accountStatusLabel(row.accountStatus) }}</span><template v-if="row.accountUsername"><br><small class="case-ref">{{ row.accountUsername }}</small></template><template v-if="row.accountMustChangePassword && row.accountStatus === 'active'"><br><small>Password change pending</small></template></template></el-table-column>
        <el-table-column label="Split Eligible" width="95"><template #default="{ row }">{{ row.isSplitEligible ? 'Yes' : 'No' }}</template></el-table-column>
        <el-table-column label="Supervisor" min-width="130"><template #default="{ row }"><div>{{ row.supervisorName || '—' }}</div><small v-if="row.supervisorEmail">{{ row.supervisorEmail }}</small></template></el-table-column>
        <el-table-column v-if="can('personnel.write') || can('accounts.manage')" label="Action" min-width="230"><template #default="{ row }">
          <template v-if="can('personnel.write')">
            <el-button text type="primary" @click="openPersonnelDialog(row)">Edit</el-button>
            <el-button text :type="row.isActive ? 'danger' : 'success'" :loading="personnelSaving" @click="togglePersonnelStatus(row)">{{ row.isActive ? 'Deactivate' : 'Reactivate' }}</el-button>
          </template>
          <template v-if="can('accounts.manage') && row.isActive">
            <el-button v-if="row.accountStatus === 'not_configured'" text type="primary" @click="openCreateAccount(row)">Create account</el-button>
            <template v-if="row.accountStatus === 'active'">
              <el-button text type="warning" @click="resetPassword(row)">Reset password</el-button>
              <el-button text type="danger" @click="disableAccount(row)">Disable account</el-button>
            </template>
            <el-button v-if="row.accountStatus === 'disabled'" text type="success" @click="enableAccount(row)">Re-enable account</el-button>
          </template>
        </template></el-table-column>
      </el-table>
      </div>
    </section>
  </template>

  <template v-else>
    <section class="pending-card"><span class="pending-badge">Queued for migration</span><h2>Annual brokerage target settings</h2><p>Annual and monthly TWD targets used by the Dashboard YTD Brokerage Trend chart will be migrated together with the Dashboard.</p><div class="pending-rule"></div><p class="pending-note">This tab remains stable while each legacy screen is migrated and verified one at a time.</p></section>
  </template>

  <el-dialog v-model="personnelDialogVisible" class="master-dialog" width="min(760px, 94vw)" :close-on-click-modal="false">
    <template #header><div class="review-heading"><span class="pending-badge">{{ editingPersonnelId ? 'Versioned personnel update' : 'New personnel record' }}</span><h2>{{ editingPersonnelId ? 'Edit' : 'Add' }} personnel</h2><p>Saving creates an immutable snapshot and an Audit Log event. No credential or password is stored here.</p></div></template>
    <el-form label-position="top" @submit.prevent>
      <div class="form-grid cols-2">
        <el-form-item label="Name" required><el-input v-model="personnelForm.name" maxlength="160"></el-input></el-form-item>
        <el-form-item label="Personnel Email"><el-input v-model="personnelForm.email" maxlength="320" :disabled="emailLocked" placeholder="Optional personnel contact"></el-input><small v-if="emailLocked">This person has a bound login account; disable the account before changing the Email.</small></el-form-item>
        <el-form-item label="Department" required><el-select v-model="personnelForm.department" @change="onPersonnelDepartmentChange"><el-option v-for="item in personnelDepartments" :key="item.value" :label="item.label" :value="item.value"></el-option></el-select></el-form-item>
        <el-form-item label="Role assignment" required><el-select v-model="personnelForm.roleCode" @change="onPersonnelRoleChange"><el-option v-for="item in personnelRoles" :key="item.value" :label="item.label" :value="item.value"></el-option></el-select></el-form-item>
        <el-form-item label="Supervisor name"><el-select v-model="personnelForm.supervisorName" filterable clearable placeholder="Select same-department Personnel or General Manager" @change="onSupervisorSelected"><el-option v-for="item in supervisorOptions" :key="'supervisor-' + item.id" :label="item.name" :value="item.name"></el-option></el-select></el-form-item>
        <el-form-item label="Supervisor Email"><el-input v-model="personnelForm.supervisorEmail" readonly placeholder="Auto-filled from Personnel; may be blank"></el-input></el-form-item>
        <el-form-item label="Personnel active"><el-switch v-model="personnelForm.isActive" inline-prompt active-text="Yes" inactive-text="No"></el-switch></el-form-item>
        <el-form-item label="Performance Split eligible"><el-switch v-model="personnelForm.isSplitEligible" :disabled="!personnelForm.isActive" inline-prompt active-text="Yes" inactive-text="No"></el-switch></el-form-item>
      </div>
    </el-form>
    <template #footer><div class="review-footer"><p>Role assignment sets the permissions of the person's login account. Accounts are created from the roster by the System Administrator.</p><div><el-button class="secondary-button" @click="personnelDialogVisible = false">Cancel</el-button><el-button class="primary-button" :loading="personnelSaving" @click="savePersonnel">{{ editingPersonnelId ? 'Save changes' : 'Add personnel' }}</el-button></div></div></template>
  </el-dialog>

  <!-- VM 專有：建立登入帳號 -->
  <el-dialog v-model="accountDialog.visible" class="master-dialog" width="min(560px, 94vw)" :close-on-click-modal="false">
    <template #header><div class="review-heading"><span class="pending-badge">Login account</span><h2>Create login account</h2><p>For <strong>{{ accountDialog.person?.name }}</strong> ({{ roleLabel(accountDialog.person?.roleCode) }}). Permissions follow the person's role.</p></div></template>
    <el-form label-position="top" @submit.prevent="createAccount">
      <el-form-item label="Username" required>
        <el-input v-model="accountDialog.username" placeholder="Lower-case letters, digits and . _ @ + - (at least 3 characters)" />
      </el-form-item>
      <el-form-item label="Email"><el-input v-model="accountDialog.email" placeholder="Optional; saved to the Personnel record" /></el-form-item>
      <el-form-item label="Initial password">
        <el-input v-model="accountDialog.password" type="password" show-password autocomplete="new-password" placeholder="Leave blank to generate a random password" />
        <small>{{ PASSWORD_RULE_TEXT }} A password you set is not shown again; tell the person yourself. They must change it at first sign-in.</small>
      </el-form-item>
    </el-form>
    <template #footer><div class="review-footer"><p>The account is audited; the password is never stored in plain text or in the Audit Log.</p><div><el-button class="secondary-button" @click="accountDialog.visible = false">Cancel</el-button><el-button class="primary-button" :loading="personnelSaving" @click="createAccount">Create account</el-button></div></div></template>
  </el-dialog>

  <!-- VM 專有：一次性密碼 -->
  <el-dialog v-model="secretDialog.visible" class="master-dialog" width="min(520px, 94vw)" :close-on-click-modal="false" :close-on-press-escape="false" :show-close="false">
    <template #header><div class="review-heading"><span class="pending-badge">Shown once</span><h2>{{ secretDialog.title }}</h2><p>This password is shown only once and cannot be viewed again after closing. Give it to the person now; they must change it at first sign-in.</p></div></template>
    <el-form label-position="top">
      <el-form-item label="Username">
        <el-input :model-value="secretDialog.username" readonly>
          <template #append><el-button @click="copy(secretDialog.username)">Copy</el-button></template>
        </el-input>
      </el-form-item>
      <el-form-item label="Password">
        <el-input :model-value="secretDialog.password" readonly style="font-family: monospace">
          <template #append><el-button @click="copy(secretDialog.password)">Copy</el-button></template>
        </el-input>
      </el-form-item>
    </el-form>
    <template #footer><el-button class="primary-button" @click="closeSecret">I have noted it — close</el-button></template>
  </el-dialog>
</template>
