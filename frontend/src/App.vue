<script setup>
// 外框：照 Alpha public/index.html 的 app-shell（左側選單、頁首、版本條、內容區）。
// VM 專有：登入者的改密碼／登出、System Administrator 的唯讀資料檢視連結、強制改密碼對話框。
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { auth, can, changePassword, logout } from './auth'
import { PASSWORD_RULE_TEXT, checkPassword } from './passwordRule'
import { allNavigation, navAllowed } from './router'
import { shell } from './alpha/shell'

const router = useRouter()
const route = useRoute()
const navigation = computed(() => allNavigation.filter(navAllowed))
const activeNavId = computed(() => route.meta.nav?.id || '')

function selectView(item) {
  if (route.path !== item.path) router.push(item.path)
  else shell.navClicks += 1 // 例如在案件明細時再按「Account List」：回到列表（Alpha 的 selectView）
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function doLogout() {
  await logout()
  router.replace({ name: 'login' })
}

// 管理員建立帳號／重設密碼／重新啟用帳號之後，本人必須先改密碼才能使用系統（後端也會擋，這裡只是引導）
const forced = computed(() => !!auth.principal?.mustChangePassword)
const pwdOpen = ref(false)
const pwdVisible = computed({
  get: () => pwdOpen.value || forced.value,
  set: (value) => {
    if (!forced.value) pwdOpen.value = value
  }
})
const pwdSaving = ref(false)
const pwd = reactive({ current: '', next: '', confirm: '' })

function openPassword() {
  Object.assign(pwd, { current: '', next: '', confirm: '' })
  pwdOpen.value = true
}

async function savePassword() {
  const problem = checkPassword(pwd.next)
  if (problem) {
    ElMessage.error(problem)
    return
  }
  if (pwd.next !== pwd.confirm) {
    ElMessage.error('The new passwords do not match.')
    return
  }
  pwdSaving.value = true
  try {
    await changePassword(pwd.current, pwd.next)
    ElMessage.success('Password updated')
    pwdOpen.value = false
  } catch (e) {
    ElMessage.error(e.message || 'The password could not be updated.')
  } finally {
    pwdSaving.value = false
  }
}
</script>

<template>
  <!-- 登入頁不顯示外框 -->
  <router-view v-if="!auth.principal" />

  <div v-else class="app-shell">
    <aside class="sidebar">
      <div class="brand-block">
        <div class="eyebrow">再保部 | VM</div>
        <div class="brand-name">Reinsurance Department System</div>
        <div class="version-chip">Facultative Outward — Phase 1</div>
      </div>

      <nav v-if="!forced" class="nav-list" aria-label="系統導覽">
        <button v-for="item in navigation" :key="item.id" type="button" class="nav-item"
          :class="{ active: activeNavId === item.id }" @click="selectView(item)">
          <img class="nav-icon" :src="item.icon" alt="" aria-hidden="true">
          <span>{{ item.label }}</span>
          <span v-if="item.phase" class="nav-phase">{{ item.phase }}</span>
        </button>
      </nav>

      <div class="sidebar-note">
        <span class="environment-dot"></span>
        Company VM · Test environment<br>
        MySQL relational data
      </div>
    </aside>

    <main class="main-area">
      <header class="page-header">
        <div>
          <div class="header-kicker">{{ shell.header.kicker }}</div>
          <h1>{{ shell.header.title }}</h1>
          <p>{{ shell.header.subtitle }}</p>
        </div>
        <div class="header-actions">
          <div style="text-align:right;margin-right:10px;"><strong style="display:block;font-size:13px;">{{ auth.principal.name }}</strong><small>{{ auth.principal.roleLabel }}</small></div>
          <!-- 各畫面自己的頁首按鈕（例如案件的 Save draft）以 Teleport 放進這裡 -->
          <div id="page-header-actions" class="header-action-group"></div>
          <el-tag v-if="shell.header.phase" class="phase-tag" effect="plain">{{ shell.header.phase }}</el-tag>
          <a v-if="can('accounts.manage') && !forced" href="/admin/" class="vm-header-link">Data viewer</a>
          <el-button v-if="!forced" class="header-secondary-button" @click="openPassword">Change password</el-button>
          <el-button class="header-secondary-button" @click="doLogout">Log out</el-button>
        </div>
      </header>
      <div class="data-version-strip"><strong>VM · V 0.003</strong> · Company VM (Django + MySQL) · Audit Log recording enabled<br><small>Case forms: use Save draft / Save changes / Review &amp; Confirm. SOA settlement, Production Report, Dashboard and document generation are still being migrated.</small></div>

      <section class="content-area">
        <el-alert v-if="shell.error" title="Data could not be loaded" :description="shell.error" type="error" :closable="false" show-icon></el-alert>
        <router-view v-if="!forced" />
      </section>
    </main>
  </div>

  <el-dialog
    v-model="pwdVisible"
    class="review-dialog"
    width="min(460px, 94vw)"
    :close-on-click-modal="!forced"
    :close-on-press-escape="!forced"
    :show-close="!forced"
  >
    <template #header><div class="review-heading"><span class="pending-badge">{{ forced ? 'Required before you continue' : 'Account security' }}</span><h2>{{ forced ? 'Change your password first' : 'Change password' }}</h2><p>{{ PASSWORD_RULE_TEXT }}</p></div></template>
    <el-alert
      v-if="forced"
      type="warning" show-icon :closable="false"
      title="You are using a temporary password set by the System Administrator. Set your own new password (it must differ from the temporary one) to use the system."
    />
    <el-form label-position="top" @submit.prevent="savePassword">
      <el-form-item label="Current password">
        <el-input v-model="pwd.current" type="password" show-password autocomplete="current-password" />
      </el-form-item>
      <el-form-item label="New password">
        <el-input v-model="pwd.next" type="password" show-password autocomplete="new-password" placeholder="At least 8 characters with letters and digits" />
      </el-form-item>
      <el-form-item label="Confirm new password">
        <el-input v-model="pwd.confirm" type="password" show-password autocomplete="new-password" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button v-if="forced" class="secondary-button" @click="doLogout">Log out</el-button>
      <el-button v-else class="secondary-button" @click="pwdVisible = false">Cancel</el-button>
      <el-button class="primary-button" :loading="pwdSaving" @click="savePassword">Update password</el-button>
    </template>
  </el-dialog>
</template>

<style>
/* VM 專有的頁首連結（Alpha 沒有）；樣式比照 header-secondary-button */
.vm-header-link { height: 36px; padding: 0 14px; display: inline-flex; align-items: center; border: 1px solid rgba(175,45,65,.26); border-radius: 8px; color: var(--brand-navy-text); font-size: 14px; font-weight: 500; text-decoration: none; }
.vm-header-link:hover { border-color: rgba(15,27,51,.18); background: var(--surface-card); }
#page-header-actions:empty { display: none; }
</style>
