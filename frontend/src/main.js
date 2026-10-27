import { createApp } from 'vue'
import App from './App.vue'
import './styles.css'
import { installReporting } from './lib/report'

const app = createApp(App)
installReporting(app)
app.mount('#app')
