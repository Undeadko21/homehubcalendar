<template>
  <div class="today">
    <section class="hero">
      <div class="clock" aria-live="off">
        <span class="hm">{{ hm }}</span>
        <div class="date">
          <strong>{{ weekday }}</strong>
          <span>{{ dayMonth }}</span>
          <span v-if="holiday" class="holiday">{{ holiday.name }}</span>
        </div>
      </div>
      <WeatherNow />
    </section>

    <section class="board" :style="{ '--cols': columns.length || 1 }">
      <div v-for="col in columns" :key="col.person.id" class="col" :style="{ '--c': col.person.color }">
        <h2>
          <span class="avatar">{{ col.person.emoji || col.person.name[0] }}</span>
          {{ col.person.name }}
          <span v-if="col.nowEvent" class="status">сейчас: {{ col.nowEvent.title }}</span>
        </h2>
        <div class="list">
          <EventPill v-for="e in col.events" :key="e.id" :e="e" :now="now" :owner-id="col.person.id" />
          <p v-if="!col.events.length" class="empty">Свободный день</p>
        </div>
      </div>
      <p v-if="!columns.length" class="empty">Выберите хотя бы одного человека в фильтре выше.</p>
    </section>

    <section v-if="tomorrow.length" class="next">
      <h2>{{ nextLabel }}</h2>
      <div class="next-list">
        <EventPill v-for="e in tomorrow" :key="e.id" :e="e" />
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { state, visiblePeople } from '../lib/store'
import { useRange } from '../lib/useRange'
import { addDays, startOfDay, overlaps, isoDate, eventRange, sameDay, relativeDayName } from '../lib/dates'
import EventPill from '../components/EventPill.vue'
import WeatherNow from '../components/WeatherNow.vue'

const now = ref(new Date())
let t
onMounted(() => { t = setInterval(() => (now.value = new Date()), 15000) })
onUnmounted(() => clearInterval(t))

const day = computed(() => startOfDay(state.cursor))
const isToday = computed(() => sameDay(day.value, now.value))
const { events, holidayMap } = useRange(() => ({ start: day.value, end: addDays(day.value, 2) }))

const hm = computed(() =>
  isToday.value
    ? now.value.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
    : day.value.toLocaleDateString('ru-RU', { day: 'numeric' }),
)
const weekday = computed(() => {
  const s = day.value.toLocaleDateString('ru-RU', { weekday: 'long' })
  return s[0].toUpperCase() + s.slice(1)
})
const dayMonth = computed(() => day.value.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' }))
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

const nextDay = computed(() => addDays(day.value, 1))
const nextLabel = computed(() => relativeDayName(nextDay.value, now.value))
const tomorrow = computed(() =>
  events.value.filter((e) => overlaps(e, nextDay.value, addDays(nextDay.value, 1)) && !overlapsAllDayFromToday(e)),
)
// Многодневные события уже видны в сегодняшней доске — не повторяем.
function overlapsAllDayFromToday(e) {
  return e.all_day && overlaps(e, day.value, addDays(day.value, 1))
}
</script>

<style scoped>
.today { padding: 20px 24px 32px; display: flex; flex-direction: column; gap: 24px; }
.hero { display: flex; align-items: center; justify-content: space-between; gap: 24px; flex-wrap: wrap; }
.clock { display: flex; align-items: center; gap: 22px; }
.hm { font-size: clamp(64px, 10vw, 128px); font-weight: 800; letter-spacing: -0.045em; line-height: .9; }
.date { display: flex; flex-direction: column; font-size: 19px; line-height: 1.3; }
.date strong { font-size: 26px; font-weight: 700; letter-spacing: -0.01em; }
.date span { color: var(--ink-2); }
.date .holiday { color: var(--holiday); font-weight: 600; }

.board {
  display: grid;
  grid-template-columns: repeat(var(--cols), minmax(200px, 1fr));
  gap: 14px;
  overflow-x: auto;
  padding-bottom: 4px;
}
.col {
  --c: #888;
  background: var(--surface);
  border-radius: var(--radius-l);
  border-top: 5px solid var(--c);
  padding: 12px 12px 14px;
  box-shadow: var(--shadow);
  min-width: 0;
}
.col h2 { font-size: 18px; margin: 0 0 10px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.avatar {
  width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center;
  background: color-mix(in srgb, var(--c) 18%, var(--surface)); font-size: 17px;
}
.status { font-size: 13px; font-weight: 600; color: var(--c); filter: saturate(1.2); width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.list { display: flex; flex-direction: column; gap: 6px; }
.list .empty { padding: 8px 2px; margin: 0; }

.next h2 { font-size: 18px; margin: 0 0 10px; }
.next-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; }

@media (max-width: 760px) {
  .today { padding: 14px 12px 24px; gap: 18px; }
  .board { grid-template-columns: 1fr; }
  .clock { gap: 14px; }
  .date strong { font-size: 20px; }
  .date { font-size: 15px; }
}
.kiosk .today { padding: 28px 32px; }
.kiosk .board { flex: 1; }
</style>
