<script setup>
// 案件 History 分頁（2026-11-27 業主決定）：Announce 之後的事件，案件修改列出欄位的修改前／後。唯讀。
import { onMounted, ref, watch } from 'vue'
import { apiFetch } from '../api'
import { formatDateTime } from '../alpha/format'

const props = defineProps({ caseUid: { type: String, required: true }, rowVersion: { type: Number, default: 0 } })
const loading = ref(false), error = ref(''), events = ref([]), announced = ref(true), truncated = ref(false), loaded = ref(false)
let sequence = 0

async function load() {
  const current = ++sequence
  loading.value = true
  error.value = ''
  try {
    const response = await apiFetch('/api/case-history?caseUid=' + encodeURIComponent(props.caseUid))
    const body = await response.json()
    if (!response.ok) throw new Error(body.message || body.error || ('HTTP ' + response.status))
    if (current !== sequence) return
    events.value = body.events || []; announced.value = !!body.announced; truncated.value = !!body.truncated; loaded.value = true
  } catch (err) {
    if (current !== sequence) return
    events.value = []; loaded.value = false
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    if (current === sequence) loading.value = false
  }
}
watch(() => props.caseUid, () => { events.value = []; loaded.value = false })
watch(() => [props.caseUid, props.rowVersion], load)
onMounted(load)

// 只差空格或換行的修改很難用眼睛看出來：標示出來，並把不同的那一段畫上底色
const spacingOnly = change => change.before !== null && change.after !== null && change.before.replace(/\s/g, '') === change.after.replace(/\s/g, '')
function parts(change, side) {
  const value = change[side]
  if (value === null || value === undefined) return [{ text: '—', mark: false }]
  const other = change[side === 'before' ? 'after' : 'before']
  const spacing = spacingOnly(change)
  // 短的值整格看得清楚；長文字或只差空白時才標出不同的段落
  if (other === null || other === undefined || (!spacing && Math.max(value.length, other.length) < 30)) return [{ text: value, mark: false }]
  const limit = Math.min(value.length, other.length)
  let start = 0, end = 0
  while (start < limit && value[start] === other[start]) start++
  while (end < limit - start && value[value.length - 1 - end] === other[other.length - 1 - end]) end++
  if (!spacing) { // 一般文字修改：標整個單字，不要切在字中間
    while (start > 0 && /[A-Za-z0-9,.]/.test(value[start - 1])) start--
    while (end > 0 && /[A-Za-z0-9,.]/.test(value[value.length - end])) end--
  }
  let middle = value.slice(start, value.length - end)
  if (middle && !middle.trim()) middle = middle.replace(/ /g, '␣').replace(/\t/g, '⇥').replace(/\n/g, '↵\n')
  return [{ text: value.slice(0, start), mark: false }, { text: middle, mark: true }, { text: value.slice(value.length - end), mark: false }].filter(part => part.text)
}
</script>

<template>
  <section class="overview-card case-history" data-testid="case-history" v-skeleton="{ on: loading, rows: 6 }">
    <div class="section-heading">
      <div><h2>History</h2><p>Changes saved after Announce, newest first. Uploading or generating documents is not listed.</p></div>
      <el-button class="secondary-button" :loading="loading" @click="load">Refresh</el-button>
    </div>
    <el-alert v-if="error" type="error" :closable="false" show-icon title="History could not be loaded" :description="error" />
    <el-alert v-if="truncated" type="info" :closable="false" show-icon title="Only the latest 200 events are shown." />
    <p v-if="loaded && !events.length" class="history-empty" data-testid="case-history-empty">{{ announced ? 'No saved records for this case.' : 'History starts after the case is Announced.' }}</p>
    <ol v-if="events.length" class="history-list">
      <li v-for="event in events" :key="event.version" class="history-event" :data-reason="event.reason">
        <header>
          <time>{{ formatDateTime(event.at) }}</time><strong>{{ event.action }}</strong><span>{{ event.actorName }}</span><small>version {{ event.version }}</small>
        </header>
        <p v-if="event.comment" class="history-comment">Reason: {{ event.comment }}</p>
        <p v-if="event.compared && !event.changes.length" class="history-comment">No change to case fields.</p>
        <table v-if="event.changes.length" class="history-changes">
          <thead><tr><th>Field</th><th>Before</th><th>After</th></tr></thead>
          <tbody>
            <tr v-for="(change, index) in event.changes" :key="index">
              <th scope="row">{{ change.field }}<small v-if="change.kind === 'added'">Added</small><small v-else-if="change.kind === 'removed'">Removed</small><small v-else-if="spacingOnly(change)">Spacing / line breaks only</small></th>
              <td data-label="Before"><span v-for="(part, i) in parts(change, 'before')" :key="i" :class="{ 'history-before': part.mark }">{{ part.text }}</span></td>
              <td data-label="After"><span v-for="(part, i) in parts(change, 'after')" :key="i" :class="{ 'history-after': part.mark }">{{ part.text }}</span></td>
            </tr>
          </tbody>
        </table>
        <p v-if="event.truncated" class="history-comment">Only the first 200 changed fields are shown.</p>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.case-history .section-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 14px; padding: 0; }
.history-empty, .history-comment { margin: 6px 0 0; color: var(--text-secondary); font-size: 13px; }
.history-list { list-style: none; margin: 0; padding: 0; }
.history-event { padding: 12px 0; border-top: 1px solid var(--border); }
.history-event header { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 14px; }
.history-event header time { color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.history-event header small { color: var(--text-secondary); margin-left: auto; }
.history-changes { width: 100%; margin-top: 10px; border-collapse: collapse; table-layout: fixed; background: var(--surface-page); font-size: 13px; }
.history-changes th, .history-changes td { border: 1px solid var(--border); padding: 8px 10px; text-align: left; vertical-align: top; font-weight: 400; overflow-wrap: anywhere; }
.history-changes thead th { color: var(--text-secondary); font-size: 12px; }
.history-changes thead th:first-child { width: 24%; }
.history-changes th small { display: block; margin-top: 3px; color: var(--text-secondary); font-size: 11px; }
.history-changes td { white-space: pre-wrap; }
.history-before, .history-after { padding: 0 2px; border-radius: 3px; }
.history-before { background: var(--danger-bg); color: var(--danger-text); }
.history-after { background: var(--success-bg); color: var(--success-text); }
@media (max-width: 700px) {
  .history-changes thead { display: none; }
  .history-changes, .history-changes tbody, .history-changes tr, .history-changes th, .history-changes td { display: block; width: auto; }
  .history-changes tr { margin-bottom: 8px; }
  .history-changes td::before { content: attr(data-label) ': '; color: var(--text-secondary); }
}
</style>
