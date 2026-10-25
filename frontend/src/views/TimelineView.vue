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
            <strong>{{ d.label }}</strong>
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
            <div v-for="(d, i) in dayList" :key="i" class="cell" :class="{ today: d.today, off: d.off }"
                 :style="{ left: i * dayW + 'px', width: dayW + 'px' }">
              <i v-for="h in (compact ? [] : hourTicks)" :key="h" class="tick" :style="{ left: hx(h) + 'px' }"></i>
            </div>
            <button
              v-for="b in lane.blocks" :key="b.key"
              class="block" :class="{ allday: b.allDay, past: b.past, private: b.e.private, multi: b.e.people.length > 1 }"
              :style="{ left: b.x + 'px', width: b.w + 'px', top: b.y + 'px', height: (b.allDay ? ALLDAY_H : ROW_H) - 4 + 'px' }"
              :title="b.e.title"
              @click="openEvent(b.e)"
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
    return { date: d, today: sameDay(d, now.value), off, holiday, label: `${wd}, ${d.getDate()}` }
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
.seg { display: inline-flex; border: 1px solid var(--line); border-radius: var(--radius-m); overflow: hidden; }
.seg button { border: 0; background: var(--surface); padding: 6px 12px; color: var(--ink-2); }
.seg button + button { border-left: 1px solid var(--line); }
.seg button.on { background: var(--ink); color: var(--bg); }
.hint { font-size: 13px; }

.scroller { overflow-x: auto; padding: 8px 20px 24px; }
.grid { position: relative; }
.head { display: flex; position: sticky; top: 0; z-index: 3; background: var(--bg); }
.corner { width: var(--name); flex: none; }
.dayhead {
  flex: none; padding: 6px 8px 22px; position: relative; border-left: 1px solid var(--line);
  display: flex; align-items: baseline; gap: 8px; white-space: nowrap; overflow: hidden;
}
.dayhead.compact { padding-bottom: 8px; }
.dayhead strong { font-size: 16px; text-transform: capitalize; }
.dayhead.off strong { color: var(--holiday); }
.dayhead.today strong { background: var(--now); color: #fff; border-radius: 999px; padding: 1px 10px; }
.hname { font-size: 12px; color: var(--holiday); overflow: hidden; text-overflow: ellipsis; }
.dayhead.short .hname { color: var(--ink-2); }
.hours { position: absolute; left: 0; right: 0; bottom: 3px; height: 16px; }
.hours span { position: absolute; transform: translateX(-50%); font-size: 11px; color: var(--ink-3); }
.hours span:first-child { transform: none; padding-left: 3px; }

.lane { display: flex; border-top: 1px solid var(--line); }
.lane:last-of-type { border-bottom: 1px solid var(--line); }
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
.cell { position: absolute; top: 0; bottom: 0; border-left: 1px solid var(--line); }
.cell.off { background: color-mix(in srgb, var(--holiday) 4%, transparent); }
.cell.today { background: color-mix(in srgb, var(--now) 5%, transparent); }
.tick { position: absolute; top: 0; bottom: 0; border-left: 1px dashed color-mix(in srgb, var(--line) 70%, transparent); }

.block {
  position: absolute; border: 0; border-radius: 6px; padding: 0 6px; text-align: left;
  display: flex; align-items: center; gap: 6px; overflow: hidden; white-space: nowrap;
  background: color-mix(in srgb, var(--c) 22%, var(--surface)); color: var(--ink);
  box-shadow: inset 3px 0 0 var(--c); font-size: 13px; line-height: 1;
}
.block:hover { background: color-mix(in srgb, var(--c) 34%, var(--surface)); z-index: 1; }
.block.allday { background: var(--c); color: #fff; box-shadow: none; font-weight: 600; }
.block.past { opacity: .45; }
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
</style>
