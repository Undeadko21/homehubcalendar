<template>
  <div class="kitchen" :class="{ night }">
    <header class="top">
      <div class="clock">
        <span class="hm">{{ hm }}</span>
        <span class="date">{{ dateText }}</span>
        <span v-if="holiday && holiday.type !== 'vacation'" class="holiday">{{ holiday.name }}</span>
        <span v-if="holiday?.vacation" class="holiday">{{ holiday.vacation }}</span>
      </div>
      <WeatherNow />
    </header>

    <!-- Ночью (23–6): только часы и ближайшее событие, тускло -->
    <section v-if="night" class="night-next">
      <template v-if="nextOne">
        <span class="nn-when">{{ whenText(nextOne) }}</span>
        <span class="nn-what">{{ titleWithIcon(nextOne) }}</span>
      </template>
    </section>

    <!-- Кто где: аватар, что сейчас или что дальше -->
    <section v-if="!night && people.length" class="who-now" aria-label="Кто где">
      <div v-for="p in people" :key="p.id" class="pw" :style="{ '--c': p.color }">
        <span class="ava">{{ p.emoji || p.name[0] }}</span>
        <span class="pw-txt">
          <strong>{{ p.name }}</strong>
          <small :class="{ busy: p.busy }">{{ p.status }}</small>
        </span>
      </div>
    </section>

    <div v-if="!night" class="cols">
      <section class="col">
        <h2>Дальше</h2>
        <p v-if="!upcoming.length" class="empty">Сегодня и завтра событий нет</p>
        <div v-for="e in upcoming" :key="e.id" class="ev" :class="{ now: isNow(e) }" :style="{ '--c': eventColor(e) }">
          <span class="when">{{ whenText(e) }}</span>
          <span class="what">
            <span v-if="isNow(e)" class="live"><i></i>идёт сейчас · до {{ formatTime(eventRange(e).end) }}</span>
            <strong>{{ titleWithIcon(e) }}</strong>
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
            <span class="what"><strong>{{ titleWithIcon(t.e) }}</strong><EscortBadge :e="t.e" /></span>
            <span class="st" :title="t.state"><Ico :name="t.e.escort_issue ? 'car' : 'check'" /><span class="sr-only">{{ t.state }}</span></span>
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
import { titleWithIcon } from '../lib/icons'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { state, visiblePeople, personById, eventColor } from '../lib/store'
import { useRange } from '../lib/useRange'
import { api } from '../lib/api'
import { addDays, startOfDay, isoDate, eventRange, formatTime, relativeDayName } from '../lib/dates'
import WeatherNow from '../components/WeatherNow.vue'
import BirthdayStrip from '../components/BirthdayStrip.vue'
import EscortBadge from '../components/EscortBadge.vue'
import Ico from '../components/Ico.vue'

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

// Ночной режим кухонного экрана — те же часы, что и затемнение в App.vue
const night = computed(() => { const h = now.value.getHours(); return state.kiosk && (h >= 23 || h < 6) })   // только на экране на стене
const nextOne = computed(() => events.value.filter((e) => !e.duty && !e.all_day && eventRange(e).start > now.value)
  .sort((a, b) => +eventRange(a).start - +eventRange(b).start)[0] || null)

// Кто где: «сейчас: Школа до 13:30» / «дальше в 15:00: Английский» / «свободен сегодня»
const people = computed(() => visiblePeople.value.filter((p) => !p.id.startsWith('_')).map((p) => {
  // поездка взрослого (duty) — тоже занятость; её название уже вида «Забрать Машу: Школа»
  const label = (e) => e.title
  const mine = events.value.filter((e) => !e.all_day && e.people.includes(p.id) && eventRange(e).end > now.value)
    .sort((a, b) => +eventRange(a).start - +eventRange(b).start)
  const cur = mine.find((e) => eventRange(e).start <= now.value)
  if (cur) return { ...p, busy: true, status: `${label(cur)} до ${formatTime(eventRange(cur).end)}` }
  const nx = mine.find((e) => eventRange(e).start < addDays(day.value, 1))
  if (nx) return { ...p, busy: false, status: `далее в ${formatTime(eventRange(nx).start)}: ${label(nx)}` }
  // нет событий со временем — «весь день» сегодня (отпуск, командировка, болеет)
  const allDay = events.value.find((e) => e.all_day && e.people.includes(p.id) && eventRange(e).start <= now.value && eventRange(e).end > now.value)
  return { ...p, busy: !!allDay, status: allDay ? allDay.title : 'сегодня свободно' }
}))

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
        state: e.escort_issue === 'conflict' ? 'Назначенный занят' : e.escort_issue === 'unassigned' ? 'Никто не назначен' : 'Всё назначено' }
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
.what strong { font-size: 26px; font-weight: 600; overflow-wrap: break-word; hyphens: auto; }
.what small { font-size: 17px; color: var(--ink-2); display: flex; gap: 14px; flex-wrap: wrap; }
.p { display: inline-flex; align-items: center; gap: 6px; }
.p i { width: 10px; height: 10px; border-radius: 50%; display: block; }
.trip { --c: var(--ink-3); }
.trip.conflict { border-left-color: var(--red); }
.trip.unassigned { border-left-color: var(--warn, #ff9500); }
.todo { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.chip { background: var(--fill); border-radius: 999px; padding: 6px 14px; font-size: 18px; }
.chip.late { background: color-mix(in srgb, var(--red) 18%, var(--surface)); color: var(--red); }
.chip small { color: var(--ink-2); }

/* со стены читается: поездки, дни рождения — крупнее */
.trip :deep(.escort) { font-size: 16px; gap: 12px; }
.trip .when { min-width: 7.2em; }
.kitchen :deep(.bday .main small), .kitchen :deep(.main small) { font-size: 15px; }
.kitchen :deep(.cnt) { font-size: 16px; }

/* кто где */
.who-now { display: flex; gap: 12px; flex-wrap: wrap; margin-top: -6px; }
.pw { display: flex; align-items: center; gap: 12px; padding: 10px 18px 10px 10px; border-radius: 999px; background: var(--surface-2); min-width: 0; }
.pw .ava { width: 52px; height: 52px; border-radius: 50%; display: grid; place-items: center; flex: none; background: var(--c); color: #fff; font-size: 28px; font-weight: 600; }
.pw-txt { display: flex; flex-direction: column; min-width: 0; line-height: 1.2; }
.pw-txt strong { font-size: 20px; }
.pw-txt small { font-size: 16px; color: var(--ink-2); max-width: 22ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pw-txt small.busy { color: color-mix(in srgb, var(--c) 70%, var(--ink)); font-weight: 600; }

/* «идёт сейчас» — пульсирующая точка */
.live { display: inline-flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; color: color-mix(in srgb, var(--c) var(--ev-mix), var(--ink)); }
.live i { width: 9px; height: 9px; border-radius: 50%; background: var(--c); animation: pulse 1.8s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--c) 55%, transparent); } 50% { box-shadow: 0 0 0 7px transparent; } }
.st { font-size: 28px; display: inline-flex; color: var(--ok); }
.trip.unassigned .st { color: var(--warn); }
.trip.conflict .st { color: var(--red); }

/* ночь: только часы и ближайшее */
.kitchen.night { justify-content: center; min-height: 80vh; opacity: .75; }
.kitchen.night .top { justify-content: center; text-align: center; }
.kitchen.night .clock { align-items: center; }
.kitchen.night .top :deep(.weather) { display: none; }
.night-next { display: flex; flex-direction: column; align-items: center; gap: 4px; color: var(--ink-2); }
.nn-when { font-size: 22px; }
.nn-what { font-size: 30px; color: var(--ink); font-weight: 600; }
/* узкий экран (телефон, крупный текст): время над названием, «кто где» по два в ряд */
@media (max-width: 600px) {
  .kitchen { padding: 12px 14px 24px; font-size: 17px; }
  .ev, .trip { flex-direction: column; align-items: flex-start; gap: 4px; }
  .when, .trip .when { min-width: 0; font-size: 18px; }
  .what strong { font-size: 21px; overflow-wrap: normal; hyphens: auto; }
  .who-now { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .pw { padding: 8px 10px 8px 8px; gap: 8px; border-radius: 16px; }
  .pw .ava { width: 36px; height: 36px; font-size: 20px; }
  .pw-txt strong { font-size: 16px; }
  .pw-txt small { font-size: 13px; max-width: none; white-space: normal; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
}

</style>
