import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import { router } from './router'
import './styles/base.scss'

createApp(App).use(createPinia()).use(router).mount('#app')
