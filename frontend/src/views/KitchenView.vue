<template>
  <div class="kitchen">
    <header class="top">
      <div class="clock">
        <span class="hm">{{ hm }}</span>
        <span class="date">{{ dateText }}</span>
        <span v-if="holiday && holiday.type !== 'vacation'" class="holiday">{{ holiday.name }}</span>
        <span v-if="holiday?.vacation" class="holiday">{{ holiday.vacation }}</span>
      </div>
      <WeatherNow />
    </header>

    <div class="cols">
      <section class="col">
        <h2>Дальше</h2>
        <p v-if="!upcoming.length" class="empty">Сегодня и завтра событий нет</p>
        <div v-for="e in upcoming" :key="e.id" class="ev" :class="{ now: isNow(e) }" :style="{ '--c': eventColor(e) }">
          <span class="when">{{ whenText(e) }}</span>
          <span class="what">
            <strong>{{ e.title }}</strong>
            <small>
              <span v-for="p in who(e)" :key="p.id" class="p"><i :style="{ background: p.color }"></i>{{ p.name }}</span>
              <span v-if="e.location" class="loc">{{ e.location }}</span>
            </small>
          </span>
        </div>
      </section>

      <section class="col">
        <template v-if="trips.length">
          <h2>Отвезти и забрать</h2>
          <div v-for="t in trips" :key="t.e.id" class="trip" :class="t.e.escort_issue">
            <span class="when">{{ t.time }}</span>
            <span class="what"><strong>{{ t.e.title }}</strong><EscortBadge :e="t.e" /></span>
            <span class="st">{{ t.icon }}</span>
          </div>
        </template>

        <template v-if="todo.length">
          <h2>Дела и покупки</h2>
          <div class="todo">
            <span v-for="i in todo" :key="i.id" class="chip" :class="{ late: i.late }">
              {{ i.text }}<small v-if="i.person"> · {{ i.person }}</small>
            </span>
          </div>
        </template>

        <BirthdayStrip />
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { state, visiblePeople, personById, eventColor } from '../lib/store'
import { useRange } from '../lib/useRange'
import { api } from '../lib/api'
import { addDays, startOfDay, isoDate, eventRange, formatTime, relativeDayName } from '../lib/dates'
import WeatherNow from '../components/WeatherNow.vue'
import BirthdayStrip from '../components/BirthdayStrip.vue'
import EscortBadge from '../components/EscortBadge.vue'

const now = ref(new Date())
let t
onMounted(() => { t = setInterval(() => (now.value = new Date()), 15000) })
onUnmounted(() => clearInterval(t))

const day = computed(() => startOfDay(now.value))
const { events, holidayMap } = useRange(() => ({ start: day.value, end: addDays(day.value, 3) }))

const hm = computed(() => now.value.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }))
const dateText = computed(() => {
  const s = now.value.toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' })
  return s.charAt(0).toUpperCase() + s.slice(1)
})
const holiday = computed(() => holidayMap.value[isoDate(day.value)])

const isNow = (e) => !e.all_day && eventRange(e).start <= now.value && eventRange(e).end > now.value
const upcoming = computed(() =>
  events.value
    .filter((e) => !e.duty && (e.all_day ? eventRange(e).end > now.value : eventRange(e).end > now.value))
    .filter((e) => eventRange(e).start < addDays(day.value, 2))
    .sort((a, b) => (a.all_day === b.all_day ? +eventRange(a).start - +eventRange(b).start : a.all_day ? -1 : 1))
    .slice(0, 8),
)
function whenText(e) {
  if (e.all_day) return 'весь день'
  const r = eventRange(e)
  const rel = relativeDayName(r.start, now.value)
  return (rel === 'Сегодня' ? '' : rel.toLowerCase() + ' ') + formatTime(r.start)
}
const who = (e) => e.people.map((id) => personById.value[id]).filter((p) => p && !p.id.startsWith('_') && visiblePeople.value.some((v) => v.id === p.id))

const trips = computed(() =>
  events.value
    .filter((e) => e.escort && !e.all_day && eventRange(e).end > now.value && eventRange(e).start < addDays(day.value, 2))
    .filter((e) => e.escort.mode === 'escort' && ['dropoff', 'pickup'].some((r) => !e.escort[r].skip))
    .slice(0, 4)
    .map((e) => {
      const r = eventRange(e)
      const rel = relativeDayName(r.start, now.value)
      return { e, time: (rel === 'Сегодня' ? '' : rel.toLowerCase() + ' ') + formatTime(r.start),
        icon: e.escort_issue === 'conflict' ? '!' : e.escort_issue === 'unassigned' ? '?' : '✓' }
    }),
)

// Покупки и дела: открытые записи, дела со сроком — первыми.
const lists = ref([])
const load = () => api.lists().then((r) => (lists.value = r)).catch(() => {})
watch(() => state.revision, load, { immediate: true })
const todo = computed(() => {
  const today = isoDate(day.value)
  const items = lists.value.flatMap((l) => l.items.filter((i) => !i.done).map((i) => ({ ...i, list: l.name })))
  return items
    .map((i) => ({ id: i.id, text: i.text, late: !!i.due && i.due <= today, due: i.due || '9999',
      person: i.person_id ? personById.value[i.person_id]?.name : '' }))
    .sort((a, b) => (a.due < b.due ? -1 : a.due > b.due ? 1 : 0))
    .slice(0, 12)
})
</script>

<style scoped>
.kitchen { padding: 18px 28px 28px; display: flex; flex-direction: column; gap: 22px; font-size: 20px; }
.top { display: flex; justify-content: space-between; align-items: center; gap: 24px; flex-wrap: wrap; }
.clock { display: flex; flex-direction: column; }
.hm { font-size: clamp(72px, 12vw, 150px); font-weight: 200; line-height: 1; letter-spacing: -0.03em; font-variant-numeric: tabular-nums; }
.date { font-size: 26px; color: var(--ink-2); margin-top: 4px; }
.holiday { color: var(--red); font-size: 20px; }
.cols { display: grid; grid-template-columns: 1.3fr 1fr; gap: 28px; align-items: start; }
@media (max-width: 900px) { .cols { grid-template-columns: 1fr; } }
h2 { font-size: 24px; margin: 0 0 12px; letter-spacing: -0.01em; }
.col { display: flex; flex-direction: column; gap: 6px; }
.empty { color: var(--ink-3); font-size: 22px; }
.ev, .trip { display: flex; gap: 18px; align-items: center; padding: 12px 16px; margin-bottom: 8px; border-radius: 14px;
  background: var(--surface-2); border-left: 6px solid var(--c, var(--ink-3)); }
.ev.now { box-shadow: inset 0 0 0 2px var(--c); }
.when { min-width: 96px; font-size: 26px; font-weight: 600; font-variant-numeric: tabular-nums; }
.what { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.what strong { font-size: 26px; font-weight: 600; overflow-wrap: anywhere; }
.what small { font-size: 17px; color: var(--ink-2); display: flex; gap: 14px; flex-wrap: wrap; }
.p { display: inline-flex; align-items: center; gap: 6px; }
.p i { width: 10px; height: 10px; border-radius: 50%; display: block; }
.trip { --c: var(--ink-3); }
.trip.conflict { border-left-color: var(--red); }
.trip.unassigned { border-left-color: var(--warn, #ff9500); }
.st { font-size: 26px; font-weight: 700; }
.todo { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.chip { background: var(--fill); border-radius: 999px; padding: 6px 14px; font-size: 18px; }
.chip.late { background: color-mix(in srgb, var(--red) 18%, var(--surface)); color: var(--red); }
.chip small { color: var(--ink-2); }
</style>
