import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
// Alpha 的樣式，順序與 Alpha index.html 相同：theme → overview → development-alignment
import './alpha/styles/theme.css'
import './alpha/styles/overview.css'
import './alpha/styles/development-alignment.css'
// 互動層（2026-11-25）：只加過渡與回饋，不改顏色與版面
import './alpha/styles/motion.css'
import App from './App.vue'
import router from './router'
import { installUnauthorizedHandler } from './auth'

installUnauthorizedHandler(router)

createApp(App).use(ElementPlus).use(router).mount('#app')
