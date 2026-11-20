// Офлайн для веб-версии (значок на экране «Домой»): оболочка страницы и её файлы лежат в кэше,
// поэтому календарь открывается сразу и без связи показывает последние данные.
// Правило простое: сеть важнее кэша везде, кроме файлов /assets/ (у них имя меняется вместе с содержимым).
const SHELL = 'hh-shell-v1'
const DATA = 'hh-data-v1'
const DATA_MAX = 40
const NAV_TIMEOUT = 3500
// Ответы только на чтение, которые можно показать без связи. Всё остальное (записи, вход, настройки) идёт мимо.
const API = /^\/api\/(config|events|holidays|lists|birthdays|countdowns|shops|recent-events)$/
// Адреса, которые открываются как страница, но оболочкой не являются.
const NOT_SHELL = /^\/(api\/|assets\/|app\.apk|app-ios\.ipa|app-mac\.zip|altstore\.json|connect|yandex-oauth|sw\.js|precache\.json)/

self.addEventListener('install', (e) => {
  e.waitUntil(precache().catch(() => {}).then(() => self.skipWaiting()))
})
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('hh-') && k !== SHELL && k !== DATA).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

// Список файлов сборки кладёт vite (precache.json). Докачиваем недостающее и убираем файлы прошлых версий.
async function precache() {
  const res = await fetch('/precache.json', { cache: 'no-store' })
  if (!res.ok) return
  const files = await res.json()
  const cache = await caches.open(SHELL)
  const have = new Set((await cache.keys()).map((r) => new URL(r.url).pathname))
  const want = new Set(files)
  await Promise.all(files.filter((f) => !have.has(f)).map((f) =>
    fetch(f, { cache: 'no-cache' }).then((r) => (r.ok ? cache.put(f, r) : null)).catch(() => null)))
    const shell = await fetch('/', { cache: 'no-store' }).catch(() => null)
  if (!shell || !shell.ok) return
  // Файлы, на которые ссылается сама страница (в списке сборки их может не быть — например, полифилы).
  const html = await shell.clone().text()
  const linked = [...new Set(html.match(/\/assets\/[\w.-]+/g) || [])]
  await Promise.all(linked.filter((f) => !have.has(f) && !want.has(f)).map((f) =>
    fetch(f).then((r) => (r.ok ? cache.put(f, r) : null)).catch(() => null)))
  await cache.put('/', shell)
  for (const p of have) if (p.startsWith('/assets/') && !want.has(p) && !linked.includes(p)) await cache.delete(p)
}

self.addEventListener('message', (e) => {
  if (e.data === 'precache') e.waitUntil(precache().catch(() => {}))
  if (e.data === 'forget') e.waitUntil(caches.delete(DATA))   // вышли из календаря — данных в кэше быть не должно
})

function timeout(ms) { return new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), ms)) }

async function page(req) {
  const cache = await caches.open(SHELL)
  try {
    const res = await Promise.race([fetch(req), timeout(NAV_TIMEOUT)])
    if (res.ok) cache.put('/', res.clone())
    return res
  } catch (err) {
    const hit = await cache.match('/')
    if (hit) return hit
    throw err
  }
}

async function asset(req) {
  const cache = await caches.open(SHELL)
  const hit = await cache.match(req)
  if (hit) return hit
  const res = await fetch(req)
  if (res.ok) cache.put(req, res.clone())
  return res
}

async function trim(cache) {
  const keys = await cache.keys()
  for (const k of keys.slice(0, Math.max(0, keys.length - DATA_MAX))) await cache.delete(k)
}

// Ответ из кэша помечаем заголовком: страница покажет полосу «Нет связи с домом», а не сделает вид, что данные свежие.
async function stale(cache, req) {
  const hit = await cache.match(req)
  if (!hit) return null
  const headers = new Headers(hit.headers)
  headers.set('X-HH-Cached', '1')
  return new Response(await hit.blob(), { status: 200, headers })
}

async function data(req) {
  const cache = await caches.open(DATA)
  let res
  try {
    res = await fetch(req)
  } catch (err) {
    const old = await stale(cache, req)
    if (old) return old
    throw err
  }
  if (res.status === 200) {
    await cache.delete(req)            // свежая запись — в конец очереди
    await cache.put(req, res.clone())
    trim(cache)
  } else if (res.status === 401) {
    caches.delete(DATA)
  } else if (res.status >= 502 && res.status <= 504) {
    const old = await stale(cache, req)
    if (old) return old
  }
  return res
}

async function small(req) {
  const cache = await caches.open(SHELL)
  try {
    const res = await fetch(req)
    if (res.ok) cache.put(req, res.clone())
    return res
  } catch (err) {
    const hit = await cache.match(req)
    if (hit) return hit
    throw err
  }
}

self.addEventListener('fetch', (e) => {
  const req = e.request
  if (req.method !== 'GET') return
  const url = new URL(req.url)
  if (url.origin !== self.location.origin) return
  const p = url.pathname
  if (p.startsWith('/assets/')) e.respondWith(asset(req))
  else if (API.test(p)) e.respondWith(data(req))
  else if (req.mode === 'navigate' && !NOT_SHELL.test(p)) e.respondWith(page(req))
  else if (/^\/(icon[\w-]*\.(svg|png)|apple-touch-icon\.png|manifest\.webmanifest)$/.test(p)) e.respondWith(small(req))
})

// Уведомления в браузере на компьютере (Web Push, v0.21): сервер шлёт {title, body, tag} — показать; нажатие — открыть календарь.
self.addEventListener('push', (e) => {
  let d = {}
  try { d = e.data ? e.data.json() : {} } catch { d = { body: e.data && e.data.text() } }
  e.waitUntil(self.registration.showNotification(d.title || 'Календарь', {
    body: d.body || '', tag: d.tag || undefined, icon: '/icon-192.png', badge: '/icon-192.png', data: { url: '/' },
  }))
})
self.addEventListener('notificationclick', (e) => {
  e.notification.close()
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
    const w = list.find((c) => new URL(c.url).origin === self.location.origin)
    return w ? w.focus() : self.clients.openWindow('/')
  }))
})
