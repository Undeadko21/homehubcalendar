<template>
  <div class="timeline">
    <div class="bar">
      <div class="seg" role="group" aria-label="Сколько дней показывать">
        <button v-for="n in [1, 3, 7]" :key="n" :class="{ on: days === n }" @click="setDays(n)">
          {{ n === 1 ? '1 день' : n === 3 ? '3 дня' : 'Неделя' }}
        </button>
      </div>
      <span v-if="!compact" class="faint hint">Шкала с {{ H0 }}:00 до {{ H1 }}:00</span>
    </div>

    <div ref="scroller" class="scroller">
      <div class="grid" :style="{ width: totalW + 'px', '--name': NAME_W_C + 'px' }">
        <!-- шапка дней -->
        <div class="head">
          <div class="corner"></div>
          <div
            v-for="(d, i) in dayList" :key="i" class="dayhead"
            :class="{ today: d.today, off: d.off, short: d.holiday?.type === 'short', compact }"
            :style="{ width: dayW + 'px' }"
            :title="d.holiday?.name || ''"
          >
            <strong><span class="wd">{{ d.wd }}</span> <span class="dn">{{ d.num }}</span></strong>
            <span v-if="d.holiday" class="hname">{{ d.holiday.name }}</span>
            <div v-if="!compact" class="hours">
              <span v-for="h in hourTicks" :key="h" :style="{ left: hx(h) + 'px' }">{{ h }}</span>
            </div>
          </div>
        </div>

        <!-- дорожки людей -->
        <div v-for="lane in lanes" :key="lane.person.id" class="lane" :style="{ '--c': lane.person.color }">
          <div class="who">
            <span class="avatar">{{ lane.person.emoji || lane.person.name[0] }}</span>
            <span v-if="!narrow" class="pname">{{ lane.person.name }}</span>
          </div>
          <div class="track" :style="{ height: lane.height + 'px' }">
            <div v-for="(d, i) in dayList" :key="i" class="cell" :class="{ today: d.today, off: d.off }" :data-day="isoDate(d.date)"
                 :style="{ left: i * dayW + 'px', width: dayW + 'px' }">
              <i v-for="h in (compact ? [] : hourTicks)" :key="h" class="tick" :style="{ left: hx(h) + 'px' }"></i>
            </div>
            <button
              v-for="b in lane.blocks" :key="b.key"
              class="block" :class="[{ allday: b.allDay, past: b.past, private: b.e.private, multi: b.e.people.length > 1, 'duty-style': b.e.duty }, b.e.escort_issue ? 'esc-' + b.e.escort_issue : '']"
              :style="{ left: b.x + 'px', width: b.w + 'px', top: b.y + 'px', height: (b.allDay ? ALLDAY_H : ROW_H) - 4 + 'px', ...(b.e.color ? { '--c': b.e.color } : {}) }"
              :title="b.e.title"
              @click="openEvent(b.e)"
              @pointerdown="down($event, b)"
            >
              <span v-if="compact && !b.allDay" class="bs">{{ b.startLabel }}</span>
              <span class="bt">{{ b.e.title }}</span>
              <span v-if="!compact && !b.allDay && b.w > 90" class="bs">{{ b.time }}</span>
            </button>
          </div>
        </div>

        <div v-if="nowX !== null" class="nowline" :style="{ left: NAME_W_C + nowX + 'px' }"></div>
      </div>
      <p v-if="!lanes.length" class="empty pad">Выберите хотя бы одного человека в фильтре выше.</p>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { state, visiblePeople, openEvent, setTimelineDays } from '../lib/store'
import { useRange } from '../lib/useRange'
import { canMove, moveEvent } from '../lib/moveEvent'
import { startDrag, dayUnder } from '../lib/drag'
import { addDays, startOfDay, startOfWeek, eventRange, isoDate, sameDay, formatTime, DAY } from '../lib/dates'

const H0 = 7
const H1 = 23
const ROW_H = 30
const ALLDAY_H = 26

const days = computed(() => state.timelineDays)
const narrow = computed(() => width.value < 600)
const NAME_W_C = computed(() => (narrow.value ? 48 : 120))
const setDays = setTimelineDays

const scroller = ref(null)
const width = ref(1000)
let ro
const now = ref(new Date())
let t
onMounted(() => {
  ro = new ResizeObserver(([e]) => (width.value = e.contentRect.width))
  ro.observe(scroller.value)
  t = setInterval(() => (now.value = new Date()), 30000)
})
onUnmounted(() => { ro?.disconnect(); clearInterval(t) })

const start = computed(() => (days.value === 7 ? startOfWeek(state.cursor) : startOfDay(state.cursor)))
const end = computed(() => addDays(start.value, days.value))
const { events, holidayMap } = useRange(() => ({ start: start.value, end: end.value }))

// Неделя — компактные списки по дням; 1–3 дня — пропорциональная шкала времени.
const compact = computed(() => days.value === 7)
const minDay = computed(() => (days.value === 1 ? 600 : days.value === 3 ? 300 : 150))
const dayW = computed(() => Math.max(minDay.value, Math.floor((width.value - NAME_W_C.value) / days.value)))
const totalW = computed(() => NAME_W_C.value + dayW.value * days.value)
const hourTicks = computed(() => {
  const step = dayW.value >= 500 ? 1 : dayW.value >= 260 ? 2 : 4
  const out = []
  for (let h = H0; h < H1; h += step) out.push(h)
  return out
})
const hx = (h) => ((h - H0) / (H1 - H0)) * dayW.value

const dayList = computed(() =>
  Array.from({ length: days.value }, (_, i) => {
    const d = addDays(start.value, i)
    const holiday = holidayMap.value[isoDate(d)]
    const weekend = d.getDay() === 0 || d.getDay() === 6
    const off = holiday ? holiday.type === 'holiday' || holiday.type === 'dayoff' : weekend
    const wd = d.toLocaleDateString('ru-RU', { weekday: 'short' })
    return { date: d, today: sameDay(d, now.value), off, holiday, wd, num: d.getDate() }
  }),
)

// Позиция момента времени внутри дня (0..dayW), с обрезкой по рабочему диапазону.
function xIn(d, dayIndex) {
  const h = d.getHours() + d.getMinutes() / 60
  const clamped = Math.min(Math.max(h, H0), H1)
  return dayIndex * dayW.value + ((clamped - H0) / (H1 - H0)) * dayW.value
}

const lanes = computed(() =>
  visiblePeople.value
    .map((person) => {
      const mine = events.value.filter((e) => e.people.includes(person.id))
      const allDay = []
      const timed = []
      for (const e of mine) {
        const r = eventRange(e)
        if (e.all_day || r.end - r.start >= DAY) {
          const a = Math.max(0, Math.floor((startOfDay(r.start) - start.value) / DAY))
          const bEnd = e.all_day ? r.end : addDays(startOfDay(r.end), 1)
          const b = Math.min(days.value, Math.ceil((bEnd - start.value) / DAY))
          if (b > a) allDay.push({ e, x: a * dayW.value + 2, w: (b - a) * dayW.value - 4, allDay: true })
          continue
        }
        // Событие может пересекать полночь — режем по дням.
        for (let i = 0; i < days.value; i++) {
          const ds = addDays(start.value, i), de = addDays(ds, 1)
          if (r.start >= de || r.end <= ds) continue
          const s = r.start < ds ? ds : r.start
          const en = r.end > de ? de : r.end
          const x = xIn(s, i)
          const x2 = r.end > de ? (i + 1) * dayW.value : xIn(en, i)
          timed.push({
            e, x: x + 1, w: Math.max(x2 - x - 2, 8), allDay: false, past: r.end <= now.value, day: i,
            time: `${formatTime(r.start)}–${formatTime(r.end)}`, key: e.id + ':' + i,
            startLabel: r.start < ds ? '…' : formatTime(r.start), sortKey: +s,
          })
        }
      }
      const adRows = pack(allDay)
      let tRows
      if (compact.value) {
        // Список по дням: каждый блок на всю ширину дня, по порядку времени.
        const perDay = Array.from({ length: days.value }, () => [])
        for (const b of timed) perDay[b.day].push(b)
        for (const list of perDay) {
          list.sort((a, b) => a.sortKey - b.sortKey)
          list.forEach((b, idx) => { b.x = b.day * dayW.value + 3; b.w = dayW.value - 6; b.row = idx })
        }
        tRows = Math.max(0, ...perDay.map((l) => l.length))
      } else {
        tRows = pack(timed)
      }
      const adH = adRows * ALLDAY_H
      for (const b of allDay) { b.y = b.row * ALLDAY_H + 4; b.key = b.e.id }
      for (const b of timed) b.y = adH + b.row * ROW_H + 4
      const height = Math.max(adH + tRows * ROW_H + 8, 44)
      return { person, blocks: [...allDay, ...timed], height, count: mine.length }
    })
    .filter((l) => l.count || !l.person.id.startsWith('_')),
)

// Перетаскивание. Недельный список и события на весь день — на другой день (куда отпустили);
// шкала времени (1–3 дня) — по горизонтали: время с шагом 15 минут и день.
function down(ev, b) {
  const e = b.e
  if (!canMove(e)) return
  const el = ev.currentTarget
  const r = eventRange(e)
  const dur = r.end - r.start
  const byDay = b.allDay || compact.value
  const sameDayEv = sameDay(r.start, new Date(+r.end - 1))
  if (!byDay && !sameDayEv) return   // через полночь — только через форму
  startDrag(ev, el, {
    onMove: (dx, dy) => { el.style.transform = byDay ? `translate(${dx}px, ${dy}px)` : `translateX(${dx}px)` },
    onEnd: async (dx, dy, up) => {
      let s = null
      let en = null
      if (byDay) {
        const iso = dayUnder(up.clientX, up.clientY)
        if (iso) {
          const [y, m, d] = iso.split('-').map(Number)
          const delta = Math.round((new Date(y, m - 1, d) - startOfDay(r.start)) / DAY)
          if (delta) { s = addDays(r.start, delta); en = addDays(r.end, delta) }
        }
      } else {
        const p = b.x - 1 + dx
        const idx = Math.min(days.value - 1, Math.max(0, Math.floor(p / dayW.value)))
        const mins = H0 * 60 + ((p - idx * dayW.value) / dayW.value) * (H1 - H0) * 60
        const snapped = Math.min(H1 * 60 - 15, Math.max(H0 * 60, Math.round(mins / 15) * 15))
        s = addDays(start.value, idx)
        s.setHours(0, snapped, 0, 0)
        if (+s === +r.start) s = null
        else en = new Date(+s + dur)
      }
      if (s) await moveEvent(e, s, en)
      el.style.transform = ''
    },
    onCancel: () => { el.style.transform = '' },
  })
}

// Раскладка пересекающихся блоков по строкам (жадно).
function pack(blocks) {
  blocks.sort((a, b) => a.x - b.x || b.w - a.w)
  const rowsEnd = []
  for (const b of blocks) {
    let r = rowsEnd.findIndex((endX) => endX <= b.x)
    if (r === -1) { r = rowsEnd.length; rowsEnd.push(0) }
    rowsEnd[r] = b.x + b.w + 2
    b.row = r
  }
  return rowsEnd.length
}

const nowX = computed(() => {
  if (compact.value) return null
  const i = Math.floor((startOfDay(now.value) - start.value) / DAY)
  if (i < 0 || i >= days.value) return null
  const h = now.value.getHours() + now.value.getMinutes() / 60
  if (h < H0 || h > H1) return null
  return xIn(now.value, i)
})
</script>

<style scoped>
.timeline { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.bar { display: flex; align-items: center; gap: 14px; padding: 12px 20px 4px; flex-wrap: wrap; }

.hint { font-size: 13px; }

.scroller { overflow-x: auto; padding: 8px 20px 24px; }
.grid { position: relative; }
.head { display: flex; position: sticky; top: 0; z-index: 3; background: var(--bg); }
.corner { width: var(--name); flex: none; }
.dayhead {
  flex: none; padding: 6px 8px 22px; position: relative; border-left: .5px solid var(--line);
  display: flex; align-items: center; gap: 8px; white-space: nowrap; overflow: hidden;
}
.dayhead.compact { padding-bottom: 8px; }
.dayhead strong { font-size: 14px; font-weight: 600; text-transform: lowercase; }
.dayhead.off strong { color: var(--ink-2); }
.dayhead.today strong { color: var(--red); }
.dn { display: inline-grid; place-items: center; min-width: 26px; height: 26px; border-radius: 50%; font-size: 16px; font-weight: 400; }
.dayhead.today .dn { background: var(--red); color: #fff; font-weight: 600; }
.dayhead { align-items: center; }
.hname { font-size: 12px; color: var(--holiday); overflow: hidden; text-overflow: ellipsis; }
.dayhead.short .hname { color: var(--ink-2); }
.hours { position: absolute; left: 0; right: 0; bottom: 3px; height: 16px; }
.hours span { position: absolute; transform: translateX(-50%); font-size: 11px; color: var(--ink-3); }
.hours span:first-child { transform: none; padding-left: 3px; }

.lane { display: flex; border-top: .5px solid var(--line); }
.lane:last-of-type { border-bottom: .5px solid var(--line); }
.who {
  width: var(--name); flex: none; display: flex; align-items: center; gap: 8px; padding: 8px 8px 8px 0;
  position: sticky; left: 0; z-index: 2; background: var(--bg); font-weight: 700;
}
.avatar {
  width: 32px; height: 32px; border-radius: 50%; flex: none; display: grid; place-items: center;
  background: var(--c); color: #fff; font-size: 17px;
}
.pname { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.track { position: relative; flex: 1; }
.cell { position: absolute; top: 0; bottom: 0; border-left: .5px solid var(--line); }
.cell.off { background: color-mix(in srgb, var(--surface-2) 60%, transparent); }
.cell.today { background: color-mix(in srgb, var(--red) 4%, transparent); }
.tick { position: absolute; top: 0; bottom: 0; border-left: 1px dashed color-mix(in srgb, var(--line) 70%, transparent); }

.block {
  position: absolute; border: 0; border-radius: 6px; padding: 0 6px; text-align: left;
  display: flex; align-items: center; gap: 6px; overflow: hidden; white-space: nowrap;
  background: color-mix(in srgb, var(--c) 18%, var(--surface)); color: color-mix(in srgb, var(--c) 62%, var(--ink));
  box-shadow: inset 3px 0 0 var(--c); font-size: 13px; line-height: 1;
}
.block:hover { background: color-mix(in srgb, var(--c) 28%, var(--surface)); z-index: 1; }
.block.allday { background: color-mix(in srgb, var(--c) 85%, var(--surface)); color: #fff; box-shadow: none; font-weight: 600; }
.block.esc-conflict { box-shadow: inset 3px 0 0 var(--c), inset 0 0 0 1.5px var(--red); }
.block.esc-unassigned { box-shadow: inset 3px 0 0 var(--c), inset 0 0 0 1.5px var(--warn); }
.block.past { opacity: .45; }
.block.duty-style { background: repeating-linear-gradient(-45deg, color-mix(in srgb, var(--c) 10%, var(--surface)) 0 5px, color-mix(in srgb, var(--c) 24%, var(--surface)) 5px 10px); }
.block.private { background: repeating-linear-gradient(135deg, color-mix(in srgb, var(--c) 12%, var(--surface)) 0 5px, color-mix(in srgb, var(--c) 24%, var(--surface)) 5px 10px); color: var(--ink-2); }
.block.multi::after { content: ''; position: absolute; right: 4px; top: 4px; width: 6px; height: 6px; border-radius: 50%; background: var(--ink-3); }
.bt { font-weight: 600; overflow: hidden; text-overflow: ellipsis; }
.bs { color: var(--ink-2); font-size: 12px; }

.nowline { position: absolute; top: 0; bottom: 0; width: 2px; background: var(--now); z-index: 2; pointer-events: none; }
.nowline::before { content: ''; position: absolute; top: 2px; left: -4px; width: 10px; height: 10px; border-radius: 50%; background: var(--now); }
.pad { padding: 16px 20px; }

@media (max-width: 760px) {
  .bar { padding: 10px 12px 2px; }
  .scroller { padding: 6px 12px 20px; }
}
.block.dragging { z-index: 6; box-shadow: 0 6px 18px rgba(0, 0, 0, .25); cursor: grabbing; }
</style>
