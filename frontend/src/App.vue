<script setup>
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { auth, can, changePassword, logout } from './auth'
import { PASSWORD_RULE_TEXT, checkPassword } from './passwordRule'

const router = useRouter()

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
    ElMessage.error('兩次輸入的新密碼不一致。')
    return
  }
  pwdSaving.value = true
  try {
    await changePassword(pwd.current, pwd.next)
    ElMessage.success('密碼已更新')
    pwdOpen.value = false
  } catch (e) {
    ElMessage.error(e.message || '密碼更新失敗')
  } finally {
    pwdSaving.value = false
  }
}
</script>

<template>
  <!-- 登入頁不顯示導覽列 -->
  <router-view v-if="!auth.principal" />

  <el-container v-else style="min-height: 100vh; background: #f5f7fa">
    <el-header style="background: #303133; color: #fff; display: flex; align-items: center; gap: 24px">
      <span style="font-size: 18px">RI System（測試環境）</span>
      <el-menu v-if="!forced" mode="horizontal" background-color="#303133" text-color="#fff" router style="flex: 1; border: none">
        <el-menu-item index="/">系統狀態</el-menu-item>
        <el-menu-item v-if="can('fx.read')" index="/fx-rates">FX Rates</el-menu-item>
        <el-menu-item v-if="can('mdm.read')" index="/master-data">Master Data</el-menu-item>
        <el-menu-item v-if="can('personnel.read')" index="/personnel">Personnel</el-menu-item>
      </el-menu>
      <span v-if="forced" style="flex: 1" />
      <span style="font-size: 14px">{{ auth.principal.name }}（{{ auth.principal.roleLabel }}）</span>
      <el-button v-if="!forced" size="small" @click="openPassword">修改密碼</el-button>
      <el-button size="small" @click="doLogout">登出</el-button>
    </el-header>
    <el-main>
      <router-view v-if="!forced" />
    </el-main>
  </el-container>

  <el-dialog
    v-model="pwdVisible"
    :title="forced ? '請先修改密碼' : '修改密碼'"
    width="420px"
    :close-on-click-modal="!forced"
    :close-on-press-escape="!forced"
    :show-close="!forced"
  >
    <el-alert
      v-if="forced"
      type="warning" show-icon :closable="false" style="margin-bottom: 12px"
      title="您目前使用的是管理員提供的暫時密碼。請先設定自己的新密碼（不能與暫時密碼相同），才能使用系統。"
    />
    <el-alert type="info" show-icon :closable="false" :title="PASSWORD_RULE_TEXT" style="margin-bottom: 16px" />
    <el-form label-width="110px" @submit.prevent="savePassword">
      <el-form-item label="目前密碼">
        <el-input v-model="pwd.current" type="password" show-password autocomplete="current-password" />
      </el-form-item>
      <el-form-item label="新密碼">
        <el-input v-model="pwd.next" type="password" show-password autocomplete="new-password" placeholder="至少 8 個字元，含英文字母與數字" />
      </el-form-item>
      <el-form-item label="確認新密碼">
        <el-input v-model="pwd.confirm" type="password" show-password autocomplete="new-password" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button v-if="forced" @click="doLogout">登出</el-button>
      <el-button v-else @click="pwdVisible = false">取消</el-button>
      <el-button type="primary" :loading="pwdSaving" @click="savePassword">更新</el-button>
    </template>
  </el-dialog>
</template>
