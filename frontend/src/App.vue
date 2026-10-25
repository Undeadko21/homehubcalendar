<template>
  <div class="app" :class="{ kiosk: state.kiosk, night }">
    <LoginScreen v-if="state.needLogin" />
    <div v-else-if="!state.config" class="boot">
      <p v-if="state.error">Сервер недоступен: {{ state.error }}. <button class="btn" @click="loadConfig">Повторить</button></p>
      <p v-else class="faint">Загружаю календарь…</p>
    </div>
    <template v-else>
      <header v-if="!state.kiosk" class="top">
        <div class="nav">
          <button class="btn icon" aria-label="Назад" @click="shift(-1)">‹</button>
          <button class="btn" @click="goToday">Сегодня</button>
          <button class="btn icon" aria-label="Вперёд" @click="shift(1)">›</button>
          <h1 class="range">{{ rangeLabel }}</h1>
        </div>
        <nav class="tabs" aria-label="Вид">
          <button v-for="v in VIEWS" :key="v.id" :class="{ on: state.view === v.id }" @click="setView(v.id)">
            {{ v.label }}
          </button>
        </nav>
        <div class="tools">
          <button class="btn icon" :title="syncTitle" :disabled="syncing" @click="doSync">
            <span :class="['sync-dot', syncState]"></span>{{ syncing ? 'Обновляю…' : 'Обновить' }}
          </button>
          <button class="btn icon" aria-label="Настройки" :class="{ on: state.view === 'settings' }" @click="setView('settings')">⚙</button>
        </div>
      </header>

      <PeopleBar v-if="state.view !== 'settings' && !state.kiosk" />

      <main class="main">
        <TodayView v-if="state.view === 'today'" />
        <TimelineView v-else-if="state.view === 'timeline'" />
        <CalendarView v-else-if="state.view === 'week' || state.view === 'month'" :mode="state.view" />
        <AgendaView v-else-if="state.view === 'agenda'" />
        <SettingsView v-else-if="state.view === 'settings'" />
      </main>

      <EventDialog />
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { state, loadConfig, setView, refreshStatus, syncNow, reload } from './lib/store'
import { addDays, startOfWeek, formatMonth, formatDayLong, formatDayMonth, relativeDayName } from './lib/dates'
import PeopleBar from './components/PeopleBar.vue'
import EventDialog from './components/EventDialog.vue'
import LoginScreen from './components/LoginScreen.vue'
import TodayView from './views/TodayView.vue'
import TimelineView from './views/TimelineView.vue'
import CalendarView from './views/CalendarView.vue'
import AgendaView from './views/AgendaView.vue'
import SettingsView from './views/SettingsView.vue'

const VIEWS = [
  { id: 'today', label: 'Сегодня' },
  { id: 'timeline', label: 'Лента' },
  { id: 'week', label: 'Неделя' },
  { id: 'month', label: 'Месяц' },
  { id: 'agenda', label: 'Список' },
]

const syncing = ref(false)
const night = ref(false)

function shift(dir) {
  const c = new Date(state.cursor)
  if (state.view === 'month') c.setMonth(c.getMonth() + dir)
  else if (state.view === 'today') c.setDate(c.getDate() + dir)
  else if (state.view === 'timeline') c.setDate(c.getDate() + state.timelineDays * dir)
  else c.setDate(c.getDate() + 7 * dir)
  state.cursor = c
}
function goToday() { state.cursor = new Date() }

const rangeLabel = computed(() => {
  const c = state.cursor
  switch (state.view) {
    case 'today': return relativeDayName(c) === 'Сегодня' ? formatDayLong(c) : relativeDayName(c)
    case 'month': return formatMonth(c)
    case 'settings': return 'Настройки'
    case 'agenda': return `С ${formatDayMonth(c)}`
    case 'timeline':
      if (state.timelineDays === 1) return relativeDayName(c)
      if (state.timelineDays === 3) return `${formatDayMonth(c)} — ${formatDayMonth(addDays(c, 2))}`
    // fallthrough — неделя
    default: {
      const s = startOfWeek(c), e = addDays(s, 6)
      return s.getMonth() === e.getMonth()
        ? `${s.getDate()}–${formatDayMonth(e)}`
        : `${formatDayMonth(s)} — ${formatDayMonth(e)}`
    }
  }
})

const syncState = computed(() => {
  const src = state.status?.sources || []
  if (!src.length) return 'unknown'
  return src.some((s) => s.last_error) ? 'error' : 'ok'
})
const syncTitle = computed(() => {
  const src = state.status?.sources || []
  const err = src.filter((s) => s.last_error)
  if (err.length) return 'Ошибки синхронизации: ' + err.map((s) => s.source_id).join(', ')
  const last = src.map((s) => s.last_ok).filter(Boolean).sort().pop()
  return last ? 'Обновлено ' + new Date(last).toLocaleString('ru-RU') : 'Ещё не синхронизировано'
})

async function doSync() {
  syncing.value = true
  try { await syncNow() } finally { syncing.value = false }
}

let timers = []
function tickNight() {
  const h = new Date().getHours()
  night.value = state.kiosk && (h >= 23 || h < 6)
}

onMounted(async () => {
  await loadConfig()
  await refreshStatus()
  tickNight()
  // Данные на сервере обновляются по расписанию — просто перечитываем их.
  timers.push(setInterval(reload, (state.kiosk ? 5 : 10) * 60000))
  timers.push(setInterval(tickNight, 60000))
  // В киоске после полуночи возвращаемся к сегодняшнему дню.
  timers.push(setInterval(() => { if (state.kiosk) state.cursor = new Date() }, 30 * 60000))
  const rotate = Number(new URLSearchParams(location.search).get('rotate'))
  if (state.kiosk && rotate > 0) {
    const cycle = ['today', 'timeline']
    timers.push(setInterval(() => {
      state.view = cycle[(cycle.indexOf(state.view) + 1) % cycle.length]
    }, rotate * 1000))
  }
})
onUnmounted(() => timers.forEach(clearInterval))
</script>

<style scoped>
.app { min-height: 100vh; display: flex; flex-direction: column; transition: filter .6s; }
.boot { display: grid; place-items: center; min-height: 100vh; padding: 24px; text-align: center; }
.top {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  padding: 12px 20px; border-bottom: 1px solid var(--line); background: var(--surface);
  position: sticky; top: 0; z-index: 20;
}
.nav { display: flex; align-items: center; gap: 6px; flex: 1 1 0; min-width: 0; }
.range { font-size: 20px; font-weight: 700; margin: 0 0 0 8px; letter-spacing: -0.01em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tabs { display: flex; background: var(--surface-2); border-radius: 999px; padding: 3px; overflow-x: auto; }
.tabs button { border: 0; background: none; padding: 6px 14px; border-radius: 999px; white-space: nowrap; color: var(--ink-2); }
.tabs button.on { background: var(--surface); color: var(--ink); font-weight: 600; box-shadow: var(--shadow); }
.tools { display: flex; gap: 6px; }
.tools .on { background: var(--surface-2); }
.sync-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ink-3); display: inline-block; }
.sync-dot.ok { background: #22a06b; }
.sync-dot.error { background: var(--now); }
.main { flex: 1; display: flex; flex-direction: column; min-height: 0; }

@media (max-width: 760px) {
  .top { padding: 10px 12px; gap: 8px; }
  .tabs { order: 3; width: 100%; }
  .tabs button { flex: 1; padding: 6px 8px; }
  .range { font-size: 16px; margin-left: 4px; }
  .nav .btn:not(.icon) { padding: 7px 9px; }
  .tools .btn { font-size: 0; gap: 0; padding: 9px; }
  .tools .btn .sync-dot { margin: 0; }
  .tools .btn:last-child { font-size: 15px; padding: 5px 9px; }
}
</style>
