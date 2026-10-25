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
    localStorage.setItem(LS_KEY, JSON.stringify({ hiddenPeople: state.hiddenPeople, view: state.view, timelineDays: state.timelineDays }))
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
})

export function openEvent(e) {
  state.selected = e
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

export async function fetchRange(start, end) {
  const key = `${state.revision}|${+start}|${+end}`
  if (cache.has(key)) return cache.get(key)
  const p = Promise.all([
    api.events(isoLocal(start), isoLocal(end)),
    api.holidays(isoDate(start), isoDate(end)).catch(() => []),
  ]).then(([events, holidays]) => ({ events, holidays }))
  cache.set(key, p)
  p.catch(() => cache.delete(key))
  if (cache.size > 30) cache.delete(cache.keys().next().value)
  return p
}

export async function refreshStatus() {
  try { state.status = await api.status() } catch {}
}

export async function syncNow() {
  await api.sync()
  await reload()
}

export async function reload() {
  cache.clear()
  await loadConfig()
  await refreshStatus()
  state.revision++
}
