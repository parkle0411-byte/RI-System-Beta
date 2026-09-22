<script setup>
import { ref, onMounted } from 'vue'

const loading = ref(false)
const health = ref(null)
const errorMsg = ref('')

async function checkHealth() {
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await fetch('/health/', { cache: 'no-store' })
    if (!res.ok) throw new Error('HTTP ' + res.status)
    health.value = await res.json()
  } catch (e) {
    health.value = null
    errorMsg.value = String(e.message || e)
  } finally {
    loading.value = false
  }
}

onMounted(checkHealth)
</script>

<template>
  <el-container style="min-height: 100vh; background: #f5f7fa">
    <el-header style="background: #303133; color: #fff; display: flex; align-items: center">
      <span style="font-size: 18px">RI System（測試環境）</span>
    </el-header>
    <el-main>
      <el-card style="max-width: 640px; margin: 24px auto">
        <template #header>系統連線狀態</template>

        <el-descriptions :column="1" border>
          <el-descriptions-item label="前端 / Nginx">
            <el-tag type="success">正常（本頁已載入）</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="Django 後端">
            <el-tag v-if="health && health.status === 'ok'" type="success">正常</el-tag>
            <el-tag v-else-if="loading" type="info">檢查中…</el-tag>
            <el-tag v-else type="danger">無法連線</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="資料庫">
            <el-tag v-if="health && health.database === 'ok'" type="success">正常</el-tag>
            <el-tag v-else-if="loading" type="info">檢查中…</el-tag>
            <el-tag v-else type="danger">未知</el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <el-alert
          v-if="errorMsg"
          :title="'錯誤：' + errorMsg"
          type="error"
          show-icon
          :closable="false"
          style="margin-top: 16px"
        />

        <el-button type="primary" :loading="loading" style="margin-top: 16px" @click="checkHealth">
          重新檢查
        </el-button>
      </el-card>
    </el-main>
  </el-container>
</template>
