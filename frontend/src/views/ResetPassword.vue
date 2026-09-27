<script setup>
// VM 專有：從重設密碼信的連結進來（/reset-password?uid=…&token=…），設定新密碼。規則與 Change password 相同。
import { reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'
import { PASSWORD_RULE_TEXT, checkPassword } from '../passwordRule'

const route = useRoute()
const uid = typeof route.query.uid === 'string' ? route.query.uid : ''
const token = typeof route.query.token === 'string' ? route.query.token : ''
const form = reactive({ password: '', confirm: '' })
const loading = ref(false)
const doneMsg = ref('')
const errorMsg = ref(uid && token ? '' : 'This password reset link is incomplete. Request a new one.')
const linkBroken = ref(!(uid && token))

async function submit() {
  errorMsg.value = ''
  const problem = checkPassword(form.password)
  if (problem) { errorMsg.value = problem; return }
  if (form.password !== form.confirm) { errorMsg.value = 'The two passwords do not match.'; return }
  loading.value = true
  try {
    const data = await api('/api/auth/password-reset/confirm', { method: 'POST', body: { uid, token, newPassword: form.password } })
    doneMsg.value = data.message
  } catch (e) {
    if (e.code === 'invalid_reset_link') linkBroken.value = true
    errorMsg.value = e.status === 429 ? 'Too many attempts. Please wait a minute and try again.' : e.message || 'The password could not be reset.'
  } finally {
    form.password = ''
    form.confirm = ''
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <section class="login-card">
      <div class="eyebrow">再保部 | VM</div>
      <div class="brand-name">Reinsurance Department System</div>
      <h2>Set a new password</h2>
      <template v-if="doneMsg">
        <el-alert :title="doneMsg" type="success" show-icon :closable="false" />
        <router-link to="/login"><el-button class="primary-button" style="width: 100%; margin-top: 16px">Sign in</el-button></router-link>
      </template>
      <template v-else>
        <el-form v-if="!linkBroken" label-position="top" @submit.prevent="submit">
          <p class="hint">{{ PASSWORD_RULE_TEXT }}</p>
          <el-form-item label="New password">
            <el-input v-model="form.password" type="password" show-password autocomplete="new-password" autofocus />
          </el-form-item>
          <el-form-item label="Confirm new password">
            <el-input v-model="form.confirm" type="password" show-password autocomplete="new-password" @keyup.enter="submit" />
          </el-form-item>
          <el-alert v-if="errorMsg" :title="errorMsg" type="error" show-icon :closable="false" />
          <el-button class="primary-button" :loading="loading" style="width: 100%" @click="submit">Set new password</el-button>
        </el-form>
        <template v-else>
          <el-alert :title="errorMsg" type="error" show-icon :closable="false" />
          <p class="back"><router-link to="/forgot-password">Request a new link</router-link></p>
        </template>
      </template>
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
