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
              <small v-else-if="!col.timed.length && !col.allDay.length" class="free">свободный день</small>
            </span>
          </div>
        </div>

        <!-- События на весь день -->
        <div v-if="hasAllDay" class="allday">
          <div class="axis-sp lbl">весь день</div>
          <div v-for="col in columns" :key="col.person.id" class="adcell">
            <EventPill v-for="e in col.allDay" :key="e.id" :e="e" :owner-id="col.person.id" hide-meta hide-escort />
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

const prepared = computed(() =>
  props.columns.map((c) => {
    const allDay = []
    const timed = []
    for (const e of c.events) {
      const r = eventRange(e)
      if (e.all_day || r.end - r.start >= 86400000) allDay.push(e)
      else timed.push({ e, start: r.start < props.day ? props.day : r.start, end: r.end > dayEnd.value ? dayEnd.value : r.end, r })
    }
    return { ...c, allDay, timed }
  }),
)
const hasAllDay = computed(() => prepared.value.some((c) => c.allDay.length))

// Диапазон шкалы: обычно 8–21, расширяется под ранние/поздние события и текущее время.
const hStart = computed(() => {
  let h = 8
  for (const c of prepared.value) for (const t of c.timed) h = Math.min(h, Math.floor(hoursOf(t.start)))
  if (isToday.value) h = Math.min(h, Math.floor(hoursOf(props.now)))
  return Math.max(0, h)
})
const hEnd = computed(() => {
  let h = 21
  for (const c of prepared.value) for (const t of c.timed) h = Math.max(h, Math.ceil(hoursOf(t.end)))
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

    const upcoming = c.timed.filter((t) => t.r.start > props.now).sort((a, b) => a.r.start - b.r.start)[0]
    return { ...c, blocks, next: upcoming ? { e: upcoming.e, start: upcoming.r.start } : null }
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
.head, .allday { display: grid; grid-template-columns: var(--axis) repeat(var(--cols), minmax(150px, 1fr)); }
.head { padding-bottom: 8px; border-bottom: .5px solid var(--line); }
.ph { --c: #888; display: flex; align-items: center; gap: 8px; padding: 0 8px; min-width: 0; }
.avatar { width: 30px; height: 30px; border-radius: 50%; flex: none; display: grid; place-items: center; background: var(--c); color: #fff; font-weight: 600; font-size: 15px; }
.pn { display: flex; flex-direction: column; min-width: 0; line-height: 1.25; }
.pn strong { font-size: 16px; }
.pn small { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--ink-2); }
.pn .status { color: var(--c); font-weight: 600; }
.pn .free { color: var(--ink-3); }

.allday { border-bottom: .5px solid var(--line); padding: 4px 0; }
.lbl { font-size: 11px; color: var(--ink-2); text-align: right; padding-right: 8px; align-self: center; }
.adcell { padding: 0 4px; display: flex; flex-direction: column; gap: 3px; min-width: 0; }

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
  .head, .allday { grid-template-columns: var(--axis) repeat(var(--cols), minmax(104px, 1fr)); }
  .cols { grid-template-columns: repeat(var(--cols), minmax(104px, 1fr)); }
  .ph { flex-direction: column; align-items: flex-start; gap: 4px; padding: 0 4px; }
  .avatar { width: 26px; height: 26px; font-size: 13px; }
  .pn strong { font-size: 14px; }
  .blk { padding: 2px 4px 2px 6px; }
  .blk .t { font-size: 12px; }
  .nowlbl { font-size: 10px; padding: 1px 3px; }
}
</style>
