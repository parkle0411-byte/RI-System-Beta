<script setup>
// 對應 Alpha index.html 最後的 v-else：尚未搬移的畫面顯示「Queued for migration」卡片（文字同 Alpha 的 pendingCopy）。
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { shell } from '../alpha/shell'

const pendingCopy = {}
const route = useRoute()
const pendingDescription = computed(() => pendingCopy[route.name] || 'This screen is queued for migration.')
</script>

<template>
  <section class="pending-card"><span class="pending-badge">Queued for migration</span><h2>{{ shell.header.title }}</h2><p>{{ pendingDescription }}</p><div class="pending-rule"></div><p class="pending-note">This navigation entry remains stable while each legacy screen is migrated and verified one at a time.</p></section>
</template>
