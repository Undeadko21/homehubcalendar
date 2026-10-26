<template>
  <div class="app" :class="{ kiosk: state.kiosk, night }">
    <LoginScreen v-if="state.needLogin" />
    <div v-else-if="!state.config" class="boot">
      <p v-if="state.error">Сервер недоступен: {{ state.error }}. <button class="btn" @click="loadConfig">Повторить</button></p>
      <p v-else class="faint">Загружаю календарь…</p>
    </div>
    <template v-else>
      <!-- Боковая панель (компьютер) -->
      <aside v-if="!state.kiosk" class="sidebar" aria-label="Боковая панель">
        <MiniMonth />
        <PeopleList class="side-people" />
        <nav class="side-nav" aria-label="Разделы">
          <button :class="{ on: state.view === 'free' }" @click="setView('free')">
            <IconFree /> Свободное время
          </button>
          <button :class="{ on: state.view === 'settings' }" @click="setView('settings')">
            <IconGear /> Настройки
          </button>
        </nav>
        <p class="sync-line" :title="syncTitle">
          <span :class="['sync-dot', syncState]"></span>
          {{ syncShort }}
          <button class="btn sm" :disabled="syncing" @click="doSync">{{ syncing ? 'Обновляю…' : 'Обновить' }}</button>
        </p>
      </aside>

      <div class="content">
        <header v-if="!state.kiosk" ref="toolbarEl" class="toolbar">
          <div class="nav-row">
            <div class="navs" :class="{ hide: !navigable }">
              <button class="btn icon" aria-label="Назад" @click="shift(-1)" :disabled="!navigable">‹</button>
              <button class="btn today-btn" @click="goToday" :disabled="!navigable">Сегодня</button>
              <button class="btn icon" aria-label="Вперёд" @click="shift(1)" :disabled="!navigable">›</button>
            </div>
            <div class="seg main-seg" role="tablist" aria-label="Вид">
              <button v-for="v in VIEWS" :key="v.id" role="tab" :aria-selected="state.view === v.id"
                      :class="{ on: state.view === v.id }" @click="setView(v.id)">{{ v.label }}</button>
            </div>
            <span class="m-sync" :title="syncTitle"><span :class="['sync-dot', syncState]"></span></span>
          </div>
          <h1 class="title">
            <span class="t-main">{{ title.main }}</span>
            <span v-if="title.sub" class="t-sub">{{ title.sub }}</span>
          </h1>
          <div v-if="isCalTab" class="seg cal-seg" role="tablist" aria-label="Вид календаря">
            <button v-for="v in CAL_TABS" :key="v.id" role="tab" :aria-selected="state.view === v.id"
                    :class="{ on: state.view === v.id }" @click="setView(v.id)">{{ v.label }}</button>
          </div>
        </header>

        <div v-if="needsAccount && state.view !== 'settings' && !state.kiosk" class="setup">
          <span>Подключите Яндекс.Календарь: нужны логин и пароль приложения.</span>
          <button class="btn filled" @click="setView('settings')">Подключить</button>
        </div>

        <main class="main">
          <TodayView v-if="state.view === 'today'" />
          <TimelineView v-else-if="state.view === 'timeline'" />
          <CalendarView v-else-if="state.view === 'week' || state.view === 'month'" :mode="state.view" />
          <AgendaView v-else-if="state.view === 'agenda'" />
          <FreeView v-else-if="state.view === 'free'" />
          <SettingsView v-else-if="state.view === 'settings'" />
        </main>
      </div>

      <!-- Нижние вкладки (телефон) -->
      <nav v-if="!state.kiosk" class="tabbar" aria-label="Разделы">
        <button :class="{ on: state.view === 'today' }" @click="setView('today')"><IconToday :day="new Date().getDate()" /><span>Сегодня</span></button>
        <button :class="{ on: isCalTab }" @click="setView(state.calView)"><IconCal /><span>Календарь</span></button>
        <button :class="{ on: state.view === 'free' }" @click="setView('free')"><IconFree /><span>Свободно</span></button>
        <button :class="{ on: state.peopleSheet }" @click="state.peopleSheet = true"><IconPeople /><span>Люди</span></button>
        <button :class="{ on: state.view === 'settings' }" @click="setView('settings')"><IconGear /><span>Настройки</span></button>
      </nav>

      <Sheet :open="state.peopleSheet" title="Чьи события показывать" @close="state.peopleSheet = false">
        <PeopleList />
      </Sheet>
      <EventDialog />
    </template>
  </div>
</template>

<script setup>
import { computed, h, onMounted, onUnmounted, ref, watch } from 'vue'
import { state, loadConfig, setView, refreshStatus, syncNow, reload, CAL_VIEWS, weekDays } from './lib/store'
import { addDays, startOfWeek, relativeDayName, cap } from './lib/dates'
import EventDialog from './components/EventDialog.vue'
import LoginScreen from './components/LoginScreen.vue'
import MiniMonth from './components/MiniMonth.vue'
import PeopleList from './components/PeopleList.vue'
import Sheet from './components/Sheet.vue'
import TodayView from './views/TodayView.vue'
import TimelineView from './views/TimelineView.vue'
import CalendarView from './views/CalendarView.vue'
import AgendaView from './views/AgendaView.vue'
import FreeView from './views/FreeView.vue'
import SettingsView from './views/SettingsView.vue'

const VIEWS = [
  { id: 'today', label: 'Сегодня' },
  { id: 'timeline', label: 'Лента' },
  { id: 'week', label: 'Неделя' },
  { id: 'month', label: 'Месяц' },
  { id: 'agenda', label: 'Список' },
]
const CAL_TABS = VIEWS.slice(1)
const isCalTab = computed(() => CAL_VIEWS.includes(state.view))
const navigable = computed(() => !['settings', 'free'].includes(state.view))

// --- значки нижней панели (тонкие линии, как SF Symbols) ---
const svg = (paths, extra = {}) => () => h('svg', { viewBox: '0 0 24 24', class: 'ico', 'aria-hidden': 'true', ...extra }, paths)
const IconCal = svg([h('rect', { x: 3.5, y: 5, width: 17, height: 15.5, rx: 3 }), h('path', { d: 'M3.5 9.5h17M8 3v4M16 3v4' })])
const IconFree = svg([h('circle', { cx: 12, cy: 12, r: 8.5 }), h('path', { d: 'M12 7.5V12l3 2' })])
const IconPeople = svg([h('circle', { cx: 9, cy: 8.5, r: 3.2 }), h('path', { d: 'M3.5 19c.6-3.2 2.8-5 5.5-5s4.9 1.8 5.5 5' }), h('circle', { cx: 16.5, cy: 9.5, r: 2.6 }), h('path', { d: 'M15.5 14.2c2.6-.3 4.6 1.3 5 4.3' })])
const IconGear = svg([h('circle', { cx: 12, cy: 12, r: 3 }), h('path', { d: 'M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7' })])
const IconToday = (props) => h('svg', { viewBox: '0 0 24 24', class: 'ico', 'aria-hidden': 'true' }, [
  h('rect', { x: 3.5, y: 4, width: 17, height: 16.5, rx: 3 }),
  h('text', { x: 12, y: 17.2, 'text-anchor': 'middle', 'font-size': 9, 'font-weight': 600, stroke: 'none', fill: 'currentColor' }, String(props.day)),
])

// Высота шапки — для «липких» заголовков дней в списке.
const toolbarEl = ref(null)
let ro
watch(toolbarEl, (el) => {
  ro?.disconnect()
  if (!el) return
  ro = new ResizeObserver(() => document.documentElement.style.setProperty('--toolbar-h', el.offsetHeight + 'px'))
  ro.observe(el)
})

const syncing = ref(false)
const night = ref(false)

function shift(dir) {
  const c = new Date(state.cursor)
  if (state.view === 'month') c.setMonth(c.getMonth() + dir)
  else if (state.view === 'today') c.setDate(c.getDate() + dir)
  else if (state.view === 'timeline') c.setDate(c.getDate() + state.timelineDays * dir)
  else c.setDate(c.getDate() + weekDays() * dir)
  state.cursor = c
}
function goToday() { state.cursor = new Date() }

const monthName = (d) => cap(d.toLocaleDateString('ru-RU', { month: 'long' }))
const title = computed(() => {
  const c = state.cursor
  switch (state.view) {
    case 'settings': return { main: 'Настройки' }
    case 'free': return { main: 'Свободное время' }
    case 'today': {
      const rel = relativeDayName(c)
      const date = c.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
      const wd = cap(c.toLocaleDateString('ru-RU', { weekday: 'long' }))
      return rel === 'Сегодня' || rel === 'Завтра' || rel === 'Вчера'
        ? { main: rel, sub: `${wd}, ${date}` }
        : { main: date, sub: wd }
    }
    case 'month':
    case 'agenda':
      return { main: monthName(c), sub: String(c.getFullYear()) }
    default: {
      const days = state.view === 'timeline' ? state.timelineDays : weekDays()
      const s = days !== 7 ? c : startOfWeek(c)
      const e = addDays(s, days - 1)
      const main = s.getMonth() === e.getMonth() ? monthName(s) : `${monthName(s)} – ${monthName(e)}`
      return { main, sub: String(e.getFullYear()) }
    }
  }
})

const needsAccount = computed(() => (state.config?.accounts || []).some((a) => !a.username || !a.has_password))
const syncState = computed(() => {
  const src = state.status?.sources || []
  if (!src.length) return 'unknown'
  return src.some((s) => s.last_error) ? 'error' : 'ok'
})
const lastOk = computed(() => (state.status?.sources || []).map((s) => s.last_ok).filter(Boolean).sort().pop())
const syncTitle = computed(() => {
  const err = (state.status?.sources || []).filter((s) => s.last_error)
  if (err.length) return 'Ошибка синхронизации: ' + err.map((s) => s.last_error).join('; ')
  return lastOk.value ? 'Обновлено ' + new Date(lastOk.value).toLocaleString('ru-RU') : 'Ещё не синхронизировано'
})
const syncShort = computed(() => {
  if (syncState.value === 'error') return 'Ошибка обновления'
  if (!lastOk.value) return 'Не обновлялось'
  return 'Обновлено в ' + new Date(lastOk.value).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
})

async function doSync() {
  syncing.value = true
  try { await syncNow() } finally { syncing.value = false }
}

const timers = []
function tickNight() {
  const hr = new Date().getHours()
  night.value = state.kiosk && (hr >= 23 || hr < 6)
}

onMounted(async () => {
  await loadConfig()
  await refreshStatus()
  tickNight()
  timers.push(setInterval(reload, (state.kiosk ? 5 : 10) * 60000))
  timers.push(setInterval(tickNight, 60000))
  timers.push(setInterval(() => { if (state.kiosk) state.cursor = new Date() }, 30 * 60000))
  const rotate = Number(new URLSearchParams(location.search).get('rotate'))
  if (state.kiosk && rotate > 0) {
    const cycle = ['today', 'timeline']
    timers.push(setInterval(() => {
      state.view = cycle[(cycle.indexOf(state.view) + 1) % cycle.length]
    }, rotate * 1000))
  }
})
onUnmounted(() => { timers.forEach(clearInterval); ro?.disconnect() })
</script>

<style scoped>
.app { min-height: 100vh; display: flex; transition: filter .6s; }
.boot { display: grid; place-items: center; min-height: 100vh; width: 100%; padding: 24px; text-align: center; }

/* --- боковая панель --- */
.sidebar {
  width: var(--sidebar); flex: none; position: sticky; top: 0; height: 100vh; overflow-y: auto;
  background: var(--surface-2); border-right: .5px solid var(--line);
  padding: 14px 10px 12px; display: flex; flex-direction: column; gap: 18px;
}
:root[data-theme='dark'] .sidebar { background: #1c1c1e; }
@media (prefers-color-scheme: dark) { :root:not([data-theme='light']) .sidebar { background: #1c1c1e; } }
.side-people { flex: 1; }
.side-nav { display: flex; flex-direction: column; gap: 1px; }
.side-nav button {
  display: flex; align-items: center; gap: 9px; border: 0; background: none; text-align: left;
  padding: 6px 8px; border-radius: 7px; font-size: 14px; color: var(--ink);
}
.side-nav button:hover { background: var(--fill); }
.side-nav button.on { background: var(--fill); font-weight: 600; }
.side-nav :deep(.ico) { width: 18px; height: 18px; color: var(--tint); }
.sync-line { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ink-2); margin: 0; padding: 0 8px; }
.sync-line .sm { margin-left: auto; font-size: 12px; padding: 2px 6px; }
.sync-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--ink-3); display: inline-block; flex: none; }
.sync-dot.ok { background: var(--ok); }
.sync-dot.error { background: var(--red); }

/* --- шапка --- */
.content { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.toolbar {
  position: sticky; top: 0; z-index: 20;
  background: color-mix(in srgb, var(--bg) 82%, transparent);
  backdrop-filter: saturate(180%) blur(20px); -webkit-backdrop-filter: saturate(180%) blur(20px);
  border-bottom: .5px solid var(--line);
  display: grid; grid-template-columns: auto 1fr; grid-template-areas: 'title nav';
  align-items: center; gap: 8px 16px; padding: 12px 20px;
}
.nav-row { grid-area: nav; display: flex; align-items: center; justify-content: flex-end; gap: 16px; }
.navs { display: flex; align-items: center; order: 2; }
.navs.hide { opacity: .35; pointer-events: none; }
.navs .icon { font-size: 26px; font-weight: 300; }
.today-btn { font-weight: 600; }
.main-seg { order: 1; }
.m-sync { display: none; }
.title { grid-area: title; margin: 0; font-family: var(--font-display); font-size: 28px; line-height: 1.1; letter-spacing: -0.02em; white-space: nowrap; }
.t-main { font-weight: 700; }
.t-sub { font-weight: 400; margin-left: 8px; color: var(--ink-2); }
.cal-seg { display: none; }

.setup {
  display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;
  margin: 12px 20px 0; padding: 12px 16px; border-radius: var(--radius-m);
  background: var(--surface-2); font-weight: 600;
}
.main { flex: 1; display: flex; flex-direction: column; min-height: 0; }
.tabbar { display: none; }

/* --- телефон и узкие окна --- */
@media (max-width: 899px) {
  .app { display: block; padding-bottom: calc(var(--tabbar) + env(safe-area-inset-bottom)); }
  .sidebar { display: none; }
  .toolbar { grid-template-columns: 1fr; grid-template-areas: 'nav' 'title' 'seg'; padding: 6px 12px 10px; gap: 2px; }
  .nav-row { justify-content: space-between; }
  .navs { order: 0; margin-left: -8px; }
  .main-seg { display: none; }
  .m-sync { display: inline-flex; padding: 8px; }
  .title { font-size: 30px; padding: 0 4px; white-space: normal; }
  .t-sub { font-size: 17px; display: block; margin: 2px 0 0; }
  .navs.hide { visibility: hidden; }
  .cal-seg { display: flex; grid-area: seg; margin-top: 8px; }
  .cal-seg button { flex: 1; padding: 6px 4px; }
  .setup { margin: 10px 12px 0; }

  .tabbar {
    display: flex; position: fixed; left: 0; right: 0; bottom: 0; z-index: 40;
    height: calc(var(--tabbar) + env(safe-area-inset-bottom)); padding-bottom: env(safe-area-inset-bottom);
    background: color-mix(in srgb, var(--surface-2) 85%, transparent);
    backdrop-filter: saturate(180%) blur(20px); -webkit-backdrop-filter: saturate(180%) blur(20px);
    border-top: .5px solid var(--line);
  }
  .tabbar button {
    flex: 1; border: 0; background: none; display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 2px; font-size: 10px; font-weight: 500; color: var(--ink-3);
  }
  .tabbar button.on { color: var(--tint); }
  .tabbar :deep(.ico) { width: 26px; height: 26px; }
}
:deep(.ico) { fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.kiosk .content { padding-top: 0; }
</style>
