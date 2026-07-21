import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import logger from './utils/logger'
import './styles/theme.css'
import './styles/global.css'
import './plugins/echarts'
import ToastPlugin from './plugins/toast'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ToastPlugin)

// 全局未捕获的 Vue 渲染/生命周期错误统一记录
app.config.errorHandler = (err, instance, info) => {
  logger.error('Vue 运行时错误:', err, info)
}

app.mount('#app')