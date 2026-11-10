import { createApp } from 'vue'
import App from './App.vue'
import './styles.css'
import { installReporting } from './lib/report'

// Возврат с oauth.yandex.ru после «Получить токен»: токен приходит после «#» (на сервер этот кусок адреса не попадает).
// Сохраняем его на сервер и перезагружаемся на страницу облака в настройках — уже без токена в адресе.
const oauth = new URLSearchParams(location.hash.slice(1))
const oauthReturn = location.pathname === '/yandex-oauth' && (oauth.get('access_token') || oauth.get('error'))

async function saveOauth() {
  const token = oauth.get('access_token')
  history.replaceState(null, '', '/')
  const done = (text) => { try { sessionStorage.setItem('cloudOauth', text); sessionStorage.setItem('settingsPage', 'cloud') } catch { /* без хранилища */ } }
  if (!token) done('err:Яндекс не выдал токен: ' + (oauth.get('error_description') || oauth.get('error')))
  else {
    try {
      const r = await fetch('/api/cloud', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }) })
      const j = await r.json().catch(() => ({}))
      done(!r.ok ? 'err:' + (j.detail || 'Сервер ответил ' + r.status) : j.last_error ? 'err:' + j.last_error : 'ok:Токен получен и сохранён. Снимок загружен на Диск.')
    } catch (e) { done('err:Не удалось сохранить токен: ' + e.message) }
  }
  location.replace('/?view=settings')
}

if (oauthReturn) saveOauth()
else {
const app = createApp(App)
installReporting(app)
app.mount('#app')
}
