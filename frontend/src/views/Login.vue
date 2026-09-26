<script setup>
// VM 專有（Alpha 的登入由 Hatchable 代管）。外觀沿用 Alpha 的樣式變數與按鈕。
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { login } from '../auth'

const router = useRouter()
const route = useRoute()

const form = reactive({ username: '', password: '' })
const loading = ref(false)
const errorMsg = ref('')

const MESSAGES = {
  INVALID_CREDENTIALS: 'Incorrect username or password.',
  PERSONNEL_NOT_LINKED: 'This account is not linked to a Personnel record. Contact the System Administrator.',
  PERSONNEL_INACTIVE: 'This Personnel record is inactive. Sign-in is not available.',
  ACCOUNT_INACTIVE: 'This account is not active or has been disabled. Contact the System Administrator.',
}

async function submit() {
  errorMsg.value = ''
  if (!form.username.trim() || !form.password) {
    errorMsg.value = 'Enter your username and password.'
    return
  }
  loading.value = true
  try {
    await login(form.username.trim(), form.password)
    const target = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/')
      ? route.query.redirect
      : '/'
    // /admin/ 不是 SPA 的路由（Django 的唯讀管理），要整頁跳轉
    if (target.startsWith('/admin/')) window.location.assign(target)
    else router.replace(target)
  } catch (e) {
    errorMsg.value = MESSAGES[e.code] || e.message || 'Sign-in failed.'
  } finally {
    form.password = ''
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <section class="login-card">
      <div class="eyebrow">再保部 | VM</div>
      <div class="brand-name">Reinsurance Department System</div>
      <h2>Sign in</h2>
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="Username">
          <el-input v-model="form.username" autocomplete="username" autofocus />
        </el-form-item>
        <el-form-item label="Password">
          <el-input v-model="form.password" type="password" show-password autocomplete="current-password" @keyup.enter="submit" />
        </el-form-item>
        <el-alert v-if="errorMsg" :title="errorMsg" type="error" show-icon :closable="false" />
        <el-button class="primary-button" :loading="loading" style="width: 100%" @click="submit">Sign in</el-button>
      </el-form>
    </section>
  </div>
</template>

<style scoped>
.login-wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; background: var(--brand-navy); }
.login-card { width: min(400px, 100%); padding: 28px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-page); }
.login-card h2 { margin: 18px 0 16px; font-size: 18px; font-weight: 500; }
</style>
