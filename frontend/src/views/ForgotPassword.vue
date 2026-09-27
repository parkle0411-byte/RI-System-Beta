<script setup>
// VM 專有：忘記密碼（輸入帳號或 e-mail，系統寄出重設連結）。後端一律回同一句話，不透露帳號是否存在。
import { reactive, ref } from 'vue'
import { api } from '../api'

const form = reactive({ identifier: '' })
const loading = ref(false)
const sentMsg = ref('')
const errorMsg = ref('')

async function submit() {
  errorMsg.value = ''
  if (!form.identifier.trim()) {
    errorMsg.value = 'Enter your username or e-mail address.'
    return
  }
  loading.value = true
  try {
    const data = await api('/api/auth/password-reset', { method: 'POST', body: { identifier: form.identifier.trim() } })
    sentMsg.value = data.message
  } catch (e) {
    errorMsg.value = e.status === 429 ? 'Too many requests. Please wait a minute and try again.' : e.message || 'The request failed.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <section class="login-card">
      <div class="eyebrow">再保部 | VM</div>
      <div class="brand-name">Reinsurance Department System</div>
      <h2>Forgot password</h2>
      <template v-if="sentMsg">
        <el-alert :title="sentMsg" type="success" show-icon :closable="false" />
        <p class="hint">Check your e-mail and open the link to set a new password. If nothing arrives, contact a System Administrator.</p>
      </template>
      <el-form v-else label-position="top" @submit.prevent="submit">
        <p class="hint">Enter your username or the e-mail address in your Personnel record. We will send you a link to set a new password.</p>
        <el-form-item label="Username or e-mail">
          <el-input v-model="form.identifier" autocomplete="username" autofocus @keyup.enter="submit" />
        </el-form-item>
        <el-alert v-if="errorMsg" :title="errorMsg" type="error" show-icon :closable="false" />
        <el-button class="primary-button" :loading="loading" style="width: 100%" @click="submit">Send reset link</el-button>
      </el-form>
      <p class="back"><router-link to="/login">Back to sign in</router-link></p>
    </section>
  </div>
</template>

<style scoped>
.login-wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; background: var(--brand-navy); }
.login-card { width: min(400px, 100%); padding: 28px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-page); }
.login-card h2 { margin: 18px 0 16px; font-size: 18px; font-weight: 500; }
.hint { margin: 0 0 14px; color: var(--text-secondary, #666); font-size: 13px; line-height: 1.5; }
.back { margin: 16px 0 0; text-align: center; font-size: 13px; }
</style>
