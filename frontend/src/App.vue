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
          <button :class="{ on: state.view === 'lists' }" @click="setView('lists')">
            <IconList /> Списки
          </button>
          <button :class="{ on: state.view === 'search' }" @click="setView('search')">
            <IconSearch /> Поиск
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
            <button class="btn icon add-btn" aria-label="Добавить событие, дело или покупку" @click="state.quickAdd = true">+</button>
            <button class="btn icon search-btn" aria-label="Поиск" @click="setView('search')"><IconSearch /></button>
            <span class="m-sync" :title="syncTitle"><span :class="['sync-dot', syncState]"></span></span>
          </div>
          <h1 class="title">
            <button v-if="navigable" class="t-btn" aria-label="Перейти к дате" @click="state.datePicker = true">
              <span class="t-main">{{ title.main }}<span class="t-chev" aria-hidden="true">▾</span></span>
              <span v-if="title.sub" class="t-sub">{{ title.sub }}</span>
            </button>
            <template v-else>
              <span class="t-main">{{ title.main }}</span>
              <span v-if="title.sub" class="t-sub">{{ title.sub }}</span>
            </template>
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

        <!-- Нет связи: спокойная полоса, данные остаются на экране -->
        <div v-if="net.offline && !state.kiosk" class="netbar" role="status">
          <span class="nb-ico" aria-hidden="true">⚠︎</span>
          <span class="nb-txt">
            <strong>{{ net.server ? 'Сервер дома не отвечает' : 'Нет связи с домом' }}</strong>
            <small>Показываю сохранённое{{ savedText ? ', обновлено ' + savedText : '' }}. Изменения сейчас не сохранятся.</small>
          </span>
          <button class="btn sm filled" :disabled="retrying" @click="retry">{{ retrying ? '…' : 'Повторить' }}</button>
        </div>

        <div v-if="problems.list.length" class="problem" role="alert">
          <span class="pb-txt">
            <strong>Не получилось: {{ friendly(problems.list[problems.list.length - 1]) }}</strong>
            <small>Можно повторить действие или обновить экран. Если повторяется — подробности в «Состоянии и копиях».</small>
          </span>
          <span class="pb-btns">
            <button class="btn sm" @click="reloadPage">Обновить</button>
            <button class="btn sm gray" @click="showDetails = !showDetails">{{ showDetails ? 'Скрыть детали' : 'Детали' }}</button>
            <button class="btn sm" aria-label="Закрыть" @click="problems.list.splice(0); showDetails = false">×</button>
          </span>
          <code v-if="showDetails" class="pb-det">{{ problems.list.join('\n') }}</code>
        </div>

        <!-- Потянуть вниз — обновить -->
        <div class="ptr" :class="{ ready: pull.ready, busy: pull.busy }" :style="{ height: pull.h + 'px' }" aria-hidden="true">
          <span class="ptr-ico">{{ pull.busy ? '' : '↓' }}</span>
          <span>{{ pull.busy ? 'Обновляю…' : pull.ready ? 'Отпустите, чтобы обновить' : 'Потяните, чтобы обновить' }}</span>
        </div>

        <main class="main">
          <KitchenView v-if="state.view === 'kitchen'" />
          <TodayView v-else-if="state.view === 'today'" />
          <TimelineView v-else-if="state.view === 'timeline'" />
          <MonthPhone v-else-if="state.view === 'month' && screen.narrow" />
          <CalendarView v-else-if="state.view === 'week' || state.view === 'month'" :mode="state.view" />
          <FamilyWeek v-else-if="state.view === 'family'" />
          <AgendaView v-else-if="state.view === 'agenda'" />
          <FreeView v-else-if="state.view === 'free'" />
          <ListsView v-else-if="state.view === 'lists'" />
          <SearchView v-else-if="state.view === 'search'" />
          <SettingsView v-else-if="state.view === 'settings'" />
        </main>
      </div>

      <!-- Нижние вкладки (телефон) -->
      <nav v-if="!state.kiosk" class="tabbar" aria-label="Разделы">
        <button :class="{ on: state.view === 'today' }" @click="setView('today')"><IconToday :day="new Date().getDate()" /><span>Сегодня</span></button>
        <button :class="{ on: isCalTab }" @click="setView(state.calView)"><IconCal /><span>Календарь</span></button>
        <button :class="{ on: state.view === 'free' }" @click="setView('free')"><IconFree /><span>Свободно</span></button>
        <button :class="{ on: state.view === 'lists' }" @click="setView('lists')"><IconList /><span>Списки</span></button>
        <button :class="{ on: state.peopleSheet }" @click="state.peopleSheet = true"><IconPeople /><span>Люди</span></button>
        <button :class="{ on: state.view === 'settings' }" @click="setView('settings')"><IconGear /><span>Настройки</span></button>
      </nav>

      <Sheet :open="state.peopleSheet" title="Чьи события показывать" @close="state.peopleSheet = false">
        <PeopleList />
      </Sheet>
      <PersonSheet />
      <Sheet :open="state.datePicker" title="Перейти к дате" @close="state.datePicker = false">
        <MiniMonth class="dp-month" @picked="state.datePicker = false" />
        <div class="dp-btns">
          <button class="btn filled" @click="goToday(); state.datePicker = false">Сегодня</button>
          <button class="btn" @click="jump(1)">Завтра</button>
          <button class="btn" @click="jump(7)">Через неделю</button>
        </div>
      </Sheet>
      <EventDialog />
      <EventEditor />
      <SectionWizard />
      <MoveScope />
      <MoveWarn />
      <QuickAdd />
      <Onboarding />
      <Toast />
    </template>
  </div>
</template>

<script setup>
import { computed, h, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { state, loadConfig, setView, refreshStatus, syncNow, reload, connectLive, CAL_VIEWS, weekDays, screen, animate, toast } from './lib/store'
import { net } from './lib/api'
import { haptic } from './lib/haptic'
import { addDays, startOfWeek, relativeDayName, cap } from './lib/dates'
import EventDialog from './components/EventDialog.vue'
import EventEditor from './components/EventEditor.vue'
import SectionWizard from './components/SectionWizard.vue'
import MoveScope from './components/MoveScope.vue'
import MoveWarn from './components/MoveWarn.vue'
import QuickAdd from './components/QuickAdd.vue'
import Onboarding from './components/Onboarding.vue'
import Toast from './components/Toast.vue'
import LoginScreen from './components/LoginScreen.vue'
import MiniMonth from './components/MiniMonth.vue'
import PeopleList from './components/PeopleList.vue'
import Sheet from './components/Sheet.vue'
import PersonSheet from './components/PersonSheet.vue'
import { problems } from './lib/report'
import TodayView from './views/TodayView.vue'
import TimelineView from './views/TimelineView.vue'
import CalendarView from './views/CalendarView.vue'
import MonthPhone from './views/MonthPhone.vue'
import KitchenView from './views/KitchenView.vue'
import AgendaView from './views/AgendaView.vue'
import FamilyWeek from './views/FamilyWeek.vue'
import FreeView from './views/FreeView.vue'
import SettingsView from './views/SettingsView.vue'
import ListsView from './views/ListsView.vue'
import SearchView from './views/SearchView.vue'

const VIEWS = [
  { id: 'today', label: 'Сегодня' },
  { id: 'timeline', label: 'Лента' },
  { id: 'week', label: 'Неделя' },
  { id: 'family', label: 'Семья' },
  { id: 'month', label: 'Месяц' },
  { id: 'agenda', label: 'Список' },
]
const CAL_TABS = VIEWS.slice(1)
const isCalTab = computed(() => CAL_VIEWS.includes(state.view))
const navigable = computed(() => !['settings', 'free', 'lists', 'search'].includes(state.view))

// --- значки нижней панели (тонкие линии, как SF Symbols) ---
const svg = (paths, extra = {}) => () => h('svg', { viewBox: '0 0 24 24', class: 'ico', 'aria-hidden': 'true', ...extra }, paths)
const IconCal = svg([h('rect', { x: 3.5, y: 5, width: 17, height: 15.5, rx: 3 }), h('path', { d: 'M3.5 9.5h17M8 3v4M16 3v4' })])
const IconFree = svg([h('circle', { cx: 12, cy: 12, r: 8.5 }), h('path', { d: 'M12 7.5V12l3 2' })])
const IconPeople = svg([h('circle', { cx: 9, cy: 8.5, r: 3.2 }), h('path', { d: 'M3.5 19c.6-3.2 2.8-5 5.5-5s4.9 1.8 5.5 5' }), h('circle', { cx: 16.5, cy: 9.5, r: 2.6 }), h('path', { d: 'M15.5 14.2c2.6-.3 4.6 1.3 5 4.3' })])
const IconList = svg([h('path', { d: 'M9 6.5h11M9 12h11M9 17.5h11' }), h('path', { d: 'M3.8 6.6l1 1 1.9-2M3.8 12.1l1 1 1.9-2M3.8 17.6l1 1 1.9-2' })])
const IconSearch = svg([h('circle', { cx: 10.5, cy: 10.5, r: 6 }), h('path', { d: 'M15 15l5 5' })])
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
  animate(dir, () => shiftNow(dir))
}
function shiftNow(dir) {
  const c = new Date(state.cursor)
  if (state.view === 'month') { const d = c.getDate(); c.setDate(1); c.setMonth(c.getMonth() + dir); c.setDate(Math.min(d, new Date(c.getFullYear(), c.getMonth() + 1, 0).getDate())) }
  else if (state.view === 'today') c.setDate(c.getDate() + dir)
  else if (state.view === 'family') c.setDate(c.getDate() + 7 * dir)
  else if (state.view === 'timeline') c.setDate(c.getDate() + state.timelineDays * dir)
  else c.setDate(c.getDate() + weekDays() * dir)
  state.cursor = c
}
function goToday() {
  const now = new Date()
  animate(now > state.cursor ? 1 : -1, () => { state.cursor = now })
}
function jump(days) {
  const d = new Date(); d.setDate(d.getDate() + days)
  animate(1, () => { state.cursor = d })
  state.datePicker = false
}

// --- связь и ошибки ---
const retrying = ref(false)
const showDetails = ref(false)
const savedText = computed(() => net.lastOk ? new Date(net.lastOk).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : '')
async function retry() {
  retrying.value = true
  try { await reload() } catch { /* полоса останется */ } finally { retrying.value = false }
  if (!net.offline) toast('Связь восстановлена')
}
// Техническую строку — в понятную фразу; подробности по кнопке «Детали».
function friendly(msg) {
  const m = String(msg || '')
  if (/загрузить события/i.test(m)) return 'загрузить события'
  if (/перенести/i.test(m)) return 'перенести событие'
  if (/сохранить/i.test(m)) return 'сохранить изменения'
  if (/\(.*(render|setup|hook|watcher)/i.test(m) || /undefined|null|is not a function/i.test(m)) return 'показать часть экрана'
  return m.length > 80 ? m.slice(0, 80) + '…' : m
}
function reloadPage() { problems.list.splice(0); location.reload() }

// --- потянуть вниз, чтобы обновить (телефон) ---
const pull = reactive({ h: 0, ready: false, busy: false })
const PULL_AT = 70
let py0 = null, pulling = false
function scrolledParent(el) {
  for (let n = el; n && n !== document.body; n = n.parentElement) {
    if (n.scrollTop > 0) return true
    if (n.classList?.contains('no-pull') || n.closest?.('.sheet, .fc-scroller, .dg-scroll')) return true
  }
  return false
}
function onTouchStart(e) {
  if (state.kiosk || pull.busy || e.touches.length !== 1 || window.scrollY > 0 || document.querySelector('.backdrop')) { py0 = null; return }
  if (scrolledParent(e.target)) { py0 = null; return }
  py0 = e.touches[0].clientY
  pulling = false
}
function onTouchMove(e) {
  if (py0 == null) return
  const dy = e.touches[0].clientY - py0
  if (dy <= 0 || window.scrollY > 0) { if (pulling) { pull.h = 0; pull.ready = false } py0 = dy < -10 ? null : py0; return }
  pulling = true
  pull.h = Math.min(110, dy * 0.5)
  const ready = pull.h >= PULL_AT * 0.8
  if (ready && !pull.ready) haptic('tap')
  pull.ready = ready
}
async function onTouchEnd() {
  if (py0 == null) return
  py0 = null
  if (!pulling) return
  pulling = false
  if (!pull.ready) { pull.h = 0; return }
  pull.busy = true
  pull.h = 44
  try { await syncNow(); haptic('success') } catch { /* полоса связи покажет */ } finally {
    pull.busy = false; pull.ready = false; pull.h = 0
  }
}

const monthName = (d) => cap(d.toLocaleDateString('ru-RU', { month: 'long' }))
const title = computed(() => {
  const c = state.cursor
  switch (state.view) {
    case 'settings': return { main: 'Настройки' }
    case 'free': return { main: 'Свободное время' }
    case 'lists': return { main: 'Списки' }
    case 'search': return { main: 'Поиск' }
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
      const days = state.view === 'timeline' ? state.timelineDays : state.view === 'family' ? 7 : weekDays()
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
// Экран на стене: тёмная тема по расписанию (?kiosk&dark=21-7 — по умолчанию с 21 до 7; dark=0 — не включать,
// dark=always — всегда тёмная) и дополнительное приглушение глубокой ночью.
const darkParam = new URLSearchParams(location.search).get('dark') ?? '21-7'
function inDarkWindow(d) {
  if (darkParam === 'always') return true
  const m = /^(\d{1,2})(?::(\d{2}))?-(\d{1,2})(?::(\d{2}))?$/.exec(darkParam)
  if (!m) return false
  const now = d.getHours() * 60 + d.getMinutes()
  const from = +m[1] * 60 + +(m[2] || 0), to = +m[3] * 60 + +(m[4] || 0)
  return from <= to ? now >= from && now < to : now >= from || now < to
}
function tickNight() {
  const d = new Date(), hr = d.getHours()
  night.value = state.kiosk && (hr >= 23 || hr < 6)
  if (!state.kiosk) return
  const root = document.documentElement
  if (inDarkWindow(d)) root.dataset.theme = 'dark'
  else if (root.dataset.theme === 'dark') delete root.dataset.theme
}

onMounted(async () => {
  window.addEventListener('touchstart', onTouchStart, { passive: true })
  window.addEventListener('touchmove', onTouchMove, { passive: true })
  window.addEventListener('touchend', onTouchEnd)
  window.addEventListener('touchcancel', onTouchEnd)
  await loadConfig()
  await refreshStatus()
  connectLive()
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
onUnmounted(() => {
  timers.forEach(clearInterval); ro?.disconnect()
  window.removeEventListener('touchstart', onTouchStart)
  window.removeEventListener('touchmove', onTouchMove)
  window.removeEventListener('touchend', onTouchEnd)
  window.removeEventListener('touchcancel', onTouchEnd)
})
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
.search-btn :deep(.ico) { width: 20px; height: 20px; color: var(--tint); }
.title { grid-area: title; margin: 0; font-family: var(--font-display); font-size: 28px; line-height: 1.1; letter-spacing: -0.02em; white-space: nowrap; }
.t-main { font-weight: 700; }
.t-btn { all: unset; cursor: pointer; display: inline; border-radius: 8px; }
.t-btn:focus-visible { outline: 2px solid var(--tint); outline-offset: 2px; }
.t-chev { font-size: .5em; color: var(--tint); margin-left: 6px; vertical-align: .35em; }
.netbar {
  display: flex; align-items: center; gap: 12px; margin: 10px 20px 0; padding: 10px 12px 10px 14px; border-radius: 12px;
  background: color-mix(in srgb, #ff9500 14%, var(--surface)); border: .5px solid color-mix(in srgb, #ff9500 40%, var(--line));
}
.nb-ico { color: #ff9500; font-size: 18px; }
.nb-txt { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.nb-txt strong { font-size: 15px; }
.nb-txt small, .pb-txt small { color: var(--ink-2); font-size: 13px; }
.pb-txt { flex: 1; min-width: 200px; display: flex; flex-direction: column; gap: 2px; }
.pb-btns { display: flex; gap: 6px; align-items: center; }
.pb-det { flex-basis: 100%; white-space: pre-wrap; font-size: 12px; color: var(--ink-2); background: var(--surface); padding: 8px; border-radius: 8px; overflow-wrap: anywhere; }
.ptr {
  display: flex; align-items: flex-end; justify-content: center; gap: 8px; overflow: hidden; color: var(--ink-2); font-size: 13px;
  transition: height .2s; padding-bottom: 8px; box-sizing: border-box;
}
.ptr[style*="height: 0px"] { padding: 0; }
.ptr-ico { display: inline-block; transition: transform .2s; font-size: 16px; }
.ptr.ready .ptr-ico { transform: rotate(180deg); color: var(--tint); }
.ptr.busy .ptr-ico { width: 14px; height: 14px; border: 2px solid var(--line); border-top-color: var(--tint); border-radius: 50%; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.dp-month { margin: 0 -4px; }
.dp-btns { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
.t-sub { font-weight: 400; margin-left: 8px; color: var(--ink-2); }
.cal-seg { display: none; }

.setup {
  display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;
  margin: 12px 20px 0; padding: 12px 16px; border-radius: var(--radius-m);
  background: var(--surface-2); font-weight: 600;
}
.main { flex: 1; display: flex; flex-direction: column; min-height: 0; }
.problem {
  margin: 10px 20px 0; padding: 10px 14px; border-radius: var(--radius-m);
  background: var(--surface-2); background: color-mix(in srgb, var(--red) 12%, var(--surface));
  color: var(--ink); display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; font-size: 13px;
}
.problem strong { color: var(--red); font-size: 14px; }
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
  .nav-row { gap: 4px; }
  .navs { margin-right: auto; }
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
