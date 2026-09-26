<script setup>
// 對應 Alpha index.html 最後的 v-else：尚未搬移的畫面顯示「Queued for migration」卡片（文字同 Alpha 的 pendingCopy）。
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { shell } from '../alpha/shell'

const pendingCopy = {
  production: 'Production Report rules will be migrated after the case and endorsement data contracts are stable.',
  accounting: 'Confirmed cases generate Development-compatible transaction cycles; settlement is controlled from the consolidated ledger.'
}
const route = useRoute()
const pendingDescription = computed(() => pendingCopy[route.name] || 'This screen is queued for migration.')
</script>

<template>
  <section class="pending-card"><span class="pending-badge">Queued for migration</span><h2>{{ shell.header.title }}</h2><p>{{ pendingDescription }}</p><div class="pending-rule"></div><p class="pending-note">This navigation entry remains stable while each legacy screen is migrated and verified one at a time.</p></section>
</template>
