<script setup>
// 移植自 Alpha index.html 的 activeView === 'accounting' 與 app.js 的 loadAccounting()／openSchedulePayment()／
// recordSchedulePayment()／reverseSchedulePayment()／paymentStatusLabel()／paymentStatusType()／openAccountingCase()。
//
// 與 Alpha 不同的地方（都記在 MIGRATION-STATUS.md）：
//   - fetch() → apiFetch()（補上 CSRF 與同源 cookie）
//   - 預設付款日期用台北的今天（Alpha 用 UTC，台灣早上 8 點前會變成前一天）
//   - 「開啟案件」導向 /cases?case=…&tab=soa（Alpha 在同一頁切換畫面）
//   - 「Partial payment」只在真的部分付款時顯示（Alpha 的 v-if 只套到 <br>，每一列都會顯示這行字）
//   - Alpha 的 settleSelectedTransactions() 呼叫不存在的 API 動作，畫面上也沒有入口，不移植
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiFetch } from '../api'
import { can } from '../auth'
import { formatMoney, reportWriteError } from '../alpha/format'
import { shell } from '../alpha/shell'

const router = useRouter()
const accountingLoading = ref(false)
const accountingSaving = ref(false)
const accountingRows = ref([])
const accountingCurrencies = ref([])
const accountingScope = ref({ canEdit: false })
const accountingFilters = reactive({ ref: '', reinsurer: '', currency: '', from: '', to: '', leg: '', settlement: '' })
const accountingPaymentDialogVisible = ref(false)
const accountingPaymentRow = ref(null)
const schedulePaymentForm = reactive({ paymentDate: taipeiToday(), amount: null, note: '' })

function taipeiToday() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
}

const filteredAccountingRows = computed(() => accountingRows.value.filter((row) => {
  const filters = accountingFilters
  if (filters.ref && !String(row.twRef || '').toLowerCase().includes(filters.ref.toLowerCase())) return false
  if (filters.reinsurer && !String(row.reinsurer || '').toLowerCase().includes(filters.reinsurer.toLowerCase())) return false
  if (filters.currency && row.currency !== filters.currency) return false
  if (filters.leg && String(row.legType || '') !== filters.leg && !String(row.legType || '').startsWith(filters.leg)) return false
  if (filters.settlement && row.settlement !== filters.settlement) return false
  const announced = String(row.announcedAt || '').slice(0, 10)
  if (filters.from && announced && announced < filters.from) return false
  if (filters.to && announced && announced > filters.to) return false
  return true
}))

async function loadAccounting() {
  accountingLoading.value = true
  shell.error = ''
  try {
    const response = await apiFetch('/api/accounting', { headers: { Accept: 'application/json' } })
    const body = await response.json()
    if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
    accountingRows.value = Array.isArray(body.rows) ? body.rows : []
    accountingCurrencies.value = Array.isArray(body.currencies) ? body.currencies : []
    accountingScope.value = body.scope || { canEdit: false }
  } catch (err) {
    shell.error = err instanceof Error ? err.message : String(err)
    ElMessage.error(shell.error)
  } finally { accountingLoading.value = false }
}

function openSchedulePayment(row) {
  if (!row || row.source !== 'premium' || row.reviewRequired) return
  if (Number(row.outstanding || 0) <= 0 && Number(row.paid || 0) <= 0) return
  accountingPaymentRow.value = row
  schedulePaymentForm.paymentDate = taipeiToday()
  schedulePaymentForm.amount = Number(row.outstanding || 0)
  schedulePaymentForm.note = ''
  accountingPaymentDialogVisible.value = true
}

async function postAccounting(payload) {
  const response = await apiFetch('/api/accounting', {
    method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(payload)
  })
  const body = await response.json()
  if (!response.ok) {
    const requestErr = new Error(body.message || body.error || ('HTTP ' + response.status))
    requestErr.status = response.status
    throw requestErr
  }
  return body
}

async function recordSchedulePayment() {
  const row = accountingPaymentRow.value
  const amount = Number(schedulePaymentForm.amount)
  if (!row || !Number.isFinite(amount) || amount <= 0) return ElMessage.warning('Enter a positive payment amount.')
  if (amount - Number(row.outstanding || 0) > 0.004) return ElMessage.warning('Payment cannot exceed the selected installment balance.')
  accountingSaving.value = true
  try {
    await postAccounting({
      action: 'record_payment', caseUid: row.caseUid, rowVersion: row.caseRowVersion,
      scheduleKey: row.scheduleKey, paymentDate: schedulePaymentForm.paymentDate,
      amount, note: schedulePaymentForm.note
    })
    accountingPaymentDialogVisible.value = false
    ElMessage.success('Payment recorded against the selected installment and party')
    await loadAccounting()
  } catch (err) {
    reportWriteError(err, () => loadAccounting())
    await loadAccounting()
  } finally { accountingSaving.value = false }
}

async function reverseSchedulePayment(row, entry) {
  if (!row || !entry?.id) return
  try {
    await ElMessageBox.confirm(
      'This keeps the original payment and appends an immutable reversal entry.',
      'Reverse payment',
      { confirmButtonText: 'Create reversal', cancelButtonText: 'Cancel', type: 'warning' }
    )
  } catch { return }
  accountingSaving.value = true
  try {
    await postAccounting({
      action: 'reverse_payment', caseUid: row.caseUid, rowVersion: row.caseRowVersion,
      entryId: entry.id, paymentDate: taipeiToday(),
      note: 'Correction reversal'
    })
    accountingPaymentDialogVisible.value = false
    ElMessage.success('Reversal entry created')
    await loadAccounting()
  } catch (err) {
    reportWriteError(err, () => loadAccounting())
    await loadAccounting()
  } finally { accountingSaving.value = false }
}

function paymentStatusLabel(value) {
  return ({ pending_review: 'Pending review', upcoming: 'Upcoming', due_today: 'Due today', overdue: 'Overdue', partially_paid: 'Partially paid', settled: 'Settled' })[value] || value || '—'
}

function paymentStatusType(value) {
  return value === 'settled' ? 'success' : value === 'overdue' ? 'danger' : value === 'due_today' ? 'warning' : value === 'pending_review' ? 'info' : ''
}

function openAccountingCase(row) {
  router.push({ path: '/cases', query: { case: row.caseUid, tab: 'soa' } })
}

onMounted(loadAccounting)
</script>

<template>
  <div class="overview-stack">
    <section class="table-card">
      <div class="section-heading">
        <div><span class="pending-badge">Payment schedule</span><h2>Accounting filters</h2><p>Premium balances are split by installment and payment party. Due time is 12:00 Taiwan.</p></div>
        <el-button class="secondary-button" :loading="accountingLoading" @click="loadAccounting">Refresh</el-button>
      </div>
      <div class="form-grid cols-3">
        <el-form-item label="TW Ref"><el-input v-model="accountingFilters.ref" clearable placeholder="e.g. TW..."></el-input></el-form-item>
        <el-form-item label="Reinsurer / R/I Broker"><el-input v-model="accountingFilters.reinsurer" clearable></el-input></el-form-item>
        <el-form-item label="Currency"><el-select v-model="accountingFilters.currency" clearable placeholder="All"><el-option v-for="currency in accountingCurrencies" :key="currency" :label="currency" :value="currency"></el-option></el-select></el-form-item>
        <el-form-item label="Announced from"><el-date-picker v-model="accountingFilters.from" type="date" value-format="YYYY-MM-DD" placeholder="YYYY-MM-DD"></el-date-picker></el-form-item>
        <el-form-item label="Announced to"><el-date-picker v-model="accountingFilters.to" type="date" value-format="YYYY-MM-DD" placeholder="YYYY-MM-DD"></el-date-picker></el-form-item>
        <el-form-item label="Payment party"><el-select v-model="accountingFilters.leg" clearable placeholder="All"><el-option label="Cedant" value="Cedant"></el-option><el-option label="Reinsurer" value="Reinsurer"></el-option><el-option label="Claim Leg 1" value="Claim Leg 1"></el-option><el-option label="Claim Leg 2" value="Claim Leg 2"></el-option></el-select></el-form-item>
        <el-form-item label="Settlement"><el-select v-model="accountingFilters.settlement" clearable placeholder="All"><el-option label="Open" value="open"></el-option><el-option label="Settled" value="settled"></el-option></el-select></el-form-item>
      </div>
    </section>

    <section class="table-card" v-loading="accountingLoading">
      <div class="section-heading">
        <div><h2>Payment schedule ({{ filteredAccountingRows.length }})</h2><p>Partial payments must be assigned to one installment and one party. Corrections append a reversal; history is never overwritten.</p></div>
      </div>
      <el-table :data="filteredAccountingRows" row-key="key" empty-text="No payment schedule rows match these filters.">
        <el-table-column prop="twRef" label="TW Ref / installment" min-width="155"><template #default="{ row }"><el-button v-if="can('cases.read.all')" text class="table-action" @click="openAccountingCase(row)">{{ row.twRef || '—' }}</el-button><span v-else>{{ row.twRef || '—' }}</span><br><small>{{ row.installmentLabel || (row.source === 'claim' ? 'Claim' : 'Premium') }}</small></template></el-table-column>
        <el-table-column prop="partyName" label="Payment party" min-width="150"><template #default="{ row }">{{ row.partyName || row.reinsurer || row.reinsured || '—' }}<br><small>{{ row.legType }}</small></template></el-table-column>
        <el-table-column label="Base / due" min-width="145"><template #default="{ row }">{{ row.baseDate || '—' }}<br><small>{{ row.dueDate ? row.dueDate + ' · ' + row.dueTime : 'Pending review' }}</small></template></el-table-column>
        <el-table-column label="Terms" width="75" align="right"><template #default="{ row }">{{ row.termsDays == null ? '—' : row.termsDays + 'd' }}</template></el-table-column>
        <el-table-column label="Scheduled" min-width="100" align="right"><template #default="{ row }">{{ formatMoney(row.amount) }}</template></el-table-column>
        <el-table-column label="Paid" min-width="95" align="right"><template #default="{ row }">{{ formatMoney(row.paid) }}</template></el-table-column>
        <el-table-column label="Outstanding" min-width="110" align="right"><template #default="{ row }"><strong>{{ row.currency }} {{ formatMoney(row.outstanding) }}</strong></template></el-table-column>
        <el-table-column label="Status" min-width="120"><template #default="{ row }"><el-tag :type="paymentStatusType(row.paymentStatus)" effect="plain">{{ paymentStatusLabel(row.paymentStatus) }}</el-tag><template v-if="row.partial"><br><small>Partial payment</small></template></template></el-table-column>
        <el-table-column v-if="accountingScope.canEdit" label="Action" min-width="110"><template #default="{ row }"><el-button v-if="row.source === 'premium' && !row.reviewRequired && (Number(row.outstanding || 0) > 0 || Number(row.paid || 0) > 0)" text :type="Number(row.outstanding || 0) > 0 ? 'primary' : 'default'" @click="openSchedulePayment(row)">{{ Number(row.outstanding || 0) > 0 ? 'Record payment' : 'View / reverse' }}</el-button></template></el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="accountingPaymentDialogVisible" class="review-dialog" width="min(720px, 94vw)" :close-on-click-modal="false">
      <template #header><div class="review-heading"><span class="pending-badge">Selected installment and party</span><h2>{{ accountingPaymentRow && Number(accountingPaymentRow.outstanding || 0) > 0 ? 'Record partial payment' : 'Payment history' }}</h2><p v-if="accountingPaymentRow">{{ accountingPaymentRow.twRef }} · {{ accountingPaymentRow.installmentLabel }} · {{ accountingPaymentRow.partyName }}</p></div></template>
      <el-form label-position="top" v-if="accountingPaymentRow">
        <template v-if="Number(accountingPaymentRow.outstanding || 0) > 0">
          <div class="form-grid cols-2">
            <el-form-item label="Payment date" required><el-date-picker v-model="schedulePaymentForm.paymentDate" type="date" value-format="YYYY-MM-DD" placeholder="YYYY-MM-DD"></el-date-picker></el-form-item>
            <el-form-item label="Amount" required><el-input-number v-model="schedulePaymentForm.amount" :min="0.01" :max="Number(accountingPaymentRow.outstanding || 0)" :precision="2" :controls="false"></el-input-number></el-form-item>
          </div>
          <el-form-item label="Note"><el-input v-model="schedulePaymentForm.note" maxlength="1000"></el-input></el-form-item>
          <el-alert type="info" :closable="false" show-icon :title="'Outstanding after this entry: ' + accountingPaymentRow.currency + ' ' + formatMoney(Math.max(0, Number(accountingPaymentRow.outstanding || 0) - Number(schedulePaymentForm.amount || 0)))"></el-alert>
        </template>
        <el-alert v-else type="success" :closable="false" show-icon title="This installment and party is fully settled. Use Reverse below to correct a payment." style="margin-bottom:16px;"></el-alert>
        <div v-if="(accountingPaymentRow.entries || []).length" class="repeat-card" style="margin-top:16px;">
          <div class="repeat-heading"><div><h3>Immutable payment history</h3><p>Incorrect entries are corrected with a linked reversal.</p></div></div>
          <div v-for="entry in accountingPaymentRow.entries" :key="entry.id" class="repeat-row">
            <span>{{ entry.paymentDate }} · {{ entry.entryType === 'reversal' ? 'Reversal' : 'Payment' }} · {{ accountingPaymentRow.currency }} {{ formatMoney(entry.amount) }}</span>
            <el-button v-if="entry.entryType === 'payment' && !(accountingPaymentRow.entries || []).some(item => item.reversalOf === entry.id)" text type="danger" @click="reverseSchedulePayment(accountingPaymentRow, entry)">Reverse</el-button>
          </div>
        </div>
      </el-form>
      <template #footer><el-button @click="accountingPaymentDialogVisible = false">Cancel</el-button><el-button v-if="accountingPaymentRow && Number(accountingPaymentRow.outstanding || 0) > 0" class="primary-button" :loading="accountingSaving" @click="recordSchedulePayment">Record payment</el-button></template>
    </el-dialog>
  </div>
</template>
