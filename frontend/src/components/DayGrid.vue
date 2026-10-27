<template>
  <div class="dg" :style="{ '--cols': columns.length, '--hh': hourH + 'px' }">
    <div class="scroller">
      <div class="inner">
        <!-- Шапка: люди -->
        <div class="head">
          <div class="axis-sp"></div>
          <div v-for="col in columns" :key="col.person.id" class="ph" :style="{ '--c': col.person.color }">
            <span class="avatar">{{ col.person.emoji || col.person.name[0] }}</span>
            <span class="pn">
              <strong>{{ col.person.name }}</strong>
              <small v-if="col.nowEvent" class="status">сейчас: {{ col.nowEvent.title }}</small>
              <small v-else-if="isToday && col.next" class="next">далее в {{ formatTime(col.next.start) }}: {{ col.next.e.title }}</small>
              <small v-else-if="!col.own.length && !col.allDay.length" class="free">свободный день</small>
            </span>
          </div>
        </div>

        <!-- События на весь день -->
        <div v-if="allDayItems.length" class="allday">
          <div class="lbl">весь день</div>
          <div class="adgrid">
            <div v-for="it in allDayItems" :key="it.key" class="adcell" :style="{ gridColumn: `${it.c0 + 1} / ${it.c1 + 2}` }">
              <EventPill :e="it.e" :owner-id="it.c0 === it.c1 ? columns[it.c0].person.id : null" hide-meta hide-escort />
            </div>
          </div>
        </div>

        <!-- Сетка времени -->
        <div class="grid" :style="{ height: (hEnd - hStart) * hourH + 'px' }">
          <div class="axis">
            <span v-for="h in hours" :key="h" class="hl" :class="{ hide: nowY !== null && Math.abs(nowY - (h - hStart) * hourH) < 10 }"
                  :style="{ top: (h - hStart) * hourH + 'px' }">{{ String(h).padStart(2, '0') }}:00</span>
          </div>
          <div class="cols">
            <i v-for="h in hours" :key="'l' + h" class="line" :style="{ top: (h - hStart) * hourH + 'px' }"></i>
            <div v-for="col in columns" :key="col.person.id" class="col" :style="{ '--c': col.person.color }">
              <button
                v-for="b in col.blocks" :key="b.e.id"
                class="blk" :class="[{ past: b.past, now: b.current, private: b.e.private, short: b.h < 34, 'duty-style': b.e.duty }, b.e.escort_issue ? 'esc-' + b.e.escort_issue : '']"
                :style="{ top: b.y + 'px', height: b.h + 'px', left: b.left + '%', width: b.width + '%' }"
                :title="`${b.e.title}, ${b.time}`"
                @click="openEvent(b.e)"
              >
                <span class="t">{{ b.e.title }}</span>
                <span class="tm">{{ b.time }}<template v-if="b.e.location && b.h >= 52">, {{ b.e.location }}</template></span>
                <EscortBadge v-if="b.e.escort && b.h >= 64" :e="b.e" class="esc" />
              </button>
            </div>
            <!-- Общие события: один блок через колонки всех участников -->
            <button
              v-for="s in spans" :key="s.key"
              class="blk span" :class="[{ past: s.past, now: s.current, private: s.e.private, short: s.h < 34, 'duty-style': s.e.duty }, s.e.escort_issue ? 'esc-' + s.e.escort_issue : '']"
              :style="{ '--c': s.color, top: s.y + 'px', height: s.h + 'px', left: `calc(${s.c0} * 100% / ${columns.length})`, width: `calc(${s.c1 - s.c0 + 1} * 100% / ${columns.length} - 4px)` }"
              :title="`${s.e.title}, ${s.time}`"
              @click="openEvent(s.e)"
            >
              <span class="t">
                <span class="dots" aria-hidden="true"><i v-for="pid in s.people" :key="pid" :style="{ '--c': colorOf(pid) }"></i></span>
                {{ s.e.title }}
              </span>
              <span class="tm">{{ s.time }}<template v-if="s.e.location && s.h >= 52">, {{ s.e.location }}</template></span>
              <EscortBadge v-if="s.e.escort && s.h >= 64" :e="s.e" class="esc" />
            </button>
          </div>
          <!-- Линия «сейчас» -->
          <div v-if="nowY !== null" class="nowline" :style="{ top: nowY + 'px' }">
            <span class="nowlbl">{{ formatTime(now) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
// Дневная сетка как в Календаре Apple: общая шкала часов, колонка на человека,
// пересекающиеся события — рядом, красная линия текущего времени.
import { computed } from 'vue'
import { openEvent } from '../lib/store'
import { addDays, eventRange, formatTime, sameDay } from '../lib/dates'
import EventPill from './EventPill.vue'
import EscortBadge from './EscortBadge.vue'

const props = defineProps({
  columns: { type: Array, required: true }, // [{ person, events }]
  day: { type: Date, required: true },
  now: { type: Date, required: true },
  hourH: { type: Number, default: 52 },
})

const isToday = computed(() => sameDay(props.day, props.now))
const dayEnd = computed(() => addDays(props.day, 1))
const hoursOf = (d) => (d - props.day) / 3600000

// Все события дня (без повторов) и в каких колонках они стоят.
// Поездка («Отвезти Марка…») показывается и у взрослого, и у ребёнка.
const colIndex = computed(() => new Map(props.columns.map((c, i) => [c.person.id, i])))
const allEvents = computed(() => {
  const m = new Map()
  for (const c of props.columns) for (const e of c.events) m.set(e.id, e)
  return [...m.values()]
})
function participants(e) {
  const ids = [...e.people, ...(e.duty?.parent?.escort?.children || [])]
  return [...new Set(ids.map((id) => colIndex.value.get(id)).filter((i) => i !== undefined))].sort((a, b) => a - b)
}
// Подряд идущие колонки: [0,1,3] → [[0,1],[3,3]]
function runs(idx) {
  const out = []
  for (const i of idx) {
    if (out.length && out[out.length - 1][1] === i - 1) out[out.length - 1][1] = i
    else out.push([i, i])
  }
  return out
}
const colorOf = (pid) => props.columns[colIndex.value.get(pid)]?.person.color || '#8e8e93'

const timedAll = computed(() =>
  allEvents.value
    .map((e) => ({ e, r: eventRange(e) }))
    .filter(({ e, r }) => !(e.all_day || r.end - r.start >= 86400000))
    .map(({ e, r }) => ({
      e, r, cols: participants(e),
      start: r.start < props.day ? props.day : r.start,
      end: r.end > dayEnd.value ? dayEnd.value : r.end,
    })),
)

// Общее событие растягивается, если в его колонках в это время больше ничего нет.
const layout = computed(() => {
  const spanned = new Set() // `${id}|${col}`
  const spanList = []
  for (const it of timedAll.value) {
    if (it.cols.length < 2) continue
    // Колонки, где в это время есть другое событие, остаются отдельными; остальные — одной полосой.
    const busyCol = (c) => timedAll.value.some((o) => o !== it && o.start < it.end && it.start < o.end && o.cols.includes(c))
    const free = it.cols.filter((c) => !busyCol(c))
    for (const [c0, c1] of runs(free)) {
      if (c0 === c1) continue
      for (let c = c0; c <= c1; c++) spanned.add(`${it.e.id}|${c}`)
      spanList.push({ it, c0, c1 })
    }
  }
  return { spanned, spanList }
})

const prepared = computed(() =>
  props.columns.map((c, ci) => ({
    ...c,
    timed: timedAll.value.filter((it) => it.cols.includes(ci) && !layout.value.spanned.has(`${it.e.id}|${ci}`)),
    own: timedAll.value.filter((it) => it.cols.includes(ci)),
    allDay: allEvents.value.filter((e) => participants(e).includes(ci) && (e.all_day || eventRange(e).end - eventRange(e).start >= 86400000)),
  })),
)

const allDayItems = computed(() => {
  const out = []
  for (const e of allEvents.value) {
    const r = eventRange(e)
    if (!(e.all_day || r.end - r.start >= 86400000)) continue
    for (const [c0, c1] of runs(participants(e))) out.push({ key: `${e.id}|${c0}`, e, c0, c1 })
  }
  return out
})

// Диапазон шкалы: обычно 8–21, расширяется под ранние/поздние события и текущее время.
const hStart = computed(() => {
  let h = 8
  for (const t of timedAll.value) h = Math.min(h, Math.floor(hoursOf(t.start)))
  if (isToday.value) h = Math.min(h, Math.floor(hoursOf(props.now)))
  return Math.max(0, h)
})
const hEnd = computed(() => {
  let h = 21
  for (const t of timedAll.value) h = Math.max(h, Math.ceil(hoursOf(t.end)))
  if (isToday.value) h = Math.max(h, Math.ceil(hoursOf(props.now) + 0.01))
  return Math.min(24, h)
})
const hours = computed(() => Array.from({ length: hEnd.value - hStart.value + 1 }, (_, i) => hStart.value + i))
const y = (d) => (hoursOf(d) - hStart.value) * props.hourH

const columns = computed(() =>
  prepared.value.map((c) => {
    // Раскладка пересечений: группы пересекающихся событий делят ширину колонки.
    const items = [...c.timed].sort((a, b) => a.start - b.start || b.end - a.end)
    const blocks = []
    let group = []
    let groupEnd = 0
    const flush = () => {
      const lanes = []
      for (const it of group) {
        let lane = lanes.findIndex((end) => end <= it.start)
        if (lane === -1) { lane = lanes.length; lanes.push(0) }
        lanes[lane] = it.end
        it.lane = lane
      }
      for (const it of group) {
        const n = lanes.length
        const top = y(it.start)
        const h = Math.max(y(it.end) - top, 22)
        blocks.push({
          e: it.e, y: top + 1, h: h - 2,
          left: (it.lane / n) * 100, width: 100 / n,
          past: it.r.end <= props.now,
          current: it.r.start <= props.now && it.r.end > props.now,
          time: `${formatTime(it.r.start)}–${formatTime(it.r.end)}`,
        })
      }
      group = []
    }
    for (const it of items) {
      if (group.length && it.start >= groupEnd) flush()
      group.push(it)
      groupEnd = Math.max(groupEnd, +it.end)
    }
    if (group.length) flush()

    const upcoming = c.own.filter((t) => t.r.start > props.now).sort((a, b) => a.r.start - b.r.start)[0]
    return { ...c, blocks, next: upcoming ? { e: upcoming.e, start: upcoming.r.start } : null }
  }),
)

const spans = computed(() =>
  layout.value.spanList.map(({ it, c0, c1 }) => {
    const top = y(it.start)
    const h = Math.max(y(it.end) - top, 22)
    const people = [...new Set([...it.e.people, ...(it.e.duty?.parent?.escort?.children || [])])].filter((p) => colIndex.value.has(p))
    return {
      key: `${it.e.id}|${c0}`, e: it.e, c0, c1, y: top + 1, h: h - 2, people,
      color: colorOf(it.e.duty ? it.e.people[0] : people[0]),
      past: it.r.end <= props.now,
      current: it.r.start <= props.now && it.r.end > props.now,
      time: `${formatTime(it.r.start)}–${formatTime(it.r.end)}`,
    }
  }),
)

const nowY = computed(() => {
  if (!isToday.value) return null
  const v = y(props.now)
  return v >= 0 && v <= (hEnd.value - hStart.value) * props.hourH ? v : null
})
</script>

<style scoped>
.dg { --axis: 52px; }
.scroller { overflow-x: auto; }
.inner { min-width: calc(var(--axis) + var(--cols) * 150px); }
.head { display: grid; grid-template-columns: var(--axis) repeat(var(--cols), minmax(150px, 1fr)); }
.head { padding-bottom: 8px; border-bottom: .5px solid var(--line); }
.ph { --c: #888; display: flex; align-items: center; gap: 8px; padding: 0 8px; min-width: 0; }
.avatar { width: 30px; height: 30px; border-radius: 50%; flex: none; display: grid; place-items: center; background: var(--c); color: #fff; font-weight: 600; font-size: 15px; }
.pn { display: flex; flex-direction: column; min-width: 0; flex: 1; overflow: hidden; line-height: 1.25; }
.pn strong { font-size: 16px; }
.pn small { display: block; max-width: 100%; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--ink-2); }
.pn .status { color: var(--c); font-weight: 600; }
.pn .free { color: var(--ink-3); }

.allday { display: grid; grid-template-columns: var(--axis) 1fr; border-bottom: .5px solid var(--line); padding: 4px 0; }
.adgrid { display: grid; grid-template-columns: repeat(var(--cols), minmax(150px, 1fr)); grid-auto-flow: row dense; gap: 3px 0; }
.lbl { font-size: 11px; color: var(--ink-2); text-align: right; padding-right: 8px; align-self: center; }
.adcell { padding: 0 2px; min-width: 0; }

.grid { position: relative; display: grid; grid-template-columns: var(--axis) 1fr; margin-top: 10px; }
.axis { position: relative; }
.hl { position: absolute; right: 8px; transform: translateY(-50%); font-size: 11px; color: var(--ink-2); font-variant-numeric: tabular-nums; }
.hl.hide { visibility: hidden; }
.cols { position: relative; display: grid; grid-template-columns: repeat(var(--cols), minmax(150px, 1fr)); }
.line { position: absolute; left: 0; right: 0; border-top: .5px solid var(--line); }
.col { --c: #888; position: relative; border-left: .5px solid var(--line); }

.blk {
  position: absolute; border: 0; text-align: left; overflow: hidden; border-radius: 5px;
  padding: 3px 6px 3px 8px; margin: 0 2px; width: calc(100% - 4px);
  background: color-mix(in srgb, var(--c) 18%, var(--surface));
  color: color-mix(in srgb, var(--c) 62%, var(--ink));
  box-shadow: inset 3px 0 0 var(--c);
  display: flex; flex-direction: column; gap: 1px; line-height: 1.2;
}
.blk:hover { background: color-mix(in srgb, var(--c) 28%, var(--surface)); z-index: 2; }
.blk .t { font-weight: 600; font-size: 13px; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.blk .tm { font-size: 11px; opacity: .85; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.blk.short { flex-direction: row; align-items: center; gap: 6px; padding-top: 1px; padding-bottom: 1px; }
.blk.short .t { -webkit-line-clamp: 1; white-space: nowrap; }
.blk.past { opacity: .5; }
.blk.span { z-index: 1; }
.dots { display: inline-flex; gap: 3px; margin-right: 4px; vertical-align: middle; }
.dots i { width: 7px; height: 7px; border-radius: 50%; background: var(--c); display: block; }
.blk.duty-style { background: repeating-linear-gradient(-45deg, color-mix(in srgb, var(--c) 10%, var(--surface)) 0 5px, color-mix(in srgb, var(--c) 24%, var(--surface)) 5px 10px); }
.blk.now { box-shadow: inset 3px 0 0 var(--c), inset 0 0 0 1.5px var(--c); }
.blk.private { background: repeating-linear-gradient(135deg, color-mix(in srgb, var(--c) 10%, var(--surface)) 0 6px, color-mix(in srgb, var(--c) 18%, var(--surface)) 6px 12px); }
.blk.esc-conflict { box-shadow: inset 3px 0 0 var(--c), inset 0 0 0 1.5px var(--red); }
.blk.esc-unassigned { box-shadow: inset 3px 0 0 var(--c), inset 0 0 0 1.5px var(--warn); }
.esc { margin-top: 2px; }

.nowline { position: absolute; left: var(--axis); right: 0; height: 0; border-top: 2px solid var(--red); z-index: 3; pointer-events: none; }
.nowline::before { content: ''; position: absolute; left: -5px; top: -6px; width: 10px; height: 10px; border-radius: 50%; background: var(--red); }
.nowlbl {
  position: absolute; right: calc(100% + 6px); top: 0; transform: translateY(-50%);
  background: var(--red); color: #fff; font-size: 11px; font-weight: 600; padding: 1px 4px; border-radius: 4px;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 599px) {
  .dg { --axis: 44px; }
  .inner { min-width: calc(var(--axis) + var(--cols) * 104px); }
  .head { grid-template-columns: var(--axis) repeat(var(--cols), minmax(104px, 1fr)); }
  .adgrid { grid-template-columns: repeat(var(--cols), minmax(104px, 1fr)); }
  .cols { grid-template-columns: repeat(var(--cols), minmax(104px, 1fr)); }
  .ph { flex-direction: column; align-items: stretch; gap: 4px; padding: 0 4px; }
  .pn { flex: none; width: 100%; }
  .avatar { align-self: flex-start; width: 26px; height: 26px; font-size: 13px; }
  .pn strong { font-size: 14px; }
  .blk { padding: 2px 4px 2px 6px; }
  .blk .t { font-size: 12px; }
  .nowlbl { font-size: 10px; padding: 1px 3px; }
}
</style>
