<template>
  <div class="mp" @touchstart.passive="ts" @touchend.passive="te">
    <div class="grid">
      <div class="wk-head">
        <span class="wn"></span>
        <span v-for="(n, i) in WD" :key="n" :class="{ we: i > 4 }">{{ n }}</span>
      </div>
      <div v-for="w in weeks" :key="w.n" class="week">
        <span class="wn" :class="{ cur: w.current }">{{ w.n }}</span>
        <button v-for="c in w.days" :key="c.key" class="cell" :class="{ out: !c.inMonth, we: c.weekend, off: c.off }" :disabled="!c.inMonth" @click="pick(c.date)">
          <template v-if="c.inMonth">
            <span class="dn" :class="{ today: c.today, sel: c.sel && !c.today, selt: c.sel && c.today }">{{ c.date.getDate() }}</span>
            <span class="bars">
              <i v-for="(col, i) in c.colors" :key="i" :style="{ background: col }"></i>
            </span>
          </template>
        </button>
      </div>
    </div>

    <ul class="day-list">
      <li v-for="e in dayEvents" :key="e.id" class="row" :style="{ '--c': eventColor(e) }" @click="openEvent(e)">
        <span class="bar"></span>
        <span class="mid">
          <span class="t">{{ e.title }}</span>
          <span v-if="e.location" class="loc">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0113 0c0 5.4-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.2"/></svg>{{ e.location }}
          </span>
        </span>
        <span class="tm" v-if="e.all_day">весь день</span>
        <span class="tm" v-else><b>{{ hm(e.start) }}</b><span>{{ hm(e.end) }}</span></span>
      </li>
      <li v-if="!dayEvents.length" class="none">Нет событий</li>
    </ul>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { state, openEvent, eventColor } from '../lib/store'
import { useRange } from '../lib/useRange'
import { addDays, startOfWeek, startOfMonth, startOfDay, isoDate, sameDay, eventRange } from '../lib/dates'

const WD = ['п', 'в', 'с', 'ч', 'п', 'с', 'в']

const gridStart = () => startOfWeek(startOfMonth(state.cursor))
const range = () => ({ start: gridStart(), end: addDays(gridStart(), 42) })
const { events, holidayMap } = useRange(range)

// События по дням (многодневные — на каждый день).
const byDay = computed(() => {
  const m = {}
  for (const e of events.value) {
    const r = eventRange(e)
    let d = startOfDay(r.start)
    const last = startOfDay(e.all_day ? addDays(r.end, -1) : new Date(+r.end - 1))
    for (let i = 0; i < 42 && d <= (last < d ? d : last); i++, d = addDays(d, 1)) (m[isoDate(d)] ||= []).push(e)
  }
  return m
})

const weeks = computed(() => {
  const s = gridStart()
  const month = state.cursor.getMonth()
  const today = new Date()
  const lastDay = new Date(state.cursor.getFullYear(), month + 1, 0)
  const out = []
  for (let w = 0; w < 6; w++) {
    const ws = addDays(s, w * 7)
    if (ws > lastDay) break
    const days = Array.from({ length: 7 }, (_, i) => {
      const date = addDays(ws, i)
      const key = isoDate(date)
      const list = byDay.value[key] || []
      const colors = [...new Set(list.map((e) => eventColor(e)))].slice(0, 5)
      const h = holidayMap.value[key]
      return { key, date, inMonth: date.getMonth() === month, weekend: i > 4, off: !!h && h.type !== 'vacation', colors, today: sameDay(date, today), sel: sameDay(date, state.cursor) }
    })
    out.push({ n: isoWeek(addDays(ws, 3)), current: days.some((d) => d.today), days })
  }
  return out
})

function isoWeek(d) {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
  t.setUTCDate(t.getUTCDate() + 4 - (t.getUTCDay() || 7))
  const y0 = new Date(Date.UTC(t.getUTCFullYear(), 0, 1))
  return Math.ceil(((t - y0) / 86400000 + 1) / 7)
}

const dayEvents = computed(() =>
  [...(byDay.value[isoDate(state.cursor)] || [])].sort((a, b) => (b.all_day ? 1 : 0) - (a.all_day ? 1 : 0) || String(a.start).localeCompare(String(b.start))),
)

const hm = (iso) => new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
const pick = (d) => { state.cursor = d }

// Свайп влево/вправо — соседний месяц.
let x0 = null, y0 = null
const ts = (e) => { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY }
const te = (e) => {
  if (x0 == null) return
  const dx = e.changedTouches[0].clientX - x0
  const dy = e.changedTouches[0].clientY - y0
  x0 = null
  if (Math.abs(dx) < 70 || Math.abs(dx) < Math.abs(dy) * 1.5) return
  const c = new Date(state.cursor.getFullYear(), state.cursor.getMonth() + (dx < 0 ? 1 : -1), 1)
  state.cursor = c
}
</script>

<style scoped>
.mp { padding: 0 0 24px; }
.grid { padding: 0 0 0 2px; }
.wk-head, .week { display: grid; grid-template-columns: 22px repeat(7, 1fr); align-items: start; }
.wk-head { font-size: 12px; font-weight: 600; text-align: center; padding: 2px 0 4px; border-bottom: 1px solid var(--line-strong); }
.wk-head .we { color: var(--ink-2); }
.week { border-bottom: 1px solid var(--line); min-height: 68px; }
.wn { font-size: 10px; font-weight: 600; color: var(--ink-3); padding: 2px 0 0 2px; }
.wn.cur { color: var(--red); }
.cell { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 8px 0 6px; background: none; border: 0; font: inherit; color: var(--ink); cursor: pointer; min-height: 68px; -webkit-tap-highlight-color: transparent; }
.cell:disabled { cursor: default; }
.cell.we .dn, .cell.off .dn { color: var(--ink-2); }
.dn { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 50%; font-size: 20px; font-weight: 500; }
.dn.today { background: var(--red); color: #fff; font-weight: 600; }
.dn.sel { background: var(--ink); color: var(--bg); }
.dn.selt { box-shadow: 0 0 0 2px var(--bg), 0 0 0 4px var(--red); }
.bars { display: flex; width: 78%; height: 5px; gap: 0; border-radius: 3px; overflow: hidden; opacity: .55; }
.bars i { flex: 1; height: 100%; display: block; }

.day-list { list-style: none; margin: 0; padding: 0 16px; }
.row { display: flex; align-items: stretch; gap: 10px; padding: 12px 0; border-bottom: 1px solid var(--line); cursor: pointer; }
.bar { width: 3px; border-radius: 2px; background: var(--c); flex: none; }
.mid { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.t { font-size: 17px; font-weight: 600; line-height: 1.2; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.loc { font-size: 15px; color: var(--ink-2); display: flex; align-items: center; gap: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.loc svg { width: 14px; height: 14px; flex: none; fill: none; stroke: currentColor; stroke-width: 1.8; }
.tm { display: flex; flex-direction: column; align-items: flex-end; font-size: 16px; color: var(--ink-2); flex: none; line-height: 1.25; }
.tm b { color: var(--ink); font-weight: 500; }
.none { padding: 24px 0; color: var(--ink-3); text-align: center; font-size: 15px; }
</style>
