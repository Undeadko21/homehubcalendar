// Сообщения об ошибках: показываем на экране и отправляем на сервер (/api/client-log),
// чтобы разбираться с проблемами на телефонах без кабеля и инструментов разработчика.
import { reactive } from 'vue'

export const problems = reactive({ list: [] })
const sent = new Set()

export function report(message, extra = {}) {
  const msg = String(message || 'Неизвестная ошибка').slice(0, 500)
  if (!problems.list.includes(msg)) problems.list.push(msg)
  if (problems.list.length > 3) problems.list.shift()
  const key = msg + (extra.kind || '')
  if (sent.has(key)) return
  sent.add(key)
  try {
    fetch('/api/client-log', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: msg,
        stack: String(extra.stack || '').slice(0, 1500),
        url: location.href,
        ua: navigator.userAgent,
        kind: extra.kind || 'error',
      }),
    }).catch(() => {})
  } catch {}
}

export function installReporting(app) {
  window.addEventListener('error', (e) => report(e.message, { stack: e.error?.stack, kind: 'window' }))
  window.addEventListener('unhandledrejection', (e) => report(e.reason?.message || e.reason, { stack: e.reason?.stack, kind: 'promise' }))
  app.config.errorHandler = (err, _vm, info) => {
    report(`${err?.message || err} (${info})`, { stack: err?.stack, kind: 'vue' })
    console.error(err)
  }
  // Сразу сообщим, если браузер не умеет нужное оформление — пригодится при разборе.
  try {
    if (window.CSS && !CSS.supports('color', 'color-mix(in srgb, red 50%, blue)')) {
      document.documentElement.classList.add('no-color-mix')
      report('Старый движок браузера: нет color-mix', { kind: 'info' })
      problems.list.pop() // это не ошибка, на экране не показываем
    }
  } catch {}
}
