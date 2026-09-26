import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { auth, can, loadContext } from '../auth'
import { NAV_ICONS } from '../alpha/constants'
import { setHeader, shell } from '../alpha/shell'
import Login from '../views/Login.vue'
import CaseWorkspace from '../views/CaseWorkspace.vue'
import RecycleBin from '../views/RecycleBin.vue'
import FxRates from '../views/FxRates.vue'
import MasterData from '../views/MasterData.vue'
import Personnel from '../views/Personnel.vue'
import AuditLog from '../views/AuditLog.vue'
import Accounting from '../views/Accounting.vue'
import Production from '../views/Production.vue'
import Dashboard from '../views/Dashboard.vue'
import PendingView from '../views/PendingView.vue'
import SystemStatus from '../views/SystemStatus.vue'

// 左側選單與頁首文字：與 Alpha public/app.js 的 allNavigation／headers 相同（順序、名稱、權限、階段標籤）。
// Alpha 用 activeView 切換畫面；VM 每一項是一個路由，方便重新整理與瀏覽器上一頁。
export const allNavigation = [
  { id: 'dashboard', path: '/dashboard', label: 'Dashboard', icon: NAV_ICONS.dashboard, permission: 'dashboard.read' },
  { id: 'cases', path: '/cases', label: 'Account List', icon: NAV_ICONS.cases, anyPermission: ['cases.read.all', 'cases.read.own'] },
  { id: 'mdm', path: '/mdm', label: 'Reinsurance MDM', icon: NAV_ICONS.mdm, permission: 'mdm.read' },
  { id: 'personnel', path: '/personnel', label: 'Personnel & Accounts', icon: NAV_ICONS.personnel, permission: 'personnel.read' },
  { id: 'production', path: '/production', label: 'Production Report', icon: NAV_ICONS.production, permission: 'production.read' },
  { id: 'accounting', path: '/accounting', label: 'Accounting', icon: NAV_ICONS.accounting, permission: 'accounting.read' },
  { id: 'fxrates', path: '/fx-rates', label: 'FX Rates', icon: NAV_ICONS.fxrates, permission: 'fx.read' },
  { id: 'recycle', path: '/recycle', label: 'Draft Recycle Bin', icon: NAV_ICONS.recycle, phase: '5 years', permission: 'recycle.read' },
  { id: 'audit', path: '/audit', label: 'Audit Log', icon: NAV_ICONS.audit, phase: 'Read only', permission: 'audit.read' }
]

export const headers = {
  dashboard: { kicker: 'Operations', title: 'Dashboard', subtitle: 'Production & records overview' },
  cases: { kicker: 'Placement', title: 'Account List', subtitle: 'All facultative outward cases' },
  recycle: { kicker: 'Placement governance', title: 'Draft Recycle Bin', subtitle: 'Five-year restore window · permanent deletion prohibited', phase: 'Retained' },
  mdm: { kicker: 'Master data', title: 'Reinsurance MDM', subtitle: 'Versioned master records, fixed clauses and lifecycle controls', phase: 'Milestone 11' },
  personnel: { kicker: 'Administration', title: 'Personnel & Accounts', subtitle: 'Unified personnel, future accounts and target settings', phase: 'Milestone 21' },
  production: { kicker: 'Reporting', title: 'Production Report', subtitle: 'Monthly read-only production preview', phase: 'Milestone 19' },
  accounting: { kicker: 'Accounting', title: 'Accounting', subtitle: 'Statement of account, transactions and settlement', phase: 'Milestone 22' },
  fxrates: { kicker: 'Master data', title: 'FX Rates', subtitle: 'Official monthly USD to TWD rates', phase: 'Milestone 20' },
  audit: { kicker: 'Governance', title: 'Audit Log', subtitle: 'Append-only activity history with at least 10-year retention', phase: 'Read only' },
  'system-status': { kicker: 'VM', title: 'System status', subtitle: 'Company VM health check' }
}

export function navAllowed(item) {
  return item.permission ? can(item.permission) : (item.anyPermission || []).some(can)
}

const component = { cases: CaseWorkspace, recycle: RecycleBin, mdm: MasterData, personnel: Personnel, fxrates: FxRates, audit: AuditLog, accounting: Accounting, production: Production, dashboard: Dashboard }
const routes = [
  { path: '/login', name: 'login', component: Login, meta: { public: true } },
  { path: '/', name: 'home', redirect: () => (allNavigation.find(navAllowed) || { path: '/system-status' }).path },
  ...allNavigation.map((item) => ({ path: item.path, name: item.id, component: component[item.id] || PendingView, meta: { nav: item } })),
  { path: '/system-status', name: 'system-status', component: SystemStatus },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(async (to) => {
  if (!auth.ready) await loadContext()
  if (to.meta.public) {
    return auth.principal && to.name === 'login' ? { path: '/' } : true
  }
  if (!auth.principal) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.nav && !navAllowed(to.meta.nav)) {
    ElMessage.warning('You do not have permission to open this page.')
    return { path: '/' }
  }
  return true
})

router.afterEach((to) => {
  shell.error = ''
  setHeader(headers[to.name] || headers.dashboard)
})

export default router
