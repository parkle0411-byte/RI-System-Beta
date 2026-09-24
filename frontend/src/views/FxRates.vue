<script setup>
import { computed, reactive, ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'

const CURRENCIES = ['USD', 'EUR', 'JPY', 'GBP', 'HKD', 'MYR']

const loading = ref(false)
const saving = ref(false)
const errorMsg = ref('')
const rates = ref([])
const dialogVisible = ref(false)

const form = reactive({
  yearMonth: '',
  rates: CURRENCIES.map((currency) => ({ currency, rate: null, rowVersion: null, isLocked: false }))
})

const groupedMonths = computed(() => {
  const months = [...new Set(rates.value.map((r) => r.yearMonth))]
  return months.sort().reverse()
})

function rowsForMonth(yearMonth) {
  const byCurrency = new Map(rates.value.filter((r) => r.yearMonth === yearMonth).map((r) => [r.currency, r]))
  return CURRENCIES.map((currency) => byCurrency.get(currency)).filter(Boolean)
}

async function loadRates() {
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await fetch('/api/fx-rates', { headers: { Accept: 'application/json' }, cache: 'no-store' })
    const body = await res.json()
    if (!res.ok) throw new Error(body.message || body.error || ('HTTP ' + res.status))
    rates.value = Array.isArray(body.rates) ? body.rates.map((r) => ({
      yearMonth: r.year_month,
      currency: r.currency,
      rate: r.rate,
      rowVersion: r.row_version,
      isLocked: r.is_locked,
      updatedAt: r.updated_at
    })) : []
  } catch (err) {
    errorMsg.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

function currentMonth() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

function populateForm(yearMonth) {
  const existing = rowsForMonth(yearMonth)
  const byCurrency = new Map(existing.map((r) => [r.currency, r]))
  form.rates = CURRENCIES.map((currency) => {
    const row = byCurrency.get(currency)
    return {
      currency,
      rate: row ? Number(row.rate) : null,
      rowVersion: row ? row.rowVersion : null,
      isLocked: Boolean(row?.isLocked)
    }
  })
}

function openDialog(yearMonth = null) {
  form.yearMonth = yearMonth || currentMonth()
  populateForm(form.yearMonth)
  dialogVisible.value = true
}

function onMonthChange(value) {
  if (/^\d{4}-(0[1-9]|1[0-2])$/.test(String(value || ''))) {
    populateForm(value)
  }
}

async function saveRates() {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(String(form.yearMonth || ''))) {
    ElMessage.error('請選擇有效的月份。')
    return
  }
  for (const row of form.rates) {
    const rate = Number(row.rate)
    if (!Number.isFinite(rate) || rate <= 0 || rate > 1000) {
      ElMessage.error(`${row.currency} 匯率必須大於 0 且不超過 1000。`)
      return
    }
  }
  saving.value = true
  try {
    const res = await fetch('/api/fx-rates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        yearMonth: form.yearMonth,
        rates: form.rates.map((r) => ({ currency: r.currency, rate: Number(r.rate), rowVersion: r.rowVersion }))
      })
    })
    const body = await res.json()
    if (!res.ok) throw new Error(body.message || body.error || ('HTTP ' + res.status))
    dialogVisible.value = false
    ElMessage.success('已儲存本月匯率')
    await loadRates()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : String(err))
  } finally {
    saving.value = false
  }
}

function fmtRate(value) {
  return Number(value).toFixed(6)
}

onMounted(loadRates)
</script>

<template>
  <el-card style="max-width: 960px; margin: 24px auto">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>FX Rates（每月 USD/EUR/JPY/GBP/HKD/MYR 對 TWD 匯率）</span>
        <el-button type="primary" @click="openDialog()">新增／編輯月份</el-button>
      </div>
    </template>

    <el-alert
      v-if="errorMsg"
      :title="'錯誤：' + errorMsg"
      type="error"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    />

    <div v-loading="loading">
      <div v-for="month in groupedMonths" :key="month" style="margin-bottom: 24px">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px">
          <strong>{{ month }}</strong>
          <el-button size="small" @click="openDialog(month)">編輯</el-button>
        </div>
        <el-table :data="rowsForMonth(month)" border size="small">
          <el-table-column prop="currency" label="幣別" width="100" />
          <el-table-column label="Rate to TWD">
            <template #default="{ row }">{{ fmtRate(row.rate) }}</template>
          </el-table-column>
          <el-table-column label="狀態" width="120">
            <template #default="{ row }">
              <el-tag v-if="row.isLocked" type="warning">已鎖定</el-tag>
              <el-tag v-else type="success">可編輯</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <el-empty v-if="!loading && groupedMonths.length === 0" description="尚無匯率資料" />
    </div>
  </el-card>

  <el-dialog v-model="dialogVisible" title="新增／編輯月份匯率" width="480px">
    <el-form label-width="140px">
      <el-form-item label="Performance Month">
        <el-date-picker
          v-model="form.yearMonth"
          type="month"
          value-format="YYYY-MM"
          placeholder="選擇月份"
          style="width: 100%"
          @change="onMonthChange"
        />
      </el-form-item>
      <el-form-item v-for="row in form.rates" :key="row.currency" :label="`${row.currency} Rate to TWD`">
        <el-input-number
          v-model="row.rate"
          :precision="6"
          :min="0.000001"
          :max="1000"
          :disabled="row.isLocked"
          style="width: 100%"
        />
        <el-tag v-if="row.isLocked" type="warning" size="small" style="margin-left: 8px">已鎖定</el-tag>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="saveRates">儲存</el-button>
    </template>
  </el-dialog>
</template>
