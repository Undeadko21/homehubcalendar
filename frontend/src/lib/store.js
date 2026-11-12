// Общее состояние приложения: настройки, фильтр людей, загрузка событий.
import { reactive, computed, nextTick } from 'vue'
import { api, CLIENT_ID, setAuthHandler } from './api'
import { isoLocal, isoDate } from './dates'

const LS_KEY = 'homecal.prefs'

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(LS_KEY) || '{}') } catch { return {} }
}
export function savePrefs() {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify({ hiddenPeople: state.hiddenPeople, view: state.view, calView: state.calView, timelineDays: state.timelineDays, weekDays: state.weekDaysPref,
      textSize: state.textSize, initials: state.initials, onboarded: state.onboarded, haptics: state.haptics, icons: state.icons, weekDense: state.weekDense }))
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
  toast: null, // { text, undo } — плашка внизу с «Отменить»
  quickAdd: false, // лист единого «+»
  listsRev: 0, // списки изменились не на странице списков — перечитать
  textSize: params.get('size') || prefs.textSize || 'normal', // compact | normal | large
  initials: params.has('initials') ? params.get('initials') !== '0' : !!prefs.initials, // буква человека на плашке (не только цвет)
  onboarded: !!prefs.onboarded, // знакомство пройдено на этом устройстве
  onboarding: false,
  haptics: prefs.haptics !== false, // отклик (вибрация) на важные нажатия
  icons: params.has('icons') ? params.get('icons') !== '0' : !!prefs.icons, // значки по словам в названии: 🏊 🩺 🎂
  weekDense: prefs.weekDense !== false, // «Неделя» на компьютере плотнее (час ниже)
  datePicker: false, // лист «Перейти к дате» (нажатие на заголовок)
  navDir: 0, // направление последнего сдвига дня/недели — для анимации
})

// Внешний вид: размер текста — множитель --fs (сборка переводит все font-size в calc(… * var(--fs))).
const SIZES = { compact: 0.9, normal: 1, large: 1.15, xlarge: 1.3 }
export function applyLook() {
  if (typeof document === 'undefined') return
  const k = SIZES[state.textSize] || 1
  document.documentElement.style.setProperty('--fs', String(k))
  document.documentElement.dataset.size = state.textSize
}
export function setTextSize(v) { state.textSize = v; savePrefs(); applyLook() }
export function setInitials(v) { state.initials = !!v; savePrefs() }
export function setHaptics(v) { state.haptics = !!v; savePrefs() }
export function setIcons(v) { state.icons = !!v; savePrefs() }
export function finishOnboarding() { state.onboarded = true; state.onboarding = false; savePrefs() }
applyLook()

// Плашка внизу экрана: «Перенесено · Отменить». undo — функция или пусто.
let toastTimer = 0
export function toast(text, undo) {
  clearTimeout(toastTimer)
  state.toast = { text, undo: undo || null, busy: false }
  toastTimer = setTimeout(() => { state.toast = null }, undo ? 6000 : 3500)
}
export function hideToast() { clearTimeout(toastTimer); state.toast = null }
export async function runToastUndo() {
  const t = state.toast
  if (!t?.undo || t.busy) return
  clearTimeout(toastTimer)
  t.busy = true
  try {
    await t.undo()
    toast('Отменено')
  } catch (err) {
    toast('Не удалось отменить: ' + err.message)
  }
}
// Отмена записи в календарь по номерам журнала, которые вернул сервер (в обратном порядке).
export function undoOf(changes) {
  if (!changes?.length) return null
  return async () => {
    for (const id of [...changes].reverse()) await api.undoChange(id)
    await reload()
  }
}

export const CAL_VIEWS = ['timeline', 'week', 'family', 'month', 'agenda']

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

// Перейти к дню на ленте (из поиска, пустых состояний).
export function goToDay(date) {
  state.cursor = new Date(date)
  state.selected = null
  setView('timeline')
}

// Единое «Быстро»: сервер решает, событие это, дело или покупка. Событие открывается в форме для проверки,
// дело и покупки добавляются сразу (с «Отменить»). Возвращает вид того, что получилось.
export async function quickAdd(text, date) {
  const r = await api.quick(text)
  if (r.kind !== 'event') import('./haptic').then((m) => m.haptic('success'))
  if (r.kind === 'event') {
    if (!writableCalendars().length) throw new Error('Нет календаря, в который можно записать событие')
    state.editor = { date: date || state.cursor, quick: text }
    return 'event'
  }
  if (!r.list_id) throw new Error('Сначала создайте список в разделе «Списки»')
  const ids = []
  if (r.kind === 'shopping') {
    for (const item of r.items) ids.push((await api.addItem(r.list_id, item)).id)
    toast(`В «${r.list_name}»: ${r.items.join(', ')}`, undoItems(ids))
  } else {
    ids.push((await api.addItem(r.list_id, r.text, r.person_id, r.due)).id)
    const due = r.due ? ' · до ' + new Date(r.due + 'T00:00:00').toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' }) : ''
    toast(`В «${r.list_name}»: ${r.text}${due}`, undoItems(ids))
  }
  state.listsRev++
  return r.kind
}
function undoItems(ids) {
  return async () => {
    for (const id of ids) await api.deleteItem(id)
    state.listsRev++
  }
}

// Буква человека для плашек: первая буква имени, а если у двоих совпадает — две.
export const personMark = computed(() => {
  const list = (state.config?.people || []).filter((p) => !p.id.startsWith('_'))
  const first = (p) => (p.name || '?').trim().slice(0, 1).toUpperCase()
  const count = {}
  for (const p of list) count[first(p)] = (count[first(p)] || 0) + 1
  return Object.fromEntries(list.map((p) => [p.id, count[first(p)] > 1 ? (p.name || '?').trim().slice(0, 2) : first(p)]))
})

export const people = computed(() => (state.config?.people || []).filter((p) => !p.hidden))
export const personById = computed(() => Object.fromEntries((state.config?.people || []).map((p) => [p.id, p])))
export const visiblePeople = computed(() => people.value.filter((p) => !state.hiddenPeople.includes(p.id)))

export function setTimelineDays(n) {
  state.timelineDays = n
  savePrefs()
}

// Плавная смена экрана/дня: View Transitions API там, где он есть (Chrome/Android WebView 111+, Safari 18+);
// направление (−1 назад, 1 вперёд, 0 — смена вида) задаёт анимацию в styles.css. Без поддержки — как раньше, сразу.
export function animate(dir, fn) {
  const reduce = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
  if (typeof document === 'undefined' || !document.startViewTransition || reduce || state.kiosk) { fn(); return }
  document.documentElement.dataset.nav = dir > 0 ? 'fwd' : dir < 0 ? 'back' : 'fade'
  try {
    document.startViewTransition(async () => { fn(); await nextTick() })
  } catch { fn() }
}

export function setView(v) {
  if (v === state.view) return
  animate(0, () => {
    state.view = v
    if (CAL_VIEWS.includes(v)) state.calView = v
    savePrefs()
  })
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
