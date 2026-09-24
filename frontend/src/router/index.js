import { createRouter, createWebHistory } from 'vue-router'
import SystemStatus from '../views/SystemStatus.vue'
import FxRates from '../views/FxRates.vue'

const routes = [
  { path: '/', name: 'system-status', component: SystemStatus },
  { path: '/fx-rates', name: 'fx-rates', component: FxRates }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
