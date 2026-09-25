<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import { can } from '../auth'
import { PASSWORD_RULE_TEXT, checkPassword } from '../passwordRule'

// 與 Alpha 的 PERSONNEL_DEPARTMENTS / PERSONNEL_ROLES / DEFAULT_ROLE_BY_DEPARTMENT 相同
const DEPARTMENTS = [
  { value: 'reinsurance', label: 'Reinsurance Dept.' },
  { value: 'finance', label: 'Finance Dept.' },
  { value: 'admin', label: 'Admin Dept.' },
  { value: 'business_1', label: 'Business Dept. 1' },
  { value: 'business_2', label: 'Business Dept. 2' },
  { value: 'special_risk', label: 'Special Risk Dept.' },
  { value: 'business_development', label: 'Business Development Dept.' }
]
const ROLES = [
  { value: 'general_manager', label: 'General Manager' },
  { value: 'sales', label: 'Reinsurance Staff' },
  { value: 'accounting_manager', label: 'Finance Manager' },
  { value: 'accounting', label: 'Finance Staff' },
  { value: 'admin', label: 'System Administrator' },
  { value: 'viewer', label: 'Case Viewer' }
]
const DEFAULT_ROLE_BY_DEPARTMENT = {
  business_1: 'viewer', business_2: 'viewer', special_risk: 'viewer',
  business_development: 'viewer', reinsurance: 'sales', finance: 'accounting', admin: 'admin'
}
const ACCOUNT_STATUS = {
  not_configured: { label: '未建立帳號', type: 'info' },
  pending: { label: '邀請中', type: 'warning' },
  active: { label: '已啟用', type: 'success' },
  disabled: { label: '已停用', type: 'danger' }
}

function defaultSplitEligibility(department, roleCode) {
  return department !== 'finance' && department !== 'admin' && !(department === 'reinsurance' && roleCode === 'general_manager')
}
const departmentLabel = (v) => DEPARTMENTS.find((d) => d.value === v)?.label || v || '—'
const roleLabel = (v) => ROLES.find((r) => r.value === v)?.label || v || '—'

const loading = ref(false)
const saving = ref(false)
const people = ref([])
const counts = ref({ total: 0, active: 0, splitEligible: 0, accountsActive: 0 })
const tab = ref('active')
const errorMsg = ref('')

const visible = computed(() => people.value.filter((p) => (tab.value === 'active' ? p.isActive : !p.isActive)))

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    const body = await api('/api/personnel')
    people.value = body.personnel || []
    counts.value = body.counts || counts.value
  } catch (e) {
    errorMsg.value = e.message
  } finally {
    loading.value = false
  }
}

// ---------- 人員新增 / 編輯 ----------
const dialogVisible = ref(false)
const editingId = ref(null)
const editingVersion = ref(null)
const editingAccountStatus = ref('not_configured')
const form = reactive({
  name: '', email: '', department: 'reinsurance', roleCode: 'sales',
  isActive: false, isSplitEligible: true, supervisorName: ''
})

// 主管：同部門的在職人員，或在職的 General Manager；不能是自己
const supervisorOptions = computed(() =>
  people.value.filter((p) => p.isActive && p.id !== editingId.value &&
    (p.department === form.department || p.roleCode === 'general_manager'))
)
const emailLocked = computed(() => ['pending', 'active'].includes(editingAccountStatus.value))

function openDialog(row = null) {
  editingId.value = row ? row.id : null
  editingVersion.value = row ? row.rowVersion : null
  editingAccountStatus.value = row ? row.accountStatus : 'not_configured'
  Object.assign(form, row
    ? {
        name: row.name, email: row.email || '', department: row.department, roleCode: row.roleCode,
        isActive: row.isActive, isSplitEligible: row.isSplitEligible, supervisorName: row.supervisorName || ''
      }
    : {
        name: '', email: '', department: 'reinsurance', roleCode: 'sales', isActive: false,
        isSplitEligible: defaultSplitEligibility('reinsurance', 'sales'), supervisorName: ''
      })
  dialogVisible.value = true
}

function onDepartmentChange(value) {
  if (!editingId.value) form.roleCode = DEFAULT_ROLE_BY_DEPARTMENT[value] || 'viewer'
  form.isSplitEligible = defaultSplitEligibility(value, form.roleCode)
  form.supervisorName = ''
}
function onRoleChange(value) {
  form.isSplitEligible = defaultSplitEligibility(form.department, value)
}

async function report(e) {
  ElMessage.error(e.message || '操作失敗')
  if (e.status === 409) await load() // 版本衝突或狀態已變：重新載入最新資料
}

async function save() {
  if (!form.name.trim()) return ElMessage.error('請輸入姓名')
  saving.value = true
  try {
    const updating = Boolean(editingId.value)
    await api('/api/personnel', {
      method: updating ? 'PUT' : 'POST',
      body: { ...form, id: editingId.value, rowVersion: editingVersion.value }
    })
    dialogVisible.value = false
    ElMessage.success(updating ? '人員資料已更新' : '人員已新增')
    await load()
  } catch (e) {
    await report(e)
  } finally {
    saving.value = false
  }
}

async function toggleActive(row) {
  const action = row.isActive ? '停用' : '重新啟用'
  try {
    await ElMessageBox.confirm(`確定要${action}「${row.name}」嗎？`, action, { type: 'warning', confirmButtonText: action, cancelButtonText: '取消' })
  } catch {
    return
  }
  saving.value = true
  try {
    await api('/api/personnel', {
      method: 'PUT',
      body: {
        id: row.id, rowVersion: row.rowVersion, name: row.name, email: row.email, department: row.department,
        roleCode: row.roleCode, isSplitEligible: row.isSplitEligible, supervisorName: row.supervisorName,
        isActive: !row.isActive
      }
    })
    ElMessage.success(row.isActive ? '已停用' : '已重新啟用')
    await load()
  } catch (e) {
    await report(e)
  } finally {
    saving.value = false
  }
}

// ---------- 帳號（僅 System Administrator） ----------
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

async function createAccount() {
  const password = accountDialog.password
  const problem = password ? checkPassword(password) : ''
  if (problem) return ElMessage.error(`${problem}（初始密碼留空則由系統產生）`)
  saving.value = true
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
      showSecret('帳號已建立', body.username, body.initialPassword)
    } else {
      ElMessage.success(`帳號 ${body.username} 已建立，請把您設定的初始密碼交給本人，並請他登入後立刻修改。`)
    }
    await load()
  } catch (e) {
    await report(e)
  } finally {
    accountDialog.password = '' // 密碼不留在畫面的記憶體裡
    saving.value = false
  }
}

async function resetPassword(row) {
  try {
    await ElMessageBox.confirm(
      `重設「${row.name}」的密碼後，他目前所有的登入都會立刻失效。確定嗎？`, '重設密碼',
      { type: 'warning', confirmButtonText: '重設', cancelButtonText: '取消' })
  } catch {
    return
  }
  saving.value = true
  try {
    const body = await api('/api/personnel-accounts/reset-password', { method: 'POST', body: { personnelId: row.id } })
    showSecret('密碼已重設', body.username, body.newPassword)
    await load()
  } catch (e) {
    await report(e)
  } finally {
    saving.value = false
  }
}

async function disableAccount(row) {
  try {
    await ElMessageBox.confirm(
      `停用「${row.name}」的帳號後，他將無法登入，目前的登入也會立刻失效。確定嗎？`, '停用帳號',
      { type: 'warning', confirmButtonText: '停用帳號', cancelButtonText: '取消' })
  } catch {
    return
  }
  saving.value = true
  try {
    await api('/api/personnel-accounts/disable', { method: 'POST', body: { personnelId: row.id } })
    ElMessage.success('帳號已停用')
    await load()
  } catch (e) {
    await report(e)
  } finally {
    saving.value = false
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
    ElMessage.success('已複製')
  } catch {
    ElMessage.warning('無法自動複製，請手動選取')
  }
}

onMounted(load)
</script>

<template>
  <el-card style="max-width: 1280px; margin: 24px auto">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>Personnel（人員）</span>
        <el-button v-if="can('personnel.write')" type="primary" @click="openDialog()">新增人員</el-button>
      </div>
    </template>

    <el-alert v-if="errorMsg" :title="'錯誤：' + errorMsg" type="error" show-icon :closable="false" style="margin-bottom: 16px" />

    <div style="display: flex; gap: 24px; align-items: center; margin-bottom: 16px; flex-wrap: wrap">
      <el-radio-group v-model="tab">
        <el-radio-button value="active">在職（{{ counts.active }}）</el-radio-button>
        <el-radio-button value="inactive">已停用（{{ counts.total - counts.active }}）</el-radio-button>
      </el-radio-group>
      <span style="color: #909399; font-size: 13px">
        可參與業績拆分 {{ counts.splitEligible }} 人 · 已啟用帳號 {{ counts.accountsActive }} 人
      </span>
    </div>

    <el-table :data="visible" v-loading="loading || saving" border size="small" empty-text="沒有資料">
      <el-table-column prop="name" label="姓名" min-width="110" />
      <el-table-column label="部門" min-width="150">
        <template #default="{ row }">{{ departmentLabel(row.department) }}</template>
      </el-table-column>
      <el-table-column label="角色" min-width="150">
        <template #default="{ row }">{{ roleLabel(row.roleCode) }}</template>
      </el-table-column>
      <el-table-column label="業績拆分" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="row.isSplitEligible ? 'success' : 'info'" size="small">{{ row.isSplitEligible ? '可' : '否' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="supervisorName" label="主管" min-width="90" />
      <el-table-column prop="email" label="Email" min-width="190" />
      <el-table-column label="帳號" min-width="200">
        <template #default="{ row }">
          <el-tag :type="ACCOUNT_STATUS[row.accountStatus]?.type || 'info'" size="small">
            {{ ACCOUNT_STATUS[row.accountStatus]?.label || row.accountStatus }}
          </el-tag>
          <span v-if="row.accountUsername" style="margin-left: 6px; color: #606266; font-size: 12px">{{ row.accountUsername }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" min-width="300" fixed="right">
        <template #default="{ row }">
          <template v-if="can('personnel.write')">
            <el-button link type="primary" @click="openDialog(row)">編輯</el-button>
            <el-button link :type="row.isActive ? 'danger' : 'success'" @click="toggleActive(row)">
              {{ row.isActive ? '停用' : '重新啟用' }}
            </el-button>
          </template>
          <template v-if="can('accounts.manage') && row.isActive">
            <el-button v-if="row.accountStatus === 'not_configured'" link type="primary" @click="openCreateAccount(row)">建立帳號</el-button>
            <template v-if="row.accountStatus === 'active'">
              <el-button link type="warning" @click="resetPassword(row)">重設密碼</el-button>
              <el-button link type="danger" @click="disableAccount(row)">停用帳號</el-button>
            </template>
          </template>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <!-- 新增 / 編輯人員 -->
  <el-dialog v-model="dialogVisible" :title="editingId ? '編輯人員' : '新增人員'" width="560px">
    <el-form label-width="120px">
      <el-form-item label="姓名" required><el-input v-model="form.name" maxlength="160" /></el-form-item>
      <el-form-item label="Email">
        <el-input v-model="form.email" :disabled="emailLocked" placeholder="選填" />
        <div v-if="emailLocked" style="color: #909399; font-size: 12px">已有啟用中的帳號；要修改 Email 請先停用帳號。</div>
      </el-form-item>
      <el-form-item label="部門" required>
        <el-select v-model="form.department" style="width: 100%" @change="onDepartmentChange">
          <el-option v-for="d in DEPARTMENTS" :key="d.value" :label="d.label" :value="d.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="角色" required>
        <el-select v-model="form.roleCode" style="width: 100%" @change="onRoleChange">
          <el-option v-for="r in ROLES" :key="r.value" :label="r.label" :value="r.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="主管">
        <el-select v-model="form.supervisorName" clearable placeholder="同部門的在職人員或 General Manager" style="width: 100%">
          <el-option v-for="p in supervisorOptions" :key="p.id" :label="`${p.name}（${departmentLabel(p.department)}）`" :value="p.name" />
        </el-select>
      </el-form-item>
      <el-form-item label="在職"><el-switch v-model="form.isActive" active-text="在職" inactive-text="停用" /></el-form-item>
      <el-form-item label="業績拆分"><el-switch v-model="form.isSplitEligible" active-text="可參與" inactive-text="不可" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">儲存</el-button>
    </template>
  </el-dialog>

  <!-- 建立帳號 -->
  <el-dialog v-model="accountDialog.visible" title="建立登入帳號" width="480px">
    <p style="margin-top: 0">為「<strong>{{ accountDialog.person?.name }}</strong>（{{ roleLabel(accountDialog.person?.roleCode) }}）」建立帳號。權限由人員的角色決定。</p>
    <el-form label-width="90px" @submit.prevent="createAccount">
      <el-form-item label="帳號" required>
        <el-input v-model="accountDialog.username" placeholder="小寫英數字與 . _ @ + -，至少 3 個字元" />
      </el-form-item>
      <el-form-item label="Email"><el-input v-model="accountDialog.email" placeholder="選填，會寫入人員資料" /></el-form-item>
      <el-form-item label="初始密碼">
        <el-input v-model="accountDialog.password" type="password" show-password autocomplete="new-password" placeholder="留空則由系統產生隨機密碼" />
        <div style="color: #909399; font-size: 12px; line-height: 1.5; margin-top: 4px">
          {{ PASSWORD_RULE_TEXT }}<br />
          管理員設定的密碼不會再顯示；請自行告知本人，並請他登入後立刻修改。
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="accountDialog.visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="createAccount">建立</el-button>
    </template>
  </el-dialog>

  <!-- 一次性密碼 -->
  <el-dialog v-model="secretDialog.visible" :title="secretDialog.title" width="480px" :close-on-click-modal="false" :close-on-press-escape="false" :show-close="false">
    <el-alert type="warning" show-icon :closable="false" title="這組密碼只會顯示這一次，關閉後無法再查看。請現在交給本人，並請他登入後立刻修改密碼。" style="margin-bottom: 16px" />
    <el-form label-width="70px">
      <el-form-item label="帳號">
        <el-input :model-value="secretDialog.username" readonly>
          <template #append><el-button @click="copy(secretDialog.username)">複製</el-button></template>
        </el-input>
      </el-form-item>
      <el-form-item label="密碼">
        <el-input :model-value="secretDialog.password" readonly style="font-family: monospace">
          <template #append><el-button @click="copy(secretDialog.password)">複製</el-button></template>
        </el-input>
      </el-form-item>
    </el-form>
    <template #footer><el-button type="primary" @click="closeSecret">我已記下，關閉</el-button></template>
  </el-dialog>
</template>
