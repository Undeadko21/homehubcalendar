// Общее состояние приложения: настройки, фильтр людей, загрузка событий.
import { reactive, computed } from 'vue'
import { api, CLIENT_ID, setAuthHandler } from './api'
import { isoLocal, isoDate } from './dates'

const LS_KEY = 'homecal.prefs'

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(LS_KEY) || '{}') } catch { return {} }
}
function savePrefs() {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify({ hiddenPeople: state.hiddenPeople, view: state.view, calView: state.calView, timelineDays: state.timelineDays, weekDays: state.weekDaysPref }))
  } catch {}
}

const CFG_KEY = 'homecal.config'
const EV_KEY = 'homecal.events'
function readJson(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key) || 'null') ?? fallback } catch { return fallback }
}
function writeJson(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)) } catch {}
}
// Выход/потеря доступа: забываем сохранённые данные семьи.
function forgetCached() {
  try { localStorage.removeItem(CFG_KEY); localStorage.removeItem(EV_KEY) } catch {}
}

const prefs = loadPrefs()
const params = new URLSearchParams(location.search)

export const state = reactive({
  config: readJson(CFG_KEY, null), // прошлые настройки — экран рисуется сразу, свежие подтянутся
  error: null,
  needLogin: false,
  // На телефоне приложение открывается на месяце, как Календарь на iPhone.
  view: params.get('view') || (params.has('kiosk') ? prefs.view : (typeof matchMedia === 'function' && matchMedia('(max-width: 599px)').matches ? 'month' : prefs.view)) || 'today',
  kiosk: params.has('kiosk'),
  cursor: new Date(), // дата, вокруг которой строится текущий вид
  hiddenPeople: prefs.hiddenPeople || [],
  status: null,
  revision: 0, // увеличивается после синхронизации — виды перезагружают данные
  selected: null, // открытое в карточке событие
  timelineDays: prefs.timelineDays || 7,
  weekDaysPref: prefs.weekDays || null, // 3 | 5 | 7; пусто — по размеру экрана
  calView: prefs.calView || 'timeline', // последний календарный вид (вкладка «Календарь» на телефоне)
  moveWarn: null, // предупреждение о конфликтах при переносе: { e, items, resolve }
  moveAsk: null, // перенос повторяющегося события: ждём «только это / вся серия»
  wizard: false, // мастер секции
  editor: null, // { event } — правка, {} — новое событие
  peopleSheet: false, // лист «Люди» на телефоне
  personSheet: null, // id человека, чей профиль открыт
})

export const CAL_VIEWS = ['timeline', 'week', 'month', 'agenda']

// Узкий экран (телефон): «Неделя» показывает 3 дня, как iPhone в портретной ориентации.
const mq = typeof matchMedia === 'function' ? matchMedia('(max-width: 599px)') : null
export const screen = reactive({ narrow: !!mq?.matches })
mq?.addEventListener?.('change', (e) => { screen.narrow = e.matches })
export const weekDays = () => state.weekDaysPref || (screen.narrow ? 3 : 7)
export function setWeekDays(n) {
  state.weekDaysPref = n
  savePrefs()
}

export const writableCalendars = () => (state.config?.calendars || []).filter((c) => c.writable && !c.hidden)

export function newEvent(date, quick) { state.editor = { date: date || state.cursor, ...(quick ? { quick } : {}) } }
export function editEvent(e) { state.editor = { event: e } }

export function openEvent(e) {
  // Поездка («Отвезти Марка…») открывает карточку исходного события ребёнка.
  state.selected = e?.duty ? e.duty.parent : e
}

// Перечитать открытое событие после изменений (участники, поездки).
export async function refreshSelected() {
  const e = state.selected
  if (!e) return
  const d = new Date(e.all_day ? e.start + 'T00:00' : e.start)
  const from = new Date(d); from.setDate(from.getDate() - 1)
  const to = new Date(d); to.setDate(to.getDate() + 2)
  const list = await api.events(isoLocal(from), isoLocal(to))
  const fresh = list.find((x) => x.id === e.id) || list.find((x) => x.uid === e.uid && x.start === e.start)
  if (fresh && state.selected?.id === e.id) state.selected = fresh
}

export const people = computed(() => (state.config?.people || []).filter((p) => !p.hidden))
export const personById = computed(() => Object.fromEntries((state.config?.people || []).map((p) => [p.id, p])))
export const visiblePeople = computed(() => people.value.filter((p) => !state.hiddenPeople.includes(p.id)))

export function setTimelineDays(n) {
  state.timelineDays = n
  savePrefs()
}

export function setView(v) {
  state.view = v
  if (CAL_VIEWS.includes(v)) state.calView = v
  savePrefs()
}

export function togglePerson(id) {
  const i = state.hiddenPeople.indexOf(id)
  if (i >= 0) state.hiddenPeople.splice(i, 1)
  else state.hiddenPeople.push(id)
  savePrefs()
}

export function showOnly(id) {
  state.hiddenPeople = people.value.map((p) => p.id).filter((x) => x !== id)
  savePrefs()
}

export function showAll() {
  state.hiddenPeople = []
  savePrefs()
}

// Цвет события: свой/общий цвет (если задан), иначе цвет первого видимого участника.
export function eventColor(e) {
  if (e.color) return e.color
  const p = e.people.map((id) => personById.value[id]).find(Boolean)
  return p?.color || '#8a94a6'
}

export function isEventVisible(e) {
  return e.people.some((id) => !state.hiddenPeople.includes(id))
}

setAuthHandler(() => { state.needLogin = true; state.config = null })

export async function loadConfig() {
  try {
    state.config = await api.config()
    writeJson(CFG_KEY, state.config)
    state.error = null
    state.needLogin = false
    if (state.config.title) document.title = state.config.title
  } catch (e) {
    if (e.auth) { state.needLogin = true; state.config = null; forgetCached() }
    else if (!state.config) state.error = e.message
  }
}

const cache = new Map()

// Последние несколько диапазонов лежат в localStorage: открытие приложения не ждёт сервер.
function saveEventsCache(key, list) {
  const all = readJson(EV_KEY, {})
  all[key] = { t: Date.now(), list }
  const keys = Object.keys(all).sort((a, b) => all[b].t - all[a].t)
  for (const k of keys.slice(6)) delete all[k]
  try {
    localStorage.setItem(EV_KEY, JSON.stringify(all))
  } catch { // не влезло — оставляем только свежий ответ
    try { localStorage.setItem(EV_KEY, JSON.stringify({ [key]: all[key] })) } catch {}
  }
}

// События и особые дни грузятся независимо: праздники не должны задерживать показ событий.
export function fetchRange(start, end) {
  const key = `${state.revision}|${+start}|${+end}`
  if (cache.has(key)) return cache.get(key)
  const ckey = `${isoLocal(start)}|${isoLocal(end)}`
  const events = api.events(isoLocal(start), isoLocal(end))
  events.then((list) => saveEventsCache(ckey, list)).catch(() => {})
  const holidays = api.holidays(isoDate(start), isoDate(end)).catch(() => [])
  // cached — прошлый ответ для этого диапазона: показываем сразу, пока идёт запрос.
  const entry = { events, holidays, cached: readJson(EV_KEY, {})[ckey]?.list || null }
  cache.set(key, entry)
  events.catch(() => cache.delete(key))
  if (cache.size > 30) cache.delete(cache.keys().next().value)
  return entry
}

// Версия интерфейса, с которой собрана эта страница (хеш коммита подставляет сборка образа), и проверка, не вышла ли новее.
export const UI_BUILD = import.meta.env.VITE_BUILD || ''
let checking = false
export async function checkUiVersion() {
  if (!UI_BUILD || checking) return
  checking = true
  try {
    const r = await fetch('/api/health', { cache: 'no-store' })
    const v = String((await r.json()).version || '')
    const server = v.includes('+') ? v.split('+')[1] : ''
    if (server && server !== UI_BUILD) {
      // Один раз на версию: если страница всё равно приходит старой, не крутимся в перезагрузках.
      let done = null
      try { done = sessionStorage.getItem('homecal.reloaded') } catch {}
      if (done === server) return
      try { sessionStorage.setItem('homecal.reloaded', server) } catch {}
      location.reload() // приложение держало старую страницу — берём новую
    }
  } catch {} finally { checking = false }
}
if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') checkUiVersion() })
  setInterval(checkUiVersion, 5 * 60 * 1000)
  setTimeout(checkUiVersion, 3000)
}

// Живое обновление: сервер сообщает по SSE, что данные изменились (с этого или другого устройства) — перезагружаемся.
let live = null
export function connectLive() {
  if (live || typeof EventSource === 'undefined') return
  let rev = null
  let t = 0
  live = new EventSource('/api/stream')
  live.onmessage = (m) => {
    let d
    try { d = JSON.parse(m.data) } catch { d = { rev: m.data } }
    // Свою запись пропускаем, если экран только что перезагрузился сам; иначе (запись без перезагрузки) обновляемся как раньше.
    const ownDone = d.o === CLIENT_ID && Date.now() - lastReloadAt < 5000
    if (rev !== null && d.rev !== rev && !ownDone) {
      clearTimeout(t)
      t = setTimeout(() => reload().catch(() => {}), 400)
    }
    rev = d.rev
  }
}

export async function refreshStatus() {
  try { state.status = await api.status() } catch {}
}

export async function syncNow() {
  await api.sync()
  await reload()
}

let lastReloadAt = 0

export async function reload() {
  lastReloadAt = Date.now()
  // Внутри Android-приложения — сразу обновить виджет на рабочем столе.
  try { window.HomeHubApp?.refreshWidget() } catch {}
  cache.clear()
  await loadConfig()
  await refreshStatus()
  state.revision++
}
