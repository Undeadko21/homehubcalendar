<template>
  <div class="mini">
    <div class="head">
      <strong>{{ title }}</strong>
      <span class="nav">
        <button class="btn icon sm" aria-label="Предыдущий месяц" @click="shift(-1)">‹</button>
        <button class="btn icon sm" aria-label="Следующий месяц" @click="shift(1)">›</button>
      </span>
    </div>
    <div class="grid" role="grid" :aria-label="title">
      <span v-for="w in WEEKDAYS" :key="w" class="wd">{{ w }}</span>
      <button
        v-for="d in days" :key="+d.date" class="day"
        :class="{ other: d.other, today: d.today, sel: d.sel, off: d.off }"
        :aria-label="d.date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })"
        @click="pick(d.date)"
      >
        {{ d.date.getDate() }}
        <i v-if="d.busy" class="dot"></i>
      </button>
    </div>
  </div>
</template>

<script setup>
// Мини-календарь месяца, как в боковой панели Календаря macOS. Точка — есть события.
import { computed, ref, watch } from 'vue'
import { state } from '../lib/store'
import { useRange } from '../lib/useRange'
import { addDays, startOfMonth, startOfWeek, sameDay, isoDate, overlaps, formatMonth } from '../lib/dates'

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
const month = ref(startOfMonth(state.cursor))
watch(() => state.cursor, (c) => { month.value = startOfMonth(c) })

const gridStart = computed(() => startOfWeek(month.value))
const { events, holidayMap } = useRange(() => ({ start: gridStart.value, end: addDays(gridStart.value, 42) }))
const title = computed(() => formatMonth(month.value).replace(/\s*г\.$/, ''))

const days = computed(() => {
  const today = new Date()
  return Array.from({ length: 42 }, (_, i) => {
    const date = addDays(gridStart.value, i)
    const h = holidayMap.value[isoDate(date)]
    const weekend = date.getDay() === 0 || date.getDay() === 6
    return {
      date,
      other: date.getMonth() !== month.value.getMonth(),
      today: sameDay(date, today),
      sel: sameDay(date, state.cursor),
      off: h ? ['holiday', 'dayoff'].includes(h.type) : weekend,
      busy: events.value.some((e) => overlaps(e, date, addDays(date, 1))),
    }
  })
})

function shift(n) {
  const m = new Date(month.value)
  m.setMonth(m.getMonth() + n)
  month.value = m
}
function pick(d) { state.cursor = d }
</script>

<style scoped>
.mini { padding: 4px 4px 0; }
.head { display: flex; align-items: center; justify-content: space-between; padding: 0 2px 6px 6px; }
.head strong { font-size: 14px; font-weight: 600; }
.nav { display: flex; }
.sm { min-width: 26px; min-height: 26px; font-size: 18px; padding: 0; color: var(--ink-2); }
.grid { display: grid; grid-template-columns: repeat(7, 1fr); row-gap: 1px; text-align: center; }
.wd { font-size: 10px; color: var(--ink-3); font-weight: 600; padding-bottom: 3px; }
.day {
  position: relative; border: 0; background: none; font-size: 12px; height: 28px; width: 28px; margin: 0 auto;
  border-radius: 50%; color: var(--ink); padding: 0;
}
.day:hover { background: var(--fill); }
.day.off { color: var(--ink-2); }
.day.other { color: var(--ink-3); }
.day.sel { background: var(--ink); color: var(--bg); font-weight: 600; }
.day.today { color: var(--red); font-weight: 700; }
.day.today.sel { background: var(--red); color: #fff; }
.dot { position: absolute; bottom: 2px; left: 50%; width: 3px; height: 3px; margin-left: -1.5px; border-radius: 50%; background: var(--ink-3); }
.day.sel .dot { background: currentColor; }
</style>
