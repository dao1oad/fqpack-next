import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'
import store from './store'
import global from './global'
import './style/workbench-tokens.css'
import './style/workbench-density.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { VueQueryPlugin } from '@tanstack/vue-query'

const app = createApp(App)
app.use(store)
  .use(router)
  .use(ElementPlus, { size: 'small', zIndex: 3000, locale: zhCn })
  .use(global)
  .use(VueQueryPlugin)
  .mount('#app')
