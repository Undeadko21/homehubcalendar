// Общее состояние приложения: настройки, фильтр людей, загрузка событий.
import { reactive, computed } from 'vue'
import { api } from './api'
import { isoLocal, isoDate } from './dates'

const LS_KEY = 'homecal.prefs'

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(LS_KEY) || '{}') } catch { return {} }
}
function savePrefs() {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify({ hiddenPeople: state.hiddenPeople, view: state.view, calView: state.calView, timelineDays: state.timelineDays }))
  } catch {}
}

const prefs = loadPrefs()
const params = new URLSearchParams(location.search)

export const state = reactive({
  config: null,
  error: null,
  needLogin: false,
  view: params.get('view') || prefs.view || 'today',
  kiosk: params.has('kiosk'),
  cursor: new Date(), // дата, вокруг которой строится текущий вид
  hiddenPeople: prefs.hiddenPeople || [],
  status: null,
  revision: 0, // увеличивается после синхронизации — виды перезагружают данные
  selected: null, // открытое в карточке событие
  timelineDays: prefs.timelineDays || 7,
  calView: prefs.calView || 'timeline', // последний календарный вид (вкладка «Календарь» на телефоне)
  moveAsk: null, // перенос повторяющегося события: ждём «только это / вся серия»
  editor: null, // { event } — правка, {} — новое событие
  peopleSheet: false, // лист «Люди» на телефоне
})

export const CAL_VIEWS = ['timeline', 'week', 'month', 'agenda']

// Узкий экран (телефон): «Неделя» показывает 3 дня, как iPhone в портретной ориентации.
const mq = typeof matchMedia === 'function' ? matchMedia('(max-width: 599px)') : null
export const screen = reactive({ narrow: !!mq?.matches })
mq?.addEventListener?.('change', (e) => { screen.narrow = e.matches })
export const weekDays = () => (screen.narrow ? 3 : 7)

export const writableCalendars = () => (state.config?.calendars || []).filter((c) => c.writable && !c.hidden)

export function newEvent(date) { state.editor = { date: date || state.cursor } }
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

// Цвет события: цвет первого видимого участника.
export function eventColor(e) {
  const p = e.people.map((id) => personById.value[id]).find(Boolean)
  return p?.color || '#8a94a6'
}

export function isEventVisible(e) {
  return e.people.some((id) => !state.hiddenPeople.includes(id))
}

export async function loadConfig() {
  try {
    state.config = await api.config()
    state.error = null
    state.needLogin = false
    if (state.config.title) document.title = state.config.title
  } catch (e) {
    if (e.auth) state.needLogin = true
    else state.error = e.message
  }
}

const cache = new Map()

// События и особые дни грузятся независимо: праздники не должны задерживать показ событий.
export function fetchRange(start, end) {
  const key = `${state.revision}|${+start}|${+end}`
  if (cache.has(key)) return cache.get(key)
  const events = api.events(isoLocal(start), isoLocal(end))
  const holidays = api.holidays(isoDate(start), isoDate(end)).catch(() => [])
  const entry = { events, holidays }
  cache.set(key, entry)
  events.catch(() => cache.delete(key))
  if (cache.size > 30) cache.delete(cache.keys().next().value)
  return entry
}

export async function refreshStatus() {
  try { state.status = await api.status() } catch {}
}

export async function syncNow() {
  await api.sync()
  await reload()
}

export async function reload() {
  // Внутри Android-приложения — сразу обновить виджет на рабочем столе.
  try { window.HomeHubApp?.refreshWidget() } catch {}
  cache.clear()
  await loadConfig()
  await refreshStatus()
  state.revision++
}
