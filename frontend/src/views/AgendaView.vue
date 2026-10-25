<template>
  <div class="agenda">
    <section v-for="g in groups" :key="g.key" class="day" :class="{ today: g.today }">
      <h2>
        <span class="num" :class="{ off: g.off }">{{ g.date.getDate() }}</span>
        <span class="lbl">
          {{ g.label }}
          <small v-if="g.holiday" class="hname">{{ g.holiday.name }}</small>
        </span>
      </h2>
      <div class="items">
        <EventPill v-for="e in g.events" :key="e.id" :e="e" :now="now" />
      </div>
    </section>
    <p v-if="!groups.length" class="empty">В ближайшие {{ DAYS }} дней событий нет.</p>
    <button class="btn more" @click="extra += 30">Показать ещё 30 дней</button>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { state } from '../lib/store'
import { useRange } from '../lib/useRange'
import { addDays, startOfDay, overlaps, isoDate, sameDay, relativeDayName, formatDayLong } from '../lib/dates'
import EventPill from '../components/EventPill.vue'

const DAYS = 30
const extra = ref(0)
const now = new Date()
const start = computed(() => startOfDay(state.cursor))
const total = computed(() => DAYS + extra.value)
const { events, holidayMap } = useRange(() => ({ start: start.value, end: addDays(start.value, total.value) }))

const groups = computed(() => {
  const out = []
  for (let i = 0; i < total.value; i++) {
    const d = addDays(start.value, i)
    const evs = events.value.filter((e) => overlaps(e, d, addDays(d, 1)))
    const holiday = holidayMap.value[isoDate(d)]
    if (!evs.length && !holiday) continue
    const rel = relativeDayName(d, now)
    const weekend = d.getDay() === 0 || d.getDay() === 6
    out.push({
      key: isoDate(d), date: d, events: evs, holiday,
      today: sameDay(d, now),
      off: holiday ? ['holiday', 'dayoff'].includes(holiday.type) : weekend,
      label: rel === formatDayLong(d) ? rel : `${rel}, ${formatDayLong(d).toLowerCase()}`,
    })
  }
  return out
})
</script>

<style scoped>
.agenda { max-width: 760px; width: 100%; margin: 0 auto; padding: 16px 20px 40px; }
.day { display: grid; grid-template-columns: 64px 1fr; gap: 6px 14px; padding: 12px 0; border-bottom: 1px solid var(--line); }
.day h2 { display: contents; }
.num { font-size: 34px; font-weight: 800; letter-spacing: -0.03em; line-height: 1; grid-row: span 2; text-align: right; }
.num.off { color: var(--holiday); }
.today .num { color: var(--now); }
.lbl { font-size: 15px; font-weight: 600; color: var(--ink-2); align-self: end; }
.hname { color: var(--holiday); font-weight: 500; margin-left: 6px; }
.items { display: flex; flex-direction: column; gap: 6px; grid-column: 2; }
.more { margin: 20px auto 0; display: flex; }
@media (max-width: 760px) { .agenda { padding: 10px 12px 30px; } .day { grid-template-columns: 46px 1fr; } .num { font-size: 26px; } }
</style>
