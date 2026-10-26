<template>
  <div class="free">
    <div class="controls">
      <h3 class="group-title">Кто</h3>
      <div class="group pad">
        <PeoplePicker v-model="who" label="Кто должен быть свободен" />
      </div>

      <h3 class="group-title">Когда</h3>
      <div class="group">
        <div class="row">
          <div class="seg wide" role="tablist" aria-label="Период">
            <button v-for="p in PERIODS" :key="p.id" :class="{ on: period === p.id }" @click="period = p.id">{{ p.label }}</button>
          </div>
        </div>
        <div class="row">
          <div class="seg wide" role="tablist" aria-label="Время суток">
            <button v-for="p in PARTS" :key="p.id" :class="{ on: part === p.id }" @click="part = p.id">{{ p.label }}</button>
          </div>
        </div>
        <div class="row">
          <span class="lbl">Не меньше</span>
          <div class="seg" role="tablist" aria-label="Минимальная длительность">
            <button v-for="m in MINS" :key="m" :class="{ on: minMinutes === m }" @click="minMinutes = m">{{ durLabel(m) }}</button>
          </div>
        </div>
        <label class="row toggle-row">
          <span class="lbl">Учитывать события на весь день</span>
          <input v-model="allDay" type="checkbox" class="switch" />
        </label>
      </div>
      <p class="group-note">Работа, все календари выбранных людей и назначенные поездки за детьми считаются занятостью.</p>
    </div>

    <div class="results" aria-live="polite">
      <p v-if="!who.length" class="empty">Выберите хотя бы одного человека.</p>
      <p v-else-if="error" class="err">{{ error }}</p>
      <template v-else>
        <p class="summary">
          <template v-if="loading">Ищу…</template>
          <template v-else-if="total">
            Нашлось {{ total }} {{ plural(total, 'окно', 'окна', 'окон') }}, когда {{ whoText }} свободны {{ partText }}.
          </template>
          <template v-else>Общих свободных окон не нашлось. Попробуйте другой период или меньшую длительность.</template>
        </p>
        <section v-for="d in days" :key="d.date" class="day" :class="{ none: !d.windows.length }">
          <h3>
            <span class="dname" :class="{ off: d.off }">{{ d.label }}</span>
            <span v-if="d.holiday" class="hname">{{ d.holiday }}</span>
          </h3>
          <!-- Шкала: строка на каждого человека и общая строка «Вместе» -->
          <div class="lanes">
            <div v-for="lane in d.lanes" :key="lane.id" class="lane">
              <span class="ln" :title="lane.name">{{ lane.short }}</span>
              <div class="track">
                <span v-for="(b, i) in lane.blocks" :key="i" class="blk" :class="{ escort: b.kind === 'escort' }"
                      :style="{ ...b.style, '--c': lane.color }" :title="b.title">{{ b.label }}</span>
              </div>
            </div>
            <div class="lane together">
              <span class="ln">Вместе</span>
              <div class="track">
                <span v-for="(w, i) in d.windowBlocks" :key="i" class="win" :style="w.style"></span>
              </div>
            </div>
            <div class="ticks"><span v-for="h in d.ticks" :key="h.label" :style="{ left: h.x + '%' }">{{ h.label }}</span></div>
          </div>

          <!-- Хронология: события и свободные окна по порядку -->
          <ul class="agenda">
            <li v-for="(it, i) in d.items" :key="i" :class="it.type">
              <span class="tm">{{ it.time }}</span>
              <span class="what">
                <template v-if="it.type === 'free'">
                  <strong>Все свободны</strong> <span class="muted">{{ durLabel(it.minutes) }}</span>
                </template>
                <template v-else>
                  <span class="ttl">{{ it.title }}</span>
                  <span class="who">
                    <span v-for="pid in it.people" :key="pid" class="pp">
                      <i :style="{ background: personById[pid]?.color }"></i>{{ personById[pid]?.name || pid }}
                    </span>
                  </span>
                </template>
              </span>
            </li>
          </ul>
          <p v-if="!d.windows.length" class="faint none-text">Общего окна нет</p>
        </section>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '../lib/api'
import { state, people, personById } from '../lib/store'
import { addDays, startOfDay, startOfWeek, isoDate, formatTime, cap } from '../lib/dates'
import PeoplePicker from '../components/PeoplePicker.vue'

const PERIODS = [
  { id: 'week', label: 'Эта неделя' },
  { id: 'next', label: 'Следующая' },
  { id: 'weekend', label: 'Выходные' },
  { id: '14', label: '2 недели' },
]
const PARTS = [
  { id: 'all', label: 'Весь день', from: '08:00', to: '22:00' },
  { id: 'morning', label: 'Утро', from: '08:00', to: '12:00' },
  { id: 'day', label: 'День', from: '12:00', to: '17:00' },
  { id: 'evening', label: 'Вечер', from: '17:00', to: '22:00' },
]
const MINS = [30, 60, 120, 180]

const LS = 'homecal.free'
let saved = {}
try { saved = JSON.parse(localStorage.getItem(LS) || '{}') } catch {}
const defaultWho = () => people.value.filter((p) => !p.id.startsWith('_') && !p.needs_escort).map((p) => p.id)
const who = ref(saved.who?.length ? saved.who : defaultWho())
const period = ref(saved.period || 'week')
const part = ref(saved.part || 'evening')
const minMinutes = ref(saved.minMinutes || 60)
const allDay = ref(!!saved.allDay)

watch([who, period, part, minMinutes, allDay], () => {
  try {
    localStorage.setItem(LS, JSON.stringify({ who: who.value, period: period.value, part: part.value,
      minMinutes: minMinutes.value, allDay: allDay.value }))
  } catch {}
})

const range = computed(() => {
  const today = startOfDay(new Date())
  const wk = startOfWeek(today)
  switch (period.value) {
    case 'next': return { start: addDays(wk, 7), end: addDays(wk, 14) }
    case 'weekend': {
      const sat = addDays(wk, 5)
      const s = sat < today ? addDays(sat, 7) : sat
      return { start: s, end: addDays(s, 2) }
    }
    case '14': return { start: today, end: addDays(today, 14) }
    default: return { start: today, end: addDays(wk, 7) }
  }
})
const partDef = computed(() => PARTS.find((p) => p.id === part.value))

const raw = ref([])
const holidays = ref({})
const loading = ref(false)
const error = ref('')

async function load() {
  if (!who.value.length) { raw.value = []; return }
  loading.value = true
  error.value = ''
  const { start, end } = range.value
  try {
    const [res, hol] = await Promise.all([
      api.free({
        people: who.value.join(','), start: isoDate(start), end: isoDate(end),
        day_from: partDef.value.from, day_to: partDef.value.to, min_minutes: minMinutes.value, all_day: allDay.value,
      }),
      api.holidays(isoDate(start), isoDate(end)).catch(() => []),
    ])
    raw.value = res
    holidays.value = Object.fromEntries(hol.map((h) => [h.date, h]))
  } catch (e) {
    error.value = 'Не удалось посчитать: ' + e.message
  } finally {
    loading.value = false
  }
}
watch([who, range, part, minMinutes, allDay, () => state.revision], load, { immediate: true, deep: true })

const now = () => new Date()
const days = computed(() =>
  raw.value
    .map((d) => {
      const from = new Date(d.from), to = new Date(d.to)
      const span = to - from
      const pct = (a, b) => ({ left: ((Math.max(a, from) - from) / span) * 100 + '%', width: ((Math.min(b, to) - Math.max(a, from)) / span) * 100 + '%' })
      const date = new Date(d.date + 'T00:00')
      const h = holidays.value[d.date]
      const weekend = date.getDay() === 0 || date.getDay() === 6
      // Окна, которые уже прошли сегодня, не показываем.
      const windows = d.windows
        .map((w) => ({ s: new Date(w.start), e: new Date(w.end) }))
        .map((w) => ({ ...w, s: w.s < now() && w.e > now() ? roundUp(now()) : w.s }))
        .filter((w) => w.e > now() && (w.e - w.s) / 60000 >= minMinutes.value)
      const hours = []
      for (let x = new Date(from); x <= to; x = new Date(x.getTime() + 3600000 * (span > 8 * 3600000 ? 2 : 1))) {
        hours.push({ label: String(x.getHours()), x: ((x - from) / span) * 100 })
      }
      return {
        date: d.date,
        label: cap(date.toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' })),
        off: h ? ['holiday', 'dayoff'].includes(h.type) : weekend,
        holiday: h?.name,
        windows: windows.map((w) => ({
          text: `${formatTime(w.s)}–${formatTime(w.e)}`,
          minutes: Math.round((w.e - w.s) / 60000),
        })),
        windowBlocks: windows.map((w) => ({ style: pct(w.s, w.e) })),
        lanes: who.value.map((pid) => {
          const person = personById.value[pid] || { name: pid, color: '#8e8e93' }
          return {
            id: pid,
            name: person.name,
            short: person.name,
            color: person.color,
            blocks: d.busy.filter((b) => b.people.includes(pid)).map((b) => {
              const s = new Date(b.start), e = new Date(b.end)
              const widthPct = ((Math.min(e, to) - Math.max(s, from)) / span) * 100
              return {
                kind: b.kind,
                style: pct(s, e),
                label: widthPct > 14 ? b.title : '',
                title: `${b.title}, ${timeText(b)}`,
              }
            }),
          }
        }),
        items: buildItems(d.busy, windows),
        ticks: hours,
      }
    })
    .filter((d) => new Date(d.date + 'T23:59') >= now()),
)
const total = computed(() => days.value.reduce((n, d) => n + d.windows.length, 0))
const whoText = computed(() => {
  const names = who.value.map((id) => personById.value[id]?.name || id)
  if (names.length === 1) return names[0] + ' (один)'
  return names.slice(0, -1).join(', ') + ' и ' + names[names.length - 1]
})
const partText = computed(() => ({ all: 'днём и вечером', morning: 'утром', day: 'днём', evening: 'вечером' })[part.value])

// Время события — настоящее, а не обрезанное по выбранной части дня.
function timeText(b) {
  if (b.all_day) return 'весь день'
  const s = new Date(b.event_start || b.start), e = new Date(b.event_end || b.end)
  return `${formatTime(s)}–${formatTime(e)}`
}

// Одна хронология дня: события (одинаковые у нескольких людей — одной строкой) и общие окна.
function buildItems(busy, windows) {
  const merged = new Map()
  for (const b of busy) {
    const key = `${b.title}|${b.event_start || b.start}|${b.event_end || b.end}`
    if (merged.has(key)) merged.get(key).people.push(...b.people.filter((p) => !merged.get(key).people.includes(p)))
    else merged.set(key, { type: b.kind === 'escort' ? 'escort' : 'busy', title: b.title, people: [...b.people],
      sort: b.all_day ? -1 : +new Date(b.start), time: timeText(b) })
  }
  const items = [...merged.values()]
  for (const w of windows) {
    items.push({ type: 'free', sort: +w.s, time: `${formatTime(w.s)}–${formatTime(w.e)}`, minutes: Math.round((w.e - w.s) / 60000) })
  }
  return items.sort((a, b) => a.sort - b.sort || (a.type === 'free') - (b.type === 'free'))
}

function roundUp(d) {
  const x = new Date(d)
  x.setMinutes(Math.ceil(x.getMinutes() / 15) * 15, 0, 0)
  return x
}
function durLabel(m) {
  if (m < 60) return `${m} мин`
  const h = Math.floor(m / 60), r = m % 60
  return r ? `${h} ч ${r} мин` : `${h} ч`
}
function plural(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100
  if (m10 === 1 && m100 !== 11) return one
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few
  return many
}
</script>

<style scoped>
.free {
  display: grid; grid-template-columns: minmax(300px, 380px) 1fr; gap: 8px 32px; align-items: start;
  padding: 4px 24px 40px; max-width: 1200px;
}
.controls { position: sticky; top: 90px; }
.group { background: var(--surface-2); }
.pad { padding: 12px; }
.wide { width: 100%; }
.wide button { flex: 1; padding-left: 4px; padding-right: 4px; }
.lbl { flex: 1; }
.toggle-row { cursor: pointer; }
.switch {
  appearance: none; width: 51px; height: 31px; border-radius: 16px; background: var(--fill); position: relative;
  transition: background .2s; flex: none; margin: 0;
}
.switch::after {
  content: ''; position: absolute; top: 2px; left: 2px; width: 27px; height: 27px; border-radius: 50%;
  background: #fff; box-shadow: 0 2px 6px rgba(0,0,0,.2); transition: transform .2s;
}
.switch:checked { background: var(--ok); }
.switch:checked::after { transform: translateX(20px); }

.results { padding-top: 16px; min-width: 0; }
.summary { font-size: 17px; font-weight: 600; margin: 6px 0 18px; }
.err { color: var(--red); }
.day { padding: 14px 0; border-bottom: .5px solid var(--line); }
.day h3 { margin: 0 0 10px; font-size: 15px; font-weight: 600; display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
.dname.off { color: var(--red); }
.hname { color: var(--red); font-weight: 400; font-size: 13px; }
.lanes { --ln: 64px; display: flex; flex-direction: column; gap: 3px; }
.lane { display: flex; align-items: center; gap: 8px; }
.ln { width: var(--ln); flex: none; font-size: 12px; color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.track { position: relative; flex: 1; height: 20px; border-radius: 5px; background: var(--surface-2); overflow: hidden; }
.blk {
  --c: #8e8e93; position: absolute; top: 0; bottom: 0; border-radius: 4px;
  background: color-mix(in srgb, var(--c) 30%, var(--surface)); box-shadow: inset 2px 0 0 var(--c);
  color: color-mix(in srgb, var(--c) 60%, var(--ink)); font-size: 11px; font-weight: 600; line-height: 20px;
  padding: 0 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.blk.escort { background: repeating-linear-gradient(135deg, color-mix(in srgb, var(--c) 30%, var(--surface)) 0 4px, color-mix(in srgb, var(--c) 14%, var(--surface)) 4px 8px); }
.together .ln { color: var(--ok); font-weight: 600; }
.win { position: absolute; top: 3px; bottom: 3px; background: var(--ok); border-radius: 4px; }
.ticks { position: relative; height: 14px; }
.ticks span { position: absolute; transform: translateX(-50%); font-size: 10px; color: var(--ink-3); }
.ticks span:first-child { transform: none; }
.ticks span:last-child { transform: translateX(-100%); }
.lanes .ticks { margin-left: calc(var(--ln) + 8px); }

.none-text { margin: 6px 0 0; font-size: 13px; }
.agenda { list-style: none; padding: 0; margin: 10px 0 0; display: flex; flex-direction: column; }
.agenda li { display: grid; grid-template-columns: 96px 1fr; gap: 10px; padding: 5px 0; align-items: baseline; }
.agenda li + li { border-top: .5px solid var(--line); }
.tm { font-size: 13px; color: var(--ink-2); font-variant-numeric: tabular-nums; }
.what { display: flex; flex-wrap: wrap; gap: 2px 10px; align-items: baseline; min-width: 0; }
.ttl { font-weight: 500; }
.who { display: inline-flex; gap: 8px; flex-wrap: wrap; font-size: 12px; color: var(--ink-2); }
.pp { display: inline-flex; align-items: center; gap: 4px; }
.pp i { width: 7px; height: 7px; border-radius: 50%; }
.agenda li.free .tm, .agenda li.free strong { color: var(--ok); font-weight: 600; }
.agenda li.escort .ttl { font-style: normal; color: var(--ink-2); }

@media (max-width: 899px) {
  .free { grid-template-columns: 1fr; padding: 0 12px 30px; }
  .controls { position: static; }
  .results { padding-top: 6px; }
}
</style>
