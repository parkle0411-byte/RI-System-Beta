import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 2026-11-13：拆檔。第三方套件（Vue、Element Plus…）獨立成 vendor 檔，內容不變時雜湊檔名不變，部署後仍可用瀏覽器快取；
// 各頁面由 router 動態載入，各自成檔。
export default defineConfig({
  plugins: [vue()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) return 'vendor'
        },
      },
    },
  },
})
