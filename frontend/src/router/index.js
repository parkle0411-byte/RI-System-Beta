import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { auth, can, loadContext } from '../auth'
import Login from '../views/Login.vue'
import SystemStatus from '../views/SystemStatus.vue'
import FxRates from '../views/FxRates.vue'
import MasterData from '../views/MasterData.vue'
import Personnel from '../views/Personnel.vue'

// meta.permission：進入該頁所需的權限（與後端 permission_map 對應，名稱與 Alpha 相同）
const routes = [
  { path: '/login', name: 'login', component: Login, meta: { public: true } },
  { path: '/', name: 'system-status', component: SystemStatus },
  { path: '/fx-rates', name: 'fx-rates', component: FxRates, meta: { permission: 'fx.read' } },
  { path: '/master-data', name: 'master-data', component: MasterData, meta: { permission: 'mdm.read' } },
  { path: '/personnel', name: 'personnel', component: Personnel, meta: { permission: 'personnel.read' } }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach(async (to) => {
  if (!auth.ready) await loadContext()
  if (to.meta.public) {
    // 已登入的人不需要再看登入頁
    return auth.principal && to.name === 'login' ? { path: '/' } : true
  }
  if (!auth.principal) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.permission && !can(to.meta.permission)) {
    ElMessage.warning('您沒有權限使用此功能。')
    return { path: '/' }
  }
  return true
})

export default router
