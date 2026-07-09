import { createApp } from 'vue'
import App from './App.vue'

// 引入 Vuetify
import 'vuetify/styles'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import '@mdi/font/css/materialdesignicons.css' // 引入图标库

const vuetify = createVuetify({
  components,
  directives,
})

const app = createApp(App)

app.use(vuetify) // 注册插件
app.mount('#app')