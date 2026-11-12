<template>
  <div class="fw">
    <Skeleton v-if="!loaded && !events.length" blocks :rows="3" class="sk" />
    <div class="scroll">
      <table class="grid" :style="{ '--n': cols.length }">
        <thead>
          <tr>
            <th class="corner"></th>
            <th v-for="p in cols" :key="p.id" :style="{ '--c': p.color }">
              <span class="avatar">{{ p.emoji || p.name[0] }}</span><span class="pn">{{ p.name }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in days" :key="d.key" :class="{ today: d.today, off: d.off }">
            <th class="day" scope="row">
              <span class="wd">{{ d.wd }}</span><span class="dn">{{ d.num }}</span>
              <small v-if="d.holiday && d.holiday.type !== 'vacation'" class="hn">{{ d.holiday.name }}</small>
            </th>
            <td v-for="p in cols" :key="p.id">
              <button v-for="e in d.cells[p.id]" :key="e.id" class="chip" :class="{ duty: e.duty, shared: e.people.length > 1 }"
                      :style="{ '--c': eventColor(e) }" @click="openEvent(e)">
                <span class="t">{{ e.all_day ? '' : time(e, d.date) }}</span>
                <span class="n">{{ titleWithIcon(e) }}</span>
              </button>
              <span v-if="!d.cells[p.id].length" class="none">·</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="!cols.length" class="empty">Нет выбранных людей — отметьте их в списке «Люди».</p>
  </div>
</template>

<script setup>
import Skeleton from '../components/Skeleton.vue'
import { titleWithIcon } from '../lib/icons'
import { computed } from 'vue'
import { state, visiblePeople, openEvent, eventColor } from '../lib/store'
import { useRange } from '../lib/useRange'
import { addDays, startOfDay, startOfWeek, overlaps, isoDate, sameDay, eventRange, formatTime, cap } from '../lib/dates'

const start = computed(() => startOfWeek(state.cursor))
const { events, holidayMap, loaded } = useRange(() => ({ start: start.value, end: addDays(start.value, 7) }))
const cols = computed(() => visiblePeople.value)
const now = new Date()

const time = (e, d) => (eventRange(e).start < d ? '…' : formatTime(eventRange(e).start))

const days = computed(() => {
  const out = []
  for (let i = 0; i < 7; i++) {
    const d = addDays(start.value, i)
    const evs = events.value.filter((e) => overlaps(e, d, addDays(d, 1)))
      .sort((a, b) => (b.all_day ? 1 : 0) - (a.all_day ? 1 : 0) || eventRange(a).start - eventRange(b).start)
    const cells = {}
    for (const p of cols.value) cells[p.id] = evs.filter((e) => e.people.includes(p.id))
    const holiday = holidayMap.value[isoDate(d)]
    const weekend = d.getDay() === 0 || d.getDay() === 6
    out.push({
      key: isoDate(d), date: d, cells, holiday, today: sameDay(d, now),
      off: holiday ? ['holiday', 'dayoff'].includes(holiday.type) : weekend,
      wd: cap(d.toLocaleDateString('ru-RU', { weekday: 'short' })), num: d.getDate(),
    })
  }
  return out
})
</script>

<style scoped>
.fw { padding: 8px 0 24px; }
.scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }
.grid { border-collapse: separate; border-spacing: 0; width: 100%; min-width: calc(64px + var(--n) * 128px); table-layout: fixed; }
thead th { position: sticky; top: 0; z-index: 2; background: var(--bg); padding: 8px 6px; font-weight: 600; font-size: 13px; text-align: left; border-bottom: .5px solid var(--line); }
.avatar { display: inline-grid; place-items: center; width: 22px; height: 22px; border-radius: 50%; background: var(--c); color: #fff; font-size: 12px; margin-right: 6px; vertical-align: middle; }
th.corner, th.day { width: 64px; }
th.day { text-align: left; vertical-align: top; padding: 8px 6px; font-weight: 600; border-bottom: .5px solid var(--line); position: sticky; left: 0; background: var(--bg); z-index: 1; }
.wd { display: block; font-size: 11px; color: var(--ink-2); text-transform: uppercase; }
.dn { font-size: 20px; }
.hn { display: block; font-size: 10px; color: var(--ink-2); font-weight: 400; line-height: 1.2; }
tr.today th.day .dn { color: var(--red); }
tr.off th.day .wd { color: var(--red); }
td { vertical-align: top; padding: 4px; border-bottom: .5px solid var(--line); border-left: .5px solid var(--line); min-height: 44px; }
tr.today td { background: color-mix(in srgb, var(--red) 5%, transparent); }
.chip { display: flex; gap: 5px; width: 100%; text-align: left; margin: 0 0 3px; padding: 3px 6px; border: 0; border-radius: 6px; cursor: pointer;
  background: color-mix(in srgb, var(--c) 18%, transparent); box-shadow: inset 3px 0 0 var(--c); color: var(--ink); font: inherit; font-size: 12.5px; }
.chip .t { color: var(--ink-2); font-variant-numeric: tabular-nums; flex: none; }
.chip .n { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
.chip.duty { font-style: italic; }
.chip.shared { outline: 1px solid color-mix(in srgb, var(--c) 45%, transparent); }
.none { color: var(--ink-3, #aaa); font-size: 12px; padding-left: 6px; }
.empty { text-align: center; color: var(--ink-2); }
:global(.no-color-mix) .chip { background: rgba(120, 120, 128, .14); }
</style>
