import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { auth, can, loadContext } from '../auth'
import { NAV_ICONS } from '../alpha/constants'
import { setHeader, shell } from '../alpha/shell'
import Login from '../views/Login.vue'
// 2026-11-13：各頁面改為進入時才載入（拆檔），部署後只需重新下載有變動的頁面；登入頁留在主檔。
const ForgotPassword = () => import('../views/ForgotPassword.vue')
const ResetPassword = () => import('../views/ResetPassword.vue')
const CaseWorkspace = () => import('../views/CaseWorkspace.vue')
const RecycleBin = () => import('../views/RecycleBin.vue')
const FxRates = () => import('../views/FxRates.vue')
const MasterData = () => import('../views/MasterData.vue')
const Personnel = () => import('../views/Personnel.vue')
const AuditLog = () => import('../views/AuditLog.vue')
const Accounting = () => import('../views/Accounting.vue')
const Production = () => import('../views/Production.vue')
const Dashboard = () => import('../views/Dashboard.vue')
const SystemStatus = () => import('../views/SystemStatus.vue')
const NoAccess = () => import('../views/NoAccess.vue')
const SystemReference = () => import('../views/SystemReference.vue')
const LegacyTransactions = () => import('../views/LegacyTransactions.vue')

// 左側選單與頁首文字：與 Alpha public/app.js 的 allNavigation／headers 相同（順序、名稱、權限、階段標籤）。
// Alpha 用 activeView 切換畫面；VM 每一項是一個路由，方便重新整理與瀏覽器上一頁。
export const allNavigation = [
  { id: 'dashboard', path: '/dashboard', label: 'Dashboard', icon: NAV_ICONS.dashboard, permission: 'dashboard.read' },
  { id: 'cases', path: '/cases', label: 'Account List', icon: NAV_ICONS.cases, anyPermission: ['cases.read.all', 'cases.read.own'] },
  { id: 'legacy', path: '/legacy', label: 'Legacy Data (Old Register)', icon: NAV_ICONS.legacy, permission: 'legacy.read' },
  { id: 'mdm', path: '/mdm', label: 'Master Data Management', icon: NAV_ICONS.mdm, anyPermission: ['mdm.read', 'cases.read.all'] },
  { id: 'personnel', path: '/personnel', label: 'Personnel & Accounts', icon: NAV_ICONS.personnel, anyPermission: ['personnel.read', 'personnel.read.team'] },
  { id: 'production', path: '/production', label: 'Production Report', icon: NAV_ICONS.production, permission: 'production.read' },
  { id: 'accounting', path: '/accounting', label: 'Accounting', icon: NAV_ICONS.accounting, permission: 'accounting.read' },
  { id: 'fxrates', path: '/fx-rates', label: 'FX Rates', icon: NAV_ICONS.fxrates, permission: 'fx.read' },
  { id: 'recycle', path: '/recycle', label: 'Draft Recycle Bin', icon: NAV_ICONS.recycle, phase: '5 years', permission: 'recycle.read' },
  { id: 'system-reference', path: '/system-reference', label: 'System Reference Data', icon: NAV_ICONS.reference, permission: 'accounts.manage' },
  { id: 'audit', path: '/audit', label: 'Audit Log', icon: NAV_ICONS.audit, permission: 'audit.read' }
]

export const headers = {
  legacy: { kicker: 'Facultative Property', title: 'Legacy Data (Old Register)', subtitle: 'Historical transactions, endorsements and claims' },
  'system-reference': { kicker: 'Reference', title: 'System Reference Data', subtitle: 'Document templates and system guides' },
  dashboard: { kicker: 'Operations', title: 'Dashboard', subtitle: 'Production & Records Overview' },
  insured: { kicker: 'Insured', title: 'Insured Master', subtitle: 'Chinese names, former names and linked policies' },
  cases: { kicker: 'Placement', title: 'Account List', subtitle: 'All outward cases' },
  recycle: { kicker: 'Placement governance', title: 'Draft Recycle Bin', subtitle: 'Five-year restore window · permanent deletion prohibited' },
  mdm: { kicker: 'Master data', title: 'Master Data Management', subtitle: 'Insureds, reinsurers, clauses and business master records' },
  personnel: { kicker: 'Administration', title: 'Personnel & Accounts', subtitle: 'Unified personnel, future accounts and target settings' },
  production: { kicker: 'Reporting', title: 'Production Report', subtitle: 'Monthly read-only production preview' },
  accounting: { kicker: 'Accounting', title: 'Accounting', subtitle: 'Statement of account, transactions and settlement' },
  fxrates: { kicker: 'Master data', title: 'FX Rates', subtitle: 'Official monthly foreign currency to TWD rates' },
  audit: { kicker: 'Governance', title: 'Audit Log', subtitle: 'Append-only activity history with at least 10-year retention' },
  'system-status': { kicker: 'VM', title: 'System status', subtitle: 'Company VM health check' },
  'no-access': { kicker: 'Access', title: 'No access', subtitle: 'No pages are available for your role' }
}

export function navAllowed(item) {
  return item.permission ? can(item.permission) : (item.anyPermission || []).some(can)
}

const component = { legacy: LegacyTransactions, 'system-reference': SystemReference, cases: CaseWorkspace, recycle: RecycleBin, mdm: MasterData, personnel: Personnel, fxrates: FxRates, audit: AuditLog, accounting: Accounting, production: Production, dashboard: Dashboard }
const routes = [
  { path: '/login', name: 'login', component: Login, meta: { public: true } },
  // 忘記密碼（VM 專有；寄信啟用後登入頁才有入口）
  { path: '/forgot-password', name: 'forgot-password', component: ForgotPassword, meta: { public: true } },
  { path: '/reset-password', name: 'reset-password', component: ResetPassword, meta: { public: true } },
  { path: '/', name: 'home', redirect: () => (allNavigation.find(navAllowed) || { path: can('foundation.read') ? '/system-status' : '/no-access' }).path },
  ...allNavigation.map((item) => ({ path: item.path, name: item.id, component: component[item.id], meta: { nav: item } })),
  { path: '/insured', redirect: to => ({ path: '/mdm', query: { ...to.query, tab: 'insured' } }) },
  // System status：只有 System Administrator（foundation.read；後端 /health/ 同樣檢查）
  { path: '/system-status', name: 'system-status', component: SystemStatus, meta: { permission: 'foundation.read' } },
  { path: '/no-access', name: 'no-access', component: NoAccess },
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
  if ((to.meta.nav && !navAllowed(to.meta.nav)) || (to.meta.permission && !can(to.meta.permission))) {
    ElMessage.warning('You do not have permission to open this page.')
    return { path: '/' }
  }
  return true
})

// 部署新版後，舊分頁要載入的頁面檔已經換名：改用整頁重新載入到目的頁，取得新版程式（只重試一次，避免無限重載）。
router.onError((error, to) => {
  const stale = /dynamically imported module|Importing a module script failed|error loading dynamically imported|Unable to preload CSS/i.test(String(error && error.message))
  if (!stale || !to || !to.fullPath) return
  const key = 'ri-chunk-reload'
  if (sessionStorage.getItem(key) === to.fullPath) return
  sessionStorage.setItem(key, to.fullPath)
  window.location.assign(to.fullPath)
})

router.afterEach((to) => {
  try { sessionStorage.removeItem('ri-chunk-reload') } catch { /* ignore */ }
  shell.error = ''
  setHeader(headers[to.name] || headers.dashboard)
})

export default router
