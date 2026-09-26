<script setup>
// 移植自 Alpha index.html 的 activeView === 'production' 與 app.js 的 loadProductionPreview()／productionAction()／
// excludeProductionRow()／generateProductionReport()／closeProductionReport()／downloadProductionReport()。
// Excel 由 Alpha 的 public/production-xlsx.js 產生（逐位元組相同的副本在 src/alpha/production-xlsx.js），
// 它需要的 JSZip 用 npm 套件 jszip 3.10.1（與 Alpha 的 vendor/jszip.min.js 同版）。
//
// 與 Alpha 不同的地方（都記在 MIGRATION-STATUS.md）：
//   - fetch() → apiFetch()（補上 CSRF 與同源 cookie）
//   - 預設月份是「台北時間的上個月」（Alpha 用 UTC）
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import JSZip from 'jszip'
import '../alpha/production-xlsx.js'
import { apiFetch } from '../api'
import { formatAmount, formatCurrency, formatDateTime } from '../alpha/format'
import { shell } from '../alpha/shell'

window.JSZip = JSZip

function previousMonth() {
  const [year, month] = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit' }).format(new Date()).split('-').map(Number)
  return new Date(Date.UTC(year, month - 2, 1)).toISOString().slice(0, 7)
}

const productionLoading = ref(false)
const productionSaving = ref('')
const productionMonth = ref(previousMonth())
const productionPreview = ref({
  headers: [], rows: [], excluded: [], versions: [], sourceSignature: '',
  summary: { rowCount: 0, excludedRowCount: 0, premiumNtd: 0, incomeNtd: 0, missingRateCurrencies: [] },
  scope: { readOnly: false, canOperate: false, canClose: false, monthClosed: false, fxLocked: false, canGenerate: false, canCloseLatest: false }
})

async function loadProductionPreview() {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(String(productionMonth.value || ''))) {
    shell.error = 'Report month must use YYYY-MM.'
    return
  }
  productionLoading.value = true
  shell.error = ''
  try {
    const response = await apiFetch('/api/production-report?month=' + encodeURIComponent(productionMonth.value), { headers: { Accept: 'application/json' } })
    const body = await response.json()
    if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
    productionPreview.value = body
  } catch (err) {
    shell.error = err instanceof Error ? err.message : String(err)
  } finally {
    productionLoading.value = false
  }
}

async function productionAction(action, payload = {}) {
  productionSaving.value = action
  shell.error = ''
  try {
    const response = await apiFetch('/api/production-report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ action, month: productionMonth.value, ...payload })
    })
    const body = await response.json()
    if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
    await loadProductionPreview()
    return body
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    shell.error = message
    ElMessage.error(message)
    return null
  } finally { productionSaving.value = '' }
}

async function excludeProductionRow(row, scope) {
  let answer
  try {
    answer = await ElMessageBox.prompt(
      `Reason for excluding ${scope === 'case' ? 'this case / installment' : 'this reinsurer'} (it will move to the next open month):`,
      'Exclude and defer',
      { confirmButtonText: 'Exclude', cancelButtonText: 'Cancel', inputValidator: (value) => String(value || '').trim() ? true : 'Reason is required.' }
    )
  } catch { return }
  const body = await productionAction('exclude', { rowId: row.id, scope, reason: answer.value })
  if (body) ElMessage.success(`Item deferred to ${body.exclusion.deferred_to}`)
}

async function generateProductionReport() {
  const body = await productionAction('generate', { sourceSignature: productionPreview.value.sourceSignature })
  if (body) ElMessage.success(`Production Report ${body.report.month} V${body.report.version} generated`)
}

async function closeProductionReport(report) {
  try {
    await ElMessageBox.confirm(
      `Close ${report.month} using V${report.version}? This cannot be reopened.`,
      'Close Production month',
      { confirmButtonText: 'Close month', cancelButtonText: 'Cancel', type: 'warning' }
    )
  } catch { return }
  const body = await productionAction('close', {
    reportUid: report.reportUid,
    rowVersion: report.rowVersion,
    sourceSignature: productionPreview.value.sourceSignature
  })
  if (body) ElMessage.success(`Production Report ${body.month} closed · ${body.confirmedCases} case(s) fully Confirmed`)
}

async function downloadProductionReport(report) {
  try {
    if (!window.RIProductionXlsx) throw new Error('Production Report Excel generator is unavailable.')
    await window.RIProductionXlsx.download(report, productionPreview.value.headers)
    ElMessage.success(`Production Report ${report.month} V${report.version} saved`)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : String(err))
  }
}

onMounted(loadProductionPreview)
</script>

<template>
  <div class="overview-stack">
    <section class="table-card production-report-card" v-loading="productionLoading">
      <div class="section-heading production-heading">
        <div><span class="pending-badge">Versioned monthly close</span><h2>Production Report</h2><p>Preview current rows, defer exceptions, generate an immutable Excel version, then close the latest unchanged version.</p></div>
        <div class="production-month-control"><label for="production-month">Report month</label><el-date-picker id="production-month" v-model="productionMonth" type="month" value-format="YYYY-MM" format="MMM YYYY" placeholder="YYYY-MM"></el-date-picker><el-button class="primary-button" :loading="productionLoading" @click="loadProductionPreview">Preview</el-button></div>
      </div>
      <el-alert v-if="productionPreview.scope?.monthClosed" class="case-readiness-alert" type="success" :closable="false" show-icon :title="productionMonth + ' is closed'" description="The report version and source rows are fixed. The monthly FX rate is locked."></el-alert>
      <el-alert v-else-if="productionPreview.summary?.missingRateCurrencies?.length" class="case-readiness-alert" type="warning" :closable="false" show-icon :title="'Official ' + productionMonth + ' exchange rate required for ' + productionPreview.summary.missingRateCurrencies.join(', ')" description="Preview remains available, but report generation is blocked until the official monthly rate is stored in FX Rates."></el-alert>
      <div class="document-summary production-summary">
        <article><span>Included rows</span><strong>{{ productionPreview.summary?.rowCount || 0 }}</strong></article>
        <article><span>Deferred rows</span><strong>{{ productionPreview.summary?.excludedRowCount || 0 }}</strong></article>
        <article><span>Premium (NTD)</span><strong>{{ formatCurrency(productionPreview.summary?.premiumNtd, 'TWD') }}</strong></article>
        <article><span>Income (NTD)</span><strong>{{ formatCurrency(productionPreview.summary?.incomeNtd, 'TWD') }}</strong></article>
      </div>
      <div class="production-table-wrap">
        <el-table :data="productionPreview.rows || []" class="production-table" row-key="id" empty-text="No eligible Production Report rows for this month.">
          <el-table-column prop="originalInsured" label="Original Insured" width="210"></el-table-column>
          <el-table-column prop="reinsured" label="Reinsured" width="190"></el-table-column>
          <el-table-column prop="reinsurer" label="Reinsurer / RI Broker" width="210"></el-table-column>
          <el-table-column prop="classCode" label="Class" width="100"></el-table-column>
          <el-table-column prop="type" label="Type" width="80"></el-table-column>
          <el-table-column prop="currency" label="Currency" width="100"></el-table-column>
          <el-table-column label="Exch. Rate" width="110" align="right"><template #default="{ row }">{{ row.missingRate ? 'Required' : formatAmount(row.rate) }}</template></el-table-column>
          <el-table-column prop="ae" label="A/E" width="130"></el-table-column>
          <el-table-column prop="effDate" label="Eff Date" width="120"></el-table-column>
          <el-table-column prop="expDate" label="Exp Date" width="120"></el-table-column>
          <el-table-column label="Comm (%)" width="110" align="right"><template #default="{ row }">{{ formatAmount(row.comm) }}%</template></el-table-column>
          <el-table-column label="Premium (NTD)" width="150" align="right"><template #default="{ row }">{{ row.premium === null ? '—' : formatCurrency(row.premium, 'TWD') }}</template></el-table-column>
          <el-table-column label="Income (NTD)" width="150" align="right"><template #default="{ row }">{{ row.income === null ? '—' : formatCurrency(row.income, 'TWD') }}</template></el-table-column>
          <el-table-column prop="policyNo" label="Policy No" width="170"></el-table-column>
          <el-table-column prop="endorseNo" label="Endorse No" width="120"><template #default="{ row }">{{ row.endorseNo || '—' }}</template></el-table-column>
          <el-table-column prop="remark" label="Remark" width="90"></el-table-column>
          <el-table-column prop="tranxDate" label="Tranx Date" width="120"></el-table-column>
          <el-table-column v-if="productionPreview.scope?.canOperate && !productionPreview.scope?.monthClosed" label="Action" width="210"><template #default="{ row }"><el-button text type="primary" :disabled="Boolean(productionSaving)" @click="excludeProductionRow(row, 'reinsurer')">Exclude R/I</el-button><el-button text type="warning" :disabled="Boolean(productionSaving)" @click="excludeProductionRow(row, 'case')">Exclude case</el-button></template></el-table-column>
        </el-table>
      </div>
    </section>

    <section v-if="(productionPreview.excluded || []).length" class="table-card">
      <div class="section-heading"><div><h2>Excluded and deferred items</h2><p>Omitted from this month's Excel and moved to the next open month.</p></div><span class="pending-badge">{{ productionPreview.excluded.length }} rows</span></div>
      <el-table :data="productionPreview.excluded" class="case-table" row-key="id">
        <el-table-column prop="originalInsured" label="Original Insured" min-width="210"></el-table-column>
        <el-table-column prop="reinsurer" label="Reinsurer / RI Broker" min-width="210"></el-table-column>
        <el-table-column prop="policyNo" label="Policy No" min-width="170"></el-table-column>
        <el-table-column label="Scope" width="130"><template #default="{ row }">{{ row.exclusion?.scope === 'case' ? 'Case / installment' : 'Reinsurer' }}</template></el-table-column>
        <el-table-column label="Reason" min-width="240"><template #default="{ row }">{{ row.exclusion?.reason || '—' }}</template></el-table-column>
        <el-table-column label="Deferred to" width="130"><template #default="{ row }">{{ row.exclusion?.deferredTo || '—' }}</template></el-table-column>
      </el-table>
    </section>

    <section class="table-card">
      <div class="section-heading">
        <div><h2>Report versions</h2><p>Each generated version retains its exact included and excluded row snapshots.</p></div>
        <el-button v-if="productionPreview.scope?.canOperate && !productionPreview.scope?.monthClosed" class="primary-button" :loading="productionSaving === 'generate'" :disabled="!productionPreview.scope?.canGenerate || Boolean(productionSaving)" @click="generateProductionReport">Generate Production Report</el-button>
      </div>
      <el-table :data="productionPreview.versions || []" class="case-table" row-key="reportUid" empty-text="No versions generated yet.">
        <el-table-column label="Version" width="110"><template #default="{ row }"><span class="case-ref">V{{ row.version }}</span></template></el-table-column>
        <el-table-column label="Status" width="130"><template #default="{ row }"><span class="status-badge" :class="row.status === 'closed' ? 'status-closed' : row.status === 'valid' ? 'status-posted' : 'status-archived'">{{ row.status }}</span></template></el-table-column>
        <el-table-column label="Generated" min-width="190"><template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template></el-table-column>
        <el-table-column label="Rows" width="100"><template #default="{ row }">{{ (row.rows || []).length }}</template></el-table-column>
        <el-table-column label="Closed" min-width="180"><template #default="{ row }">{{ row.closedAt ? formatDateTime(row.closedAt) : '—' }}</template></el-table-column>
        <el-table-column label="Action" min-width="250"><template #default="{ row }"><el-button text type="primary" @click="downloadProductionReport(row)">Download XLSX</el-button><el-button v-if="productionPreview.scope?.canClose && row.status === 'valid' && row === productionPreview.versions[0]" text type="success" :loading="productionSaving === 'close'" :disabled="!productionPreview.scope?.canCloseLatest || Boolean(productionSaving)" @click="closeProductionReport(row)">Close month</el-button></template></el-table-column>
      </el-table>
    </section>
  </div>
</template>
