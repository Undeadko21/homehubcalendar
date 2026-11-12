<template>
  <div class="today">
    <section class="hero">
      <div class="clock">
        <span class="hm">{{ hm }}</span>
        <span v-if="holiday && holiday.type !== 'vacation'" class="holiday">{{ holiday.name }}</span>
        <span v-if="holiday?.vacation" class="vacation">{{ holiday.vacation }}</span>
      </div>
      <WeatherNow />
    </section>

    <form class="quick" @submit.prevent="addQuick">
      <input v-model="quickText" placeholder="Быстро: «Йога завтра в 18:30», «купить молоко», «дело: …»" aria-label="Быстро добавить событие, дело или покупку"
             autocomplete="off" enterkeyhint="go" />
      <MicButton @text="(t) => { quickText = t; addQuick() }" @error="(m) => toast(m)" />
      <button class="btn filled" :disabled="!quickText.trim()">＋</button>
    </form>

    <BirthdayStrip />

    <!-- Поездки детей: сегодня и завтра -->
    <section v-if="trips.length" class="trips">
      <h2 class="sec">Отвезти и забрать</h2>
      <div class="group">
        <button v-for="t in trips" :key="t.e.id" class="row trip" :class="t.e.escort_issue" @click="openEvent(t.e)">
          <span class="when">
            <strong>{{ t.time }}</strong>
            <small>{{ t.day }}</small>
          </span>
          <span class="what">
            <span class="title">{{ titleWithIcon(t.e) }}</span>
            <EscortBadge :e="t.e" />
          </span>
          <span class="state" :title="t.stateText">{{ t.icon }}</span>
        </button>
      </div>
    </section>

    <!-- Пустой день: что ближайшее и когда -->
    <button v-if="freeDay" class="free-day" :disabled="!nextUp" @click="nextUp && goToDay(nextUp.date)">
      <strong>{{ isToday ? 'Сегодня' : 'В этот день' }} свободно</strong>
      <span v-if="nextUp">Ближайшее — {{ nextUp.when }}: {{ nextUp.title }} ›</span>
      <span v-else-if="nextLoaded">В ближайший месяц событий нет</span>
    </button>

    <Skeleton v-if="!loaded && !todays.length" blocks :rows="3" class="sk" />
    <section ref="daySec" class="day-section">
      <DayGrid v-if="columns.length" :columns="columns" :day="day" :now="now" />
      <p v-else class="empty">Выберите хотя бы одного человека в списке «Люди».</p>
    </section>

    <section v-if="tomorrow.length" class="next">
      <h2 class="sec">{{ nextLabel }}</h2>
      <div class="next-list">
        <EventPill v-for="e in tomorrow" :key="e.id" :e="e" hide-escort />
      </div>
    </section>
  </div>
</template>

<script setup>
import Skeleton from '../components/Skeleton.vue'
import { titleWithIcon } from '../lib/icons'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { state, visiblePeople, openEvent, quickAdd, toast, goToDay, isEventVisible } from '../lib/store'
import { api } from '../lib/api'

const quickText = ref('')
async function addQuick() {
  const t = quickText.value.trim()
  if (!t) return
  try {
    await quickAdd(t, state.cursor)
    quickText.value = ''
  } catch (err) { toast(err.message) }
}
import { useRange } from '../lib/useRange'
import { addDays, startOfDay, overlaps, isoDate, isoLocal, eventRange, sameDay, relativeDayName, formatTime } from '../lib/dates'
import EventPill from '../components/EventPill.vue'
import EscortBadge from '../components/EscortBadge.vue'
import WeatherNow from '../components/WeatherNow.vue'
import DayGrid from '../components/DayGrid.vue'
import BirthdayStrip from '../components/BirthdayStrip.vue'
import MicButton from '../components/MicButton.vue'

const now = ref(new Date())
const daySec = ref(null)
let t
onMounted(() => { t = setInterval(() => (now.value = new Date()), 15000) })
onUnmounted(() => clearInterval(t))

const day = computed(() => startOfDay(state.cursor))
const isToday = computed(() => sameDay(day.value, now.value))
const { events, holidayMap, loaded } = useRange(() => ({ start: day.value, end: addDays(day.value, 2) }))

// На телефоне при открытии «Сегодня» сразу показываем сетку дня, а не часы и погоду над ней.
let scrolled = false
function toGrid() {
  if (scrolled || !daySec.value || !isToday.value || state.kiosk || window.innerWidth >= 900) return
  scrolled = true
  daySec.value.scrollIntoView({ block: 'start' })
}
onMounted(() => setTimeout(() => nextTick(toGrid), 1200))
watch(() => events.value.length, (n) => { if (n) setTimeout(() => nextTick(toGrid), 150) }, { once: true })

const hm = computed(() =>
  isToday.value ? now.value.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : String(day.value.getDate()),
)
const holiday = computed(() => holidayMap.value[isoDate(day.value)])

const todays = computed(() => events.value.filter((e) => overlaps(e, day.value, addDays(day.value, 1))))

const columns = computed(() =>
  visiblePeople.value
    .map((person) => {
      const evs = todays.value.filter((e) => e.people.includes(person.id))
      const nowEvent = isToday.value
        ? evs.find((e) => !e.all_day && eventRange(e).start <= now.value && eventRange(e).end > now.value)
        : null
      return { person, events: evs, nowEvent }
    })
    .filter((c) => c.events.length || !c.person.id.startsWith('_')),
)

// День без событий у выбранных людей: показываем, что ближайшее (ищем на месяц вперёд).
const freeDay = computed(() => loaded.value && visiblePeople.value.length > 0 && !todays.value.some(isEventVisible))
const upcoming = ref([])
const nextLoaded = ref(false)
watch([freeDay, day, () => state.revision], async ([free]) => {
  nextLoaded.value = false
  upcoming.value = []
  if (!free) return
  const from = addDays(day.value, 1)
  try {
    upcoming.value = await api.events(isoLocal(from), isoLocal(addDays(from, 31)))
  } catch { /* подсказка необязательна */ }
  nextLoaded.value = true
}, { immediate: true })
const nextUp = computed(() => {
  const e = upcoming.value.find((x) => !x.duty && isEventVisible(x))
  if (!e) return null
  const r = eventRange(e)
  const rel = relativeDayName(r.start, now.value)
  const dayText = ['Сегодня', 'Завтра'].includes(rel) ? rel.toLowerCase()
    : r.start.toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric', month: 'long' })
  return { date: r.start, title: e.title, when: e.all_day ? dayText : `${dayText} в ${formatTime(r.start)}` }
})

const nextDay = computed(() => addDays(day.value, 1))
const nextLabel = computed(() => relativeDayName(nextDay.value, now.value))
const tomorrow = computed(() =>
  events.value.filter((e) => overlaps(e, nextDay.value, addDays(nextDay.value, 1)) &&
    !(e.all_day && overlaps(e, day.value, addDays(day.value, 1)))),
)

// Поездки: события детей сегодня (ещё не закончившиеся) и завтра.
const trips = computed(() =>
  events.value
    .filter((e) => e.escort && !e.all_day && eventRange(e).end > now.value)
    .filter((e) => e.escort.mode === 'escort' && ['dropoff', 'pickup'].some((r) => !e.escort[r].skip))
    .map((e) => {
      const r = eventRange(e)
      const issue = e.escort_issue
      return {
        e,
        time: `${formatTime(r.start)}–${formatTime(r.end)}`,
        day: relativeDayName(r.start, now.value),
        icon: issue === 'conflict' ? '!' : issue === 'unassigned' ? '?' : '✓',
        stateText: issue === 'conflict' ? 'Конфликт' : issue === 'unassigned' ? 'Никто не назначен' : 'Всё в порядке',
      }
    }),
)
</script>

<style scoped>
.today { padding: 20px 24px 32px; display: flex; flex-direction: column; gap: 26px; max-width: 1400px; }
.quick { display: flex; gap: 8px; margin: 6px 0 14px; max-width: 640px; }
.quick input { flex: 1; min-width: 0; font: inherit; padding: 10px 14px; border-radius: 12px; border: .5px solid var(--line); background: var(--surface); color: var(--ink); }
.quick .btn { min-width: 44px; font-size: 20px; }
.hero { display: flex; align-items: center; justify-content: space-between; gap: 24px; flex-wrap: wrap; }
.clock { display: flex; align-items: baseline; gap: 18px; flex-wrap: wrap; }
.hm { font-family: var(--font-display); font-size: clamp(64px, 9vw, 112px); font-weight: 200; letter-spacing: -0.04em; line-height: .9; }
.holiday { color: var(--red); font-weight: 600; font-size: 17px; }
.vacation { color: #34c759; font-weight: 600; font-size: 17px; }
.free-day {
  display: flex; flex-direction: column; gap: 2px; text-align: left; border: 0; font: inherit; color: var(--ink);
  background: var(--surface-2); border-radius: var(--radius-m); padding: 12px 16px; max-width: 760px;
}
.free-day strong { font-size: 17px; }
.free-day span { color: var(--ink-2); font-size: 14px; }
.free-day:not(:disabled):hover { background: var(--fill); }
.sec { font-size: 20px; font-weight: 700; margin: 0 0 10px; letter-spacing: -0.01em; }

.trips .group { background: var(--surface-2); max-width: 760px; }
.trip { width: 100%; border: 0; background: none; text-align: left; color: inherit; }
.trip:hover { background: var(--fill); }
.trip .when { display: flex; flex-direction: column; width: 92px; flex: none; }
.trip .when strong { font-size: 14px; font-weight: 600; }
.trip .when small { font-size: 12px; color: var(--ink-2); }
.trip .what { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.trip .title { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.trip .state {
  width: 22px; height: 22px; border-radius: 50%; flex: none; display: grid; place-items: center;
  font-size: 13px; font-weight: 800; color: #fff; background: var(--ok);
}
.trip.conflict .state { background: var(--red); }
.trip.unassigned .state { background: var(--warn); }

.board {
  display: grid; grid-template-columns: repeat(var(--cols), minmax(210px, 1fr)); gap: 12px;
  overflow-x: auto; padding-bottom: 4px;
}
.col { --c: #888; background: var(--surface-2); border-radius: var(--radius-l); padding: 12px 10px 12px; min-width: 0; }
.col h2 { font-size: 17px; font-weight: 700; margin: 0 2px 10px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.avatar {
  width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center; flex: none;
  background: var(--c); color: #fff; font-size: 16px; font-weight: 600;
}
.pn { flex: 1; min-width: 0; }
.status { font-size: 12px; font-weight: 600; color: var(--c); width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.list { display: flex; flex-direction: column; gap: 5px; }
.list .empty { padding: 6px 4px; margin: 0; }
.next-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 6px; }

@media (max-width: 899px) {
  .today { padding: 14px 12px 24px; gap: 22px; }
  .board { grid-template-columns: 1fr; }
  .hm { font-size: 52px; }
  .today { gap: 16px; }
  .day-section { scroll-margin-top: 118px; }
}
.kiosk .today { padding: 28px 32px; max-width: none; }
</style>
