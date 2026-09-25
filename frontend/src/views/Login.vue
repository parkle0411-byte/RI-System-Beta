<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { login } from '../auth'

const router = useRouter()
const route = useRoute()

const form = reactive({ username: '', password: '' })
const loading = ref(false)
const errorMsg = ref('')

const MESSAGES = {
  INVALID_CREDENTIALS: '帳號或密碼錯誤。',
  PERSONNEL_NOT_LINKED: '此帳號尚未對應到人員資料，請聯絡系統管理員。',
  PERSONNEL_INACTIVE: '此人員已停用，無法登入。',
  ACCOUNT_INACTIVE: '此帳號尚未啟用或已被停用，請聯絡系統管理員。',
}

async function submit() {
  errorMsg.value = ''
  if (!form.username.trim() || !form.password) {
    errorMsg.value = '請輸入帳號與密碼。'
    return
  }
  loading.value = true
  try {
    await login(form.username.trim(), form.password)
    const target = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/')
      ? route.query.redirect
      : '/'
    router.replace(target)
  } catch (e) {
    errorMsg.value = MESSAGES[e.code] || e.message || '登入失敗'
  } finally {
    form.password = ''
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <template #header>再保系統 (RI System) 登入</template>
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="帳號">
          <el-input v-model="form.username" autocomplete="username" autofocus />
        </el-form-item>
        <el-form-item label="密碼">
          <el-input v-model="form.password" type="password" show-password autocomplete="current-password" @keyup.enter="submit" />
        </el-form-item>
        <el-alert v-if="errorMsg" :title="errorMsg" type="error" show-icon :closable="false" style="margin-bottom: 16px" />
        <el-button type="primary" :loading="loading" style="width: 100%" @click="submit">登入</el-button>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.login-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f7fa;
}
.login-card {
  width: 380px;
}
</style>
