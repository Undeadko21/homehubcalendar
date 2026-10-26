<template>
  <div class="agenda">
    <section v-for="g in groups" :key="g.key" class="day">
      <h2 class="dh" :class="{ today: g.today, off: g.off }">
        <span>{{ g.label }}</span>
        <small v-if="g.holiday" class="hname">{{ g.holiday.name }}</small>
      </h2>
      <button v-for="e in g.events" :key="e.id" class="item" :style="{ '--c': eventColor(e) }"
              :class="{ past: isPast(e), duty: e.duty, conflict: e.duty && e.escort_issue === 'conflict' }" @click="openEvent(e)">
        <span class="time">
          <template v-if="e.all_day">весь день</template>
          <template v-else>{{ startText(e, g.date) }}<br /><span class="faint">{{ endText(e, g.date) }}</span></template>
        </span>
        <span class="bar" aria-hidden="true"></span>
        <span class="body">
          <span class="t">{{ e.title }}</span>
          <span v-if="e.location" class="s">{{ e.location }}</span>
          <span class="who">
            <i v-for="p in e.people" :key="p" :style="{ background: personById[p]?.color }"></i>
            {{ e.people.map((p) => personById[p]?.name).filter(Boolean).join(', ') }}
          </span>
          <EscortBadge v-if="e.escort" :e="e" />
        </span>
      </button>
    </section>
    <p v-if="!groups.length" class="empty">В ближайшие {{ total }} дней событий нет.</p>
    <button class="btn more" @click="extra += 30">Показать ещё 30 дней</button>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { state, openEvent, eventColor, personById } from '../lib/store'
import { useRange } from '../lib/useRange'
import { addDays, startOfDay, overlaps, isoDate, sameDay, eventRange, formatTime, cap } from '../lib/dates'
import EscortBadge from '../components/EscortBadge.vue'

const DAYS = 30
const extra = ref(0)
const now = new Date()
const start = computed(() => startOfDay(state.cursor))
const total = computed(() => DAYS + extra.value)
const { events, holidayMap } = useRange(() => ({ start: start.value, end: addDays(start.value, total.value) }))

const isPast = (e) => !e.all_day && eventRange(e).end <= now
const startText = (e, d) => (eventRange(e).start < d ? '…' : formatTime(eventRange(e).start))
const endText = (e, d) => (eventRange(e).end > addDays(d, 1) ? '…' : formatTime(eventRange(e).end))

const groups = computed(() => {
  const out = []
  for (let i = 0; i < total.value; i++) {
    const d = addDays(start.value, i)
    const evs = events.value.filter((e) => overlaps(e, d, addDays(d, 1)))
    const holiday = holidayMap.value[isoDate(d)]
    if (!evs.length && !holiday) continue
    const weekend = d.getDay() === 0 || d.getDay() === 6
    const diff = Math.round((d - startOfDay(now)) / 86400000)
    const rel = diff === 0 ? 'Сегодня — ' : diff === 1 ? 'Завтра — ' : ''
    out.push({
      key: isoDate(d), date: d, events: evs, holiday,
      today: sameDay(d, now),
      off: holiday ? ['holiday', 'dayoff'].includes(holiday.type) : weekend,
      label: rel + cap(d.toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' })),
    })
  }
  return out
})
</script>

<style scoped>
.agenda { max-width: 760px; width: 100%; padding: 0 20px 40px; }
.dh {
  position: sticky; top: var(--toolbar-h, 0px); z-index: 5; margin: 0; padding: 14px 0 6px;
  background: color-mix(in srgb, var(--bg) 92%, transparent); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
  font-size: 13px; font-weight: 600; color: var(--ink-2); border-bottom: .5px solid var(--line);
  display: flex; gap: 8px; align-items: baseline;
}
.dh.today { color: var(--red); }
.dh.off:not(.today) span { color: var(--ink); }
.hname { color: var(--red); font-weight: 500; }
.item {
  --c: #8e8e93; display: grid; grid-template-columns: 64px 4px 1fr; gap: 0 12px; align-items: stretch;
  width: 100%; border: 0; background: none; text-align: left; padding: 10px 0; color: inherit;
  border-bottom: .5px solid var(--line);
}
.item:hover { background: color-mix(in srgb, var(--fill) 50%, transparent); }
.item.past { opacity: .5; }
.item.duty .bar { background: repeating-linear-gradient(180deg, var(--c) 0 4px, transparent 4px 7px); }
.item.duty .t { font-weight: 500; }
.item.conflict .t { color: var(--red); }
.time { font-size: 13px; font-weight: 500; line-height: 1.35; padding-top: 1px; text-align: right; }
.bar { background: var(--c); border-radius: 2px; }
.body { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.t { font-weight: 600; font-size: 16px; overflow-wrap: anywhere; }
.s { font-size: 13px; color: var(--ink-2); }
.who { font-size: 12px; color: var(--ink-2); display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.who i { width: 7px; height: 7px; border-radius: 50%; }
.more { margin: 20px auto 0; display: flex; }
@media (max-width: 899px) {
  .agenda { padding: 0 12px 30px; }
  .item { grid-template-columns: 52px 4px 1fr; gap: 0 10px; }
}
</style>
