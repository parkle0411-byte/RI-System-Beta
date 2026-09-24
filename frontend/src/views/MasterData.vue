<template>
  <div class="master-data-page">
    <el-tabs v-model="activeType">
      <el-tab-pane v-for="opt in entityTypeOptions" :key="opt.value" :label="opt.label" :name="opt.value" />
    </el-tabs>

    <div class="toolbar">
      <el-button type="primary" @click="openCreateDialog">新增</el-button>
    </div>

    <el-table :data="records" v-loading="loading" style="width: 100%">
      <el-table-column prop="code" label="代碼" width="140" />
      <el-table-column prop="name" label="名稱" />
      <el-table-column label="狀態" width="100">
        <template #default="{ row }">
          <el-tag :type="row.isActive ? 'success' : 'info'">{{ row.isActive ? '啟用' : '停用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEditDialog(row)">編輯</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editingRecord ? '編輯主檔' : '新增主檔'" width="600px">
      <el-form :model="form" label-width="120px">
        <el-form-item label="類型">
          <el-input :model-value="entityTypeLabel(activeType)" disabled />
        </el-form-item>
        <el-form-item label="代碼" :required="activeType === 'clause'">
          <el-input v-model="form.code" />
        </el-form-item>
        <el-form-item label="名稱" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="狀態" v-if="editingRecord">
          <el-switch v-model="form.isActive" active-text="啟用" inactive-text="停用" />
        </el-form-item>

        <template v-if="['reinsurer','reinsured','foreign_broker'].includes(activeType)">
          <el-form-item label="簡稱">
            <el-input v-model="form.payload.abbreviation" />
          </el-form-item>
        </template>
        <template v-if="activeType === 'reinsured'">
          <el-form-item label="地址">
            <el-input v-model="form.payload.address" type="textarea" />
          </el-form-item>
        </template>

        <template v-if="activeType === 'reinsurer'">
          <el-divider>Fixed Clauses</el-divider>
          <div v-for="(clause, idx) in form.payload.fixedClauses" :key="idx" class="row-editor">
            <el-input v-model="clause.code" placeholder="Code" style="width: 200px" />
            <el-input v-model="clause.title" placeholder="Title" />
            <el-button type="danger" link @click="form.payload.fixedClauses.splice(idx,1)">刪除</el-button>
          </div>
          <el-button @click="form.payload.fixedClauses.push({code:'',title:''})">+ 新增 Clause</el-button>

          <el-divider>Ratings</el-divider>
          <div v-for="(rating, idx) in form.payload.ratings" :key="idx" class="row-editor">
            <el-input v-model="rating.agency" placeholder="Agency" style="width: 140px" />
            <el-input v-model="rating.grade" placeholder="Grade" style="width: 100px" />
            <el-input v-model="rating.outlook" placeholder="Outlook" style="width: 120px" />
            <el-button type="danger" link @click="form.payload.ratings.splice(idx,1)">刪除</el-button>
          </div>
          <el-button @click="form.payload.ratings.push({agency:'',grade:'',outlook:''})">+ 新增 Rating</el-button>
        </template>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">儲存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'

const entityTypeOptions = [
  { value: 'ae', label: 'AE' },
  { value: 'reinsurer', label: 'Reinsurer' },
  { value: 'reinsured', label: 'Reinsured' },
  { value: 'class', label: 'Class' },
  { value: 'foreign_broker', label: 'Foreign RI Broker' },
  { value: 'clause', label: 'Clause' },
]

const activeType = ref('ae')
const records = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const saving = ref(false)
const editingRecord = ref(null)

const emptyForm = () => ({
  code: '',
  name: '',
  isActive: true,
  payload: { abbreviation: '', address: '', fixedClauses: [], ratings: [] },
})
const form = reactive(emptyForm())

function entityTypeLabel(value) {
  return entityTypeOptions.find(o => o.value === value)?.label || value
}

async function loadRecords() {
  loading.value = true
  try {
    const res = await fetch(`/api/master-data?entityType=${activeType.value}`)
    const data = await res.json()
    if (!data.ok) throw new Error(data.message || '載入失敗')
    records.value = data.records
  } catch (e) {
    ElMessage.error(e.message || '載入失敗')
  } finally {
    loading.value = false
  }
}

function openCreateDialog() {
  editingRecord.value = null
  Object.assign(form, emptyForm())
  dialogVisible.value = true
}

function openEditDialog(row) {
  editingRecord.value = row
  Object.assign(form, {
    code: row.code || '',
    name: row.name,
    isActive: row.isActive,
    payload: {
      abbreviation: row.payload?.abbreviation || '',
      address: row.payload?.address || '',
      fixedClauses: (row.payload?.fixedClauses || []).map(c => ({ ...c })),
      ratings: (row.payload?.ratings || []).map(r => ({ ...r })),
    },
  })
  dialogVisible.value = true
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.error('名稱為必填')
    return
  }
  if (activeType.value === 'clause' && !form.code.trim()) {
    ElMessage.error('Clause 代碼為必填')
    return
  }
  saving.value = true
  try {
    const body = {
      entityType: activeType.value,
      code: form.code,
      name: form.name,
      payload: form.payload,
    }
    let res
    if (editingRecord.value) {
      body.id = editingRecord.value.id
      body.rowVersion = editingRecord.value.rowVersion
      body.isActive = form.isActive
      res = await fetch('/api/master-data', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
    } else {
      res = await fetch('/api/master-data', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
    }
    const data = await res.json()
    if (!res.ok || !data.ok) throw new Error(data.message || '儲存失敗')
    ElMessage.success('儲存成功')
    dialogVisible.value = false
    await loadRecords()
  } catch (e) {
    ElMessage.error(e.message || '儲存失敗')
  } finally {
    saving.value = false
  }
}

watch(activeType, loadRecords)
onMounted(loadRecords)
</script>

<style scoped>
.toolbar {
  margin: 16px 0;
}
.row-editor {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  align-items: center;
}
</style>
