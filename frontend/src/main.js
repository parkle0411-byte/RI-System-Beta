import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
// 字體（2026-11-26）：Lato 由系統自己提供，不對外連線；只載入 400 與 700
import '@fontsource/lato/400.css'
import '@fontsource/lato/700.css'
// Alpha 的樣式，順序與 Alpha index.html 相同：theme → overview → development-alignment
import './alpha/styles/theme.css'
import './alpha/styles/overview.css'
import './alpha/styles/development-alignment.css'
// 互動層（2026-11-25）：只加過渡與回饋，不改顏色與版面
import './alpha/styles/motion.css'
import './alpha/styles/skeleton.css'
// 字體設定放在最後，覆蓋 --sans／--mono（英文與數字 Lato、中文標楷體）
import './alpha/styles/fonts.css'
import App from './App.vue'
import router from './router'
import { installUnauthorizedHandler } from './auth'
import { installRipple } from './alpha/ripple'
import { vSkeleton } from './directives/skeleton'

installUnauthorizedHandler(router)
installRipple()

createApp(App).use(ElementPlus).use(router).directive('skeleton', vSkeleton).mount('#app')
