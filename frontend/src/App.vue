<script setup>
</script>

<template>
  <el-container style="min-height: 100vh; background: #f5f7fa">
    <el-header style="background: #303133; color: #fff; display: flex; align-items: center; gap: 24px">
      <span style="font-size: 18px">RI System（測試環境）</span>
      <el-menu mode="horizontal" background-color="#303133" text-color="#fff" router style="flex: 1; border: none">
        <el-menu-item index="/">系統狀態</el-menu-item>
        <el-menu-item index="/fx-rates">FX Rates</el-menu-item>
      </el-menu>
    </el-header>
    <el-main>
      <router-view />
    </el-main>
  </el-container>
</template>
