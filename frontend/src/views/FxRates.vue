<script setup>
// 移植自 Alpha index.html 的 activeView === 'fxrates' 與 app.js 的 loadFxRates()／populateFxMonth()／openFxDialog()／saveFxRate()。
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiFetch } from '../api'
import { can } from '../auth'
import { FX_CURRENCIES, currentMonth } from '../alpha/constants'
import { formatFxRate, jsonOrThrow, reportWriteError } from '../alpha/format'
import { shell } from '../alpha/shell'

const fxLoading = ref(false)
const fxSaving = ref(false)
const fxDialogVisible = ref(false)
const fxRates = ref([])
const fxForm = reactive({ yearMonth: currentMonth(), existingMonth: false, rates: FX_CURRENCIES.map((currency) => ({ currency, rate: null, rowVersion: null, isLocked: false })) })

async function loadFxRates() {
  fxLoading.value = true
  shell.error = ''
  try {
    const response = await apiFetch('/api/fx-rates', { headers: { Accept: 'application/json' } })
    const body = await response.json()
    if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
    fxRates.value = Array.isArray(body.rates) ? body.rates : []
  } catch (err) {
    shell.error = err instanceof Error ? err.message : String(err)
  } finally {
    fxLoading.value = false
  }
}

function populateFxMonth(yearMonth) {
  const existingRows = fxRates.value.filter((item) => item.yearMonth === yearMonth)
  const byCurrency = new Map(existingRows.map((item) => [item.currency, item]))
  fxForm.existingMonth = existingRows.length > 0
  fxForm.rates = FX_CURRENCIES.map((currency) => {
    const existing = byCurrency.get(currency)
    return {
      currency,
      rate: existing ? Number(existing.rate) : null,
      rowVersion: existing ? Number(existing.rowVersion) : null,
      isLocked: Boolean(existing?.isLocked)
    }
  })
}

function openFxDialog(row = null) {
  fxForm.yearMonth = row?.yearMonth || currentMonth()
  populateFxMonth(fxForm.yearMonth)
  fxDialogVisible.value = true
}

function onFxMonthChange(yearMonth) {
  if (/^\d{4}-(0[1-9]|1[0-2])$/.test(String(yearMonth || ''))) {
    populateFxMonth(yearMonth)
  }
}

async function saveFxRate() {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(String(fxForm.yearMonth || ''))) {
    ElMessage.error('Select a valid Performance month.')
    return
  }
  for (const row of fxForm.rates) {
    const rate = Number(row.rate)
    if (!Number.isFinite(rate) || rate <= 0 || rate > 1000) {
      ElMessage.error(`${row.currency} Rate to TWD is required and must be no more than 1000.`)
      return
    }
  }
  fxSaving.value = true
  shell.error = ''
  try {
    await jsonOrThrow(await apiFetch('/api/fx-rates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        yearMonth: fxForm.yearMonth,
        rates: fxForm.rates.map((row) => ({ currency: row.currency, rate: Number(row.rate), rowVersion: row.rowVersion }))
      })
    }))
    fxDialogVisible.value = false
    ElMessage.success('Monthly FX rates saved')
    await loadFxRates()
  } catch (err) {
    shell.error = err instanceof Error ? err.message : String(err)
    reportWriteError(err, () => loadFxRates())
  } finally {
    fxSaving.value = false
  }
}

onMounted(loadFxRates)
</script>

<template>
  <!-- Development presents FX Rates as one operational panel. -->
  <section class="table-card" v-loading="fxLoading">
    <div class="section-heading"><div><h2>FX Rates</h2><p>Official monthly rates to TWD for USD, EUR, JPY, GBP, HKD and MYR. TWD is always 1; closed months are locked.</p></div><div><el-button v-if="can('fx.write')" class="primary-button" @click="openFxDialog()">+ Set monthly rates</el-button><el-button class="secondary-button" :loading="fxLoading" @click="loadFxRates">Refresh</el-button></div></div>
    <el-table :data="fxRates" class="case-table" row-key="id" empty-text="No monthly FX rates set yet.">
      <el-table-column prop="yearMonth" label="Performance month" min-width="180"><template #default="{ row }"><span class="case-ref">{{ row.yearMonth }}</span></template></el-table-column>
      <el-table-column prop="currency" label="Currency" width="130"></el-table-column>
      <el-table-column label="Rate to TWD" min-width="180" align="right"><template #default="{ row }">{{ formatFxRate(row.rate) }}</template></el-table-column>
      <el-table-column prop="rowVersion" label="Version" width="110"></el-table-column>
      <el-table-column label="Status" width="130"><template #default="{ row }"><span class="status-badge" :class="row.isLocked ? 'status-archived' : 'status-posted'">{{ row.isLocked ? 'Locked' : 'Open' }}</span></template></el-table-column>
      <el-table-column label="Action" width="120"><template #default="{ row }"><el-button v-if="can('fx.write')" text type="primary" :disabled="row.isLocked" @click="openFxDialog(row)">Edit month</el-button></template></el-table-column>
    </el-table>
  </section>
  <el-dialog v-model="fxDialogVisible" class="master-dialog" width="min(680px, 94vw)" :close-on-click-modal="false">
    <template #header><div class="review-heading"><span class="pending-badge">{{ fxForm.existingMonth ? 'Versioned monthly update' : 'New monthly rates' }}</span><h2>Performance month FX rates</h2><p>All six Rate to TWD values are required and saved together.</p></div></template>
    <el-form label-position="top" @submit.prevent>
      <el-form-item label="Performance month" required><el-date-picker v-model="fxForm.yearMonth" type="month" value-format="YYYY-MM" format="MMM YYYY" placeholder="YYYY-MM" style="width:100%" @change="onFxMonthChange"></el-date-picker></el-form-item>
      <el-table :data="fxForm.rates" row-key="currency" class="case-table" size="small">
        <el-table-column prop="currency" label="Currency" width="150"><template #default="{ row }"><strong>{{ row.currency }}</strong></template></el-table-column>
        <el-table-column label="Rate to TWD" min-width="280"><template #default="{ row }"><el-input-number v-model="row.rate" :min="0.000001" :max="1000" :precision="6" :controls="false" :disabled="row.isLocked" style="width:100%"></el-input-number></template></el-table-column>
      </el-table>
    </el-form>
    <template #footer><div class="review-footer"><p>Order: USD, EUR, JPY, GBP, HKD, MYR. Blank rates cannot be saved.</p><div><el-button class="secondary-button" @click="fxDialogVisible = false">Cancel</el-button><el-button class="primary-button" :loading="fxSaving" :disabled="fxForm.rates.some(row => row.isLocked)" @click="saveFxRate">Save monthly rates</el-button></div></div></template>
  </el-dialog>
</template>
