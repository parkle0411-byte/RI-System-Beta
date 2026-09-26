<script setup>
// 登入者沒有任何可開啟的頁面時顯示（VM 才有；以前會導到 System status，現在那頁只給 System Administrator）。
</script>

<template>
  <section class="pending-card"><span class="pending-badge">No access</span><h2>No pages are available for your role</h2><p>Your account is active, but your role does not include any page in this system. Please contact a System Administrator.</p></section>
</template>
