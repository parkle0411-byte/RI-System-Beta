<script setup>
import { ref,computed,onMounted,watch } from 'vue'
import { useRoute,useRouter } from 'vue-router'
import { api } from '../api'
const route=useRoute(),router=useRouter(),search=ref(''),records=ref([]),total=ref(0),page=ref(1),loading=ref(false),error=ref(''),selected=ref(null),cases=ref([]),caseCount=ref(0),casePage=ref(1)
const emit=defineEmits(['counts'])
const scope=ref('formal'),formalTotal=ref(0),pendingTotal=ref(0)
const actionLabels = {created:'Created',renamed:'Renamed',merged:'Merged',merged_into:'Merged into',retired_alias:'Retired alias'}
function operationTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(date).map(part=>[part.type,part.value]))
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`
}
const historyRows=computed(()=>{const rows=[];const visit=history=>(history||[]).forEach(row=>{visit(row.sourceHistory);rows.push(row)});visit(selected.value?.history);return rows.sort((a,b)=>Date.parse(b.at)-Date.parse(a.at))})
let generation=0
async function load() {
  const run=++generation;loading.value=true;error.value=''
  try {
    const data=await api(`/api/insured-masters?search=${encodeURIComponent(search.value)}&page=${page.value}&scope=${scope.value}`)
    if(run!==generation)return
    records.value=data.records;total.value=data.total;formalTotal.value=data.formalTotal;pendingTotal.value=data.pendingTotal;emit('counts',data)
    if(route.query.id)await detail(route.query.id)
  } catch(e){error.value=e.message}finally{if(run===generation)loading.value=false}
}
async function detail(id) {
  error.value=''
  try { const data=await api(`/api/insured-masters?id=${encodeURIComponent(id)}&page=${casePage.value}`);selected.value=data.record;scope.value=data.record.registrationStatus==='pending'?'pending':'formal';cases.value=data.cases;caseCount.value=data.caseCount }
  catch(e){error.value=e.message;selected.value=null}
}
async function open(row){casePage.value=1;await router.replace({path:'/mdm',query:{tab:'insured',id:row.id}})}
function selectScope(value) { selected.value=null;router.replace({path:'/mdm',query:{tab:'insured'}});scope.value=value }
watch(scope,()=>{page.value=1;void load()})
watch(()=>route.query.id,()=>{if(route.query.id){casePage.value=1;void detail(route.query.id)}else selected.value=null})
onMounted(load)
</script>
<template>
  <section class="insured-directory table-card" v-loading="loading" data-testid="insured-directory">
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div class="directory-toolbar"><el-button :type="scope==='formal'?'primary':'default'" @click="selectScope('formal')">Insured ({{ formalTotal }})</el-button><el-button :type="scope==='pending'?'primary':'default'" @click="selectScope('pending')">Pending confirmation ({{ pendingTotal }})</el-button></div>
    <el-alert v-if="scope==='pending'" title="These historical masters have no verified Announce record. They are excluded from the formal count. A matching successful Announce automatically activates the master." type="info" :closable="false" />
    <div class="directory-toolbar"><el-input v-model="search" placeholder="Search current or former Chinese name" clearable aria-label="Search insured" @keyup.enter="page=1;load()" /><el-button @click="page=1;load()">Search</el-button></div>
    <p>Each master represents the complete insured combination. A/B and B/A share one master; A alone is separate. Each policy retains its own name and member order.</p>
    <el-table :data="records" @row-click="open" data-testid="insured-list"><el-table-column label="Chinese name" min-width="220"><template #default="{row}"><el-button type="primary" text @click.stop="open(row)">{{ row.name }}</el-button></template></el-table-column><el-table-column label="Former names" min-width="250"><template #default="{row}">{{ row.aliases.join('、')||'—' }}</template></el-table-column></el-table>
    <el-pagination v-model:current-page="page" :total="total" :page-size="50" layout="prev, pager, next, total" @current-change="load" />
    <section v-if="selected" class="directory-detail" data-testid="insured-detail">
      <div class="directory-toolbar"><h2>{{ selected.name }}</h2></div>
      <p>Former names: {{ selected.aliases.join('、')||'—' }}</p>
      <h3>Linked cases ({{ caseCount }})</h3>
      <el-table :data="cases"><el-table-column label="TW Ref." min-width="180"><template #default="{row}"><router-link :to="{path:'/cases',query:{case:row.caseUid}}">{{ row.twRef||'Draft' }}</router-link></template></el-table-column><el-table-column prop="caseKind" label="Kind" min-width="110" /><el-table-column prop="originalInsuredCn" label="Case name (CN)" min-width="190" /><el-table-column prop="originalInsured" label="Case name (EN)" min-width="200" /><el-table-column prop="className" label="Class" min-width="150" /><el-table-column prop="policyFrom" label="Effective" width="120" /><el-table-column prop="policyTo" label="Expiration" width="120" /><el-table-column prop="status" label="Status" width="110" /><el-table-column prop="renewedFromTwRef" label="Renewed from" min-width="170" /><el-table-column prop="parentTwRef" label="Parent policy" min-width="170" /></el-table>
      <el-pagination v-model:current-page="casePage" :total="caseCount" :page-size="100" layout="prev, pager, next, total" @current-change="detail(selected.id)" />
      <h3>Name and merge history</h3>
      <el-table :data="historyRows" data-testid="insured-history"><el-table-column label="Operation time" min-width="180"><template #default="{row}">{{ operationTime(row.at) }}</template></el-table-column><el-table-column prop="byName" label="Operator" min-width="150" /><el-table-column label="Action" min-width="140"><template #default="{row}">{{ actionLabels[row.action] || row.action }} <el-tag v-if="row.beforeAnnounce || selected.registrationStatus==='pending'" size="small">Before Announce</el-tag></template></el-table-column><el-table-column label="Change" min-width="260"><template #default="{row}">{{ row.before||row.sourceName||row.name||'' }}<template v-if="row.after||row.targetName"> → {{ row.after||row.targetName }}</template></template></el-table-column></el-table>
    </section>
    <p>Only successful Announce registers a formal insured. Draft names stay on the Case. Name changes are confirmed through Case or Endorsement workflows.</p>
  </section>
</template>
<style scoped>
.insured-directory{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;min-width:0;width:100%;max-width:100%;padding:18px 20px;overflow:hidden}.directory-toolbar{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.directory-toolbar .el-input{max-width:420px}.directory-toolbar h2{margin-right:auto}.directory-detail{min-width:0;max-width:100%;overflow:hidden;margin-top:12px;border-top:1px solid var(--border);padding-top:16px}.insured-directory p{color:var(--muted);line-height:1.6}.insured-directory :deep(.el-table__row){cursor:pointer}
</style>
