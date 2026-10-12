// retail-frontend/src/main.js
import { createApp } from 'vue'
import App from './App.vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css' // 引入 Element Plus 样式
import * as echarts from 'echarts'

const app = createApp(App)
app.use(ElementPlus)
app.config.globalProperties.$echarts = echarts // 全局挂载 ECharts
app.mount('#app')