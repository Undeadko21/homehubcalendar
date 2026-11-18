<template>
  <div class="cal" :class="[mode, { narrow: screen.narrow, dense: dense }]">
    <div v-if="mode === 'week'" class="wbar">
      <div class="seg" role="group" aria-label="Сколько дней показывать">
        <button v-for="n in [3, 5, 7]" :key="n" :class="{ on: days === n }" @click="setWeekDays(n)">{{ n === 7 ? 'Неделя' : n + ' дня' }}</button>
      </div>
      <div v-if="!screen.narrow" class="seg" role="group" aria-label="Плотность">
        <button :class="{ on: dense }" @click="setDense(true)">Плотно</button>
        <button :class="{ on: !dense }" @click="setDense(false)">Просторно</button>
      </div>
    </div>
    <FullCalendar ref="fc" :options="options" />
  </div>
</template>

<script setup>
import { titleWithIcon } from '../lib/icons'
import { computed, ref, watch } from 'vue'
import FullCalendar from '@fullcalendar/vue3'
import dayGridPlugin from '@fullcalendar/daygrid'
import timeGridPlugin from '@fullcalendar/timegrid'
import interactionPlugin from '@fullcalendar/interaction'
import ruLocale from '@fullcalendar/core/locales/ru'
import { state, openEvent, openDriverPick, newEventAt, eventColor, personMark, screen, weekDays, setWeekDays, setView, setTimelineDays, savePrefs, toast } from '../lib/store'
import { tripIssue, chipLabel, chipHintOnce } from '../lib/trip'
import { onColor } from '../lib/contrast'
import { icoSvg } from '../lib/ico'
import { canMove, moveEvent } from '../lib/moveEvent'
import { useRange } from '../lib/useRange'
import { addDays, startOfDay, startOfWeek, startOfMonth, isoDate } from '../lib/dates'

const props = defineProps({ mode: { type: String, default: 'week' } })
const fc = ref(null)
const days = computed(() => weekDays())
const dotsMonth = computed(() => props.mode === 'month' && screen.narrow)   // на телефоне месяц — числа с точками
const viewName = computed(() => (props.mode === 'month' ? 'dayGridMonth' : days.value === 7 ? 'timeGridWeek' : `timeGrid${days.value}`))

// Диапазон, который загружаем: для месяца — с запасом на соседние недели в сетке.
const range = () => {
  if (props.mode === 'month') {
    const s = startOfWeek(startOfMonth(state.cursor))
    return { start: s, end: addDays(s, 42) }
  }
  if (days.value !== 7) {
    const s = startOfDay(state.cursor)
    return { start: s, end: addDays(s, days.value) }
  }
  const s = startOfWeek(state.cursor)
  return { start: s, end: addDays(s, 7) }
}
const { events, holidayMap } = useRange(range)

// Плотная неделя на компьютере: час ниже, короткие события в одну строку — рабочий день целиком без прокрутки.
const dense = computed(() => props.mode === 'week' && !screen.narrow && state.weekDense)
function setDense(v) { state.weekDense = v; savePrefs() }

async function moved(info) {
  const e = info.event.extendedProps.src
  if (info.event.allDay !== !!e.all_day || !info.event.start) { info.revert(); return }
  const r = await moveEvent(e, info.event.start, info.event.end)
  if (r !== true) info.revert()   // повторяющееся: пока человек не выбрал, событие остаётся на месте
}

// Буквы людей перед названием (настройка «Буквы на плашках»).
const marksText = (e) => { const m = e.people.map((id) => personMark.value[id]).filter(Boolean).join('·'); return m ? m + ' ' : '' }

const fcEvents = computed(() =>
  events.value.map((e) => {
    const c = eventColor(e)
    return {
      id: e.id,
      title: (state.initials ? marksText(e) : '') + titleWithIcon(e) + (e.people.length > 1 && !state.initials ? ` (${e.people.length})` : ''),
      start: e.start,
      end: e.end,
      allDay: e.all_day,
      backgroundColor: e.all_day ? `color-mix(in srgb, ${c} 85%, var(--surface))` : `color-mix(in srgb, ${c} var(--ev-bg), var(--surface))`,
      borderColor: c,
      textColor: e.all_day ? onColor(c) : `color-mix(in srgb, ${c} var(--ev-mix), var(--ink))`,
      classNames: [e.people.length > 1 && !e.duty ? 'is-shared' : '', e.private ? 'is-private' : '', e.escort_issue ? 'esc-' + e.escort_issue : '', e.duty ? 'is-duty' : ''],
      editable: canMove(e),
      extendedProps: { src: e },
    }
  }),
)

// Месяц на телефоне: под числом цветные точки (до 6), по нажатию — день на шкале.
function dotsHtml(d) {
  const key = isoDate(d)
  const list = events.value.filter((e) => {
    const s = isoDate(new Date(e.start))
    const en = e.all_day ? isoDate(addDays(new Date(e.end), -1)) : isoDate(new Date(e.end))
    return key >= s && key <= (en < s ? s : en)
  })
  if (!list.length) return ''
  const dots = list.slice(0, 6).map((e) => `<i style="background:${eventColor(e)}"></i>`).join('')
  return `<span class="dots">${dots}${list.length > 6 ? `<b>+${list.length - 6}</b>` : ''}</span>`
}

const options = computed(() => {
  const dotsData = dotsMonth.value ? events.value : null   // зависимость: точки пересчитываются, когда пришли события
  void dotsData
  return {
  plugins: [dayGridPlugin, timeGridPlugin, interactionPlugin],
  editable: false,
  eventDrop: moved,
  eventResize: moved,
  snapDuration: '00:15:00',
  longPressDelay: 400,
  eventLongPressDelay: 400,
  locale: ruLocale,
  initialView: viewName.value,
  views: { timeGrid3: { type: 'timeGrid', duration: { days: 3 } }, timeGrid5: { type: 'timeGrid', duration: { days: 5 } } },
  initialDate: state.cursor,
  headerToolbar: false,
  height: 'auto',
  firstDay: 1,
  nowIndicator: true,
  slotMinTime: '06:00:00',
  slotMaxTime: '24:00:00',
  scrollTime: '08:00:00',
  allDayText: 'весь день',
  dayMaxEvents: 4,
  slotEventOverlap: false,
  eventShortHeight: dense.value ? 40 : 30,
  eventMinHeight: dense.value ? 16 : 20,
  eventTimeFormat: { hour: '2-digit', minute: '2-digit', hour12: false },
  // Шапка дня как в Календаре Apple: «пн 26», сегодня — число в красном круге
  dayHeaderContent: (arg) => {
    if (props.mode === 'month') return arg.date.toLocaleDateString('ru-RU', { weekday: 'short' })
    const wd = arg.date.toLocaleDateString('ru-RU', { weekday: 'short' })
    return { html: `<span class="wd">${wd}</span> <span class="dn">${arg.date.getDate()}</span>` }
  },
  ...(props.mode === 'month' ? { dayCellContent: (arg) => ({ html: `<span class="dn">${arg.date.getDate()}</span>${dotsMonth.value ? dotsHtml(arg.date) : ''}` }) } : {}),
  ...(dotsMonth.value ? { dateClick: (info) => { state.cursor = info.date; setTimelineDays(1); setView('timeline') } } : {}),
  displayEventEnd: false,
  // В неделе — как у Apple: сначала название, под ним время начала
  // Короткое (до 45 мин) — одна строка с многоточием; длинное — название в несколько строк с переносом по слогам, время ниже.
  eventContent: (arg) => {
    if (!arg.view.type.startsWith('timeGrid') || arg.event.allDay) return true
    const esc = (s) => s.replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[ch])
    const src = arg.event.extendedProps.src
    const chip = src && tripIssue(src) ? `<span class="trip-chip ${esc(String(src.escort_issue))}" role="button" title="${esc(chipLabel(src))}">${icoSvg('car')}${src.escort_issue === 'conflict' ? '!' : '?'}</span>` : ''
    const mins = arg.event.end ? (arg.event.end - arg.event.start) / 60000 : 60
    if (mins <= 45) return { html: `<div class="ev-t one">${chip}${esc(arg.event.title)}</div>` }
    const lines = Math.max(1, Math.min(4, Math.floor(mins / 30)))
    // значок — в строке времени, чтобы не закрывал название в узкой колонке
    return { html: `<div class="ev-t" style="-webkit-line-clamp:${lines}">${esc(arg.event.title)}</div><div class="ev-tm">${chip}${esc(arg.timeText)}</div>` }
  },
  events: dotsMonth.value ? [] : fcEvents.value,
  eventClick: (info) => {
    const src = info.event.extendedProps.src
    if (info.jsEvent?.target?.closest?.('.trip-chip')) openDriverPick(src)
    else openEvent(src)
  },
  // Протянуть по пустому месту (мышь — сразу, палец — после долгого нажатия) — новое событие на этот отрезок.
  selectable: !dotsMonth.value,
  selectMirror: true,
  selectMinDistance: 6,
  selectLongPressDelay: 450,
  unselectAuto: true,
  select: (info) => {
    info.view.calendar.unselect()
    if (info.allDay && props.mode !== 'month') return
    if (info.allDay) { newEventAt(info.start, info.end, null, true); return }
    newEventAt(info.start, info.end)
  },
  dayCellClassNames: (arg) => dayClasses(arg.date),
  dayHeaderClassNames: (arg) => dayClasses(arg.date),
  dayCellDidMount: (arg) => {
    const h = holidayMap.value[isoDate(arg.date)]
    if (h) arg.el.title = h.name
  },
}
})

function dayClasses(d) {
  const h = holidayMap.value[isoDate(d)]
  const weekend = d.getDay() === 0 || d.getDay() === 6
  if (h) return [`hd-${h.type}`]
  return weekend ? ['hd-weekend'] : []
}

watch(() => events.value.some((e) => tripIssue(e)), (v) => { if (v) chipHintOnce(toast) }, { immediate: true })

// Навигация из шапки приложения → переход в FullCalendar.
watch(() => [state.cursor, viewName.value], () => {
  const api = fc.value?.getApi()
  if (!api) return
  api.changeView(viewName.value, props.mode === 'month' || !screen.narrow ? state.cursor : startOfDay(state.cursor))
})
</script>

<style>
/* FullCalendar рисует вне scoped-стилей — оформляем под Календарь Apple. */
.cal { padding: 0 0 28px; }
.cal .fc {
  --fc-border-color: var(--line);
  --fc-page-bg-color: var(--bg);
  --fc-neutral-bg-color: var(--surface-2);
  --fc-today-bg-color: transparent;
  --fc-now-indicator-color: var(--red);
  --fc-event-border-color: transparent;
  --fc-small-font-size: 12px;
  font-size: 13px;
}
.cal .fc .fc-scrollgrid { border-left: 0; border-right: 0; }
.cal .fc th { border-left-color: transparent; border-right-color: transparent; }
.cal .fc-col-header-cell { padding: 6px 0; font-weight: 400; }
.cal .fc-col-header-cell-cushion { color: var(--ink); text-decoration: none; text-transform: lowercase; font-size: 13px; }
.cal .fc-col-header-cell-cushion .dn { font-size: 20px; font-weight: 400; display: inline-grid; place-items: center; min-width: 32px; height: 32px; border-radius: 50%; margin-left: 2px; }
.cal .fc-day-today .fc-col-header-cell-cushion .dn { background: var(--red); color: #fff; font-weight: 600; }
.cal .fc-day-today .fc-col-header-cell-cushion .wd { color: var(--red); }
.cal th.hd-weekend .fc-col-header-cell-cushion, .cal th.hd-holiday .fc-col-header-cell-cushion, .cal th.hd-dayoff .fc-col-header-cell-cushion { color: var(--ink-2); }

/* месяц на телефоне: числа с точками */
.cal.month.narrow .fc-daygrid-day-frame { min-height: 62px; cursor: pointer; }
.cal.month.narrow .fc-daygrid-day-top { flex-direction: column; align-items: center; width: 100%; }
.cal.month.narrow .fc-daygrid-day-number { display: flex; flex-direction: column; align-items: center; width: 100%; padding: 4px 0 0; }
.cal .fc .dots { display: flex; flex-wrap: wrap; justify-content: center; gap: 3px; margin-top: 4px; padding: 0 4px; }
.cal .fc .dots i { width: 7px; height: 7px; border-radius: 50%; display: block; }
.cal .fc .dots b { font-size: 10px; font-weight: 600; color: var(--ink-2); line-height: 7px; }
.wbar { padding: 4px 16px 8px; }
.cal .fc-event.is-shared { outline: 1.5px solid var(--ink-3); outline-offset: -1.5px; }

/* неделя */
.cal .fc-timegrid-slot { height: 2.6em; }
.cal.dense .fc-timegrid-slot { height: 1.45em; }
.cal.dense .fc-timegrid-event .fc-event-main { padding: 0 4px; font-size: 12px; line-height: 1.25; }
.cal.dense .fc-timegrid-event-short .fc-event-time::after { content: '\00a0'; }
.cal.dense .fc-timegrid-event-short .fc-event-main-frame { flex-direction: row; gap: 4px; white-space: nowrap; overflow: hidden; }
.cal.dense .fc-timegrid-event-short .fc-event-title { overflow: hidden; text-overflow: ellipsis; }
.cal.dense .fc-timegrid-slot-label-cushion { font-size: 10px; }
.wbar { display: flex; gap: 10px; flex-wrap: wrap; }
.cal .fc-timegrid-slot-minor { border-top-style: none; }
.cal .fc-timegrid-slot-label-cushion, .cal .fc-timegrid-axis-cushion { color: var(--ink-2); font-size: 11px; }
.cal .fc-timegrid-axis-cushion { text-transform: lowercase; }
.cal .fc-timegrid-event { border: 0 !important; border-left: 3px solid var(--fc-event-border-color) !important; border-radius: 4px; box-shadow: none; }
.cal .fc-timegrid-event .fc-event-main { padding: 2px 4px; }
.cal .fc-timegrid-event .fc-event-title { font-weight: 600; }
.cal .fc-timegrid-event .fc-event-time { font-size: 11px; opacity: .85; }
.cal .fc-timegrid-col.fc-day-today { background: transparent; }
.cal .fc-timegrid-now-indicator-line { border-width: 1px 0 0; }
.cal .fc-timegrid-now-indicator-arrow { border: 0; width: 9px; height: 9px; border-radius: 50%; background: var(--red); margin-top: -4.5px; left: auto; right: -4px; }
.cal td.hd-holiday, .cal td.hd-dayoff, .cal td.hd-weekend { background: color-mix(in srgb, var(--surface-2) 55%, transparent); }

/* месяц */
.cal .fc-daygrid-day-top { flex-direction: row; justify-content: flex-end; }
.cal .fc-daygrid-day-number { color: var(--ink); text-decoration: none; padding: 4px 6px; }
.cal .fc-daygrid-day-number .dn { display: inline-grid; place-items: center; min-width: 26px; height: 26px; border-radius: 50%; font-size: 14px; }
.cal .fc-day-today .fc-daygrid-day-number .dn { background: var(--red); color: #fff; font-weight: 600; }
.cal .fc-day-other .fc-daygrid-day-number { color: var(--ink-3); }
.cal .fc-dayGridMonth-view .hd-holiday .dn, .cal .fc-dayGridMonth-view .hd-dayoff .dn { color: var(--red); }
.cal .fc-dayGridMonth-view .fc-day-today.hd-holiday .dn { color: #fff; }
.cal .fc-daygrid-day-frame { min-height: 96px; }
.cal .fc-daygrid-dot-event { border-radius: 4px; padding: 1px 2px; }
.cal .fc-daygrid-dot-event .fc-event-title { font-weight: 500; color: var(--ink); }
.cal .fc-daygrid-dot-event .fc-event-time { color: var(--ink-2); font-weight: 400; }
.cal .fc-daygrid-dot-event:hover { background: var(--fill); }
.cal .fc-daygrid-block-event { border-radius: 4px; border: 0; padding: 0 3px; font-weight: 600; }
.cal .fc-daygrid-more-link { color: var(--ink-2); font-weight: 500; }
.cal .fc-popover { background: var(--surface); border: 0; border-radius: 12px; box-shadow: var(--shadow-pop); }
.cal .fc-popover-header { background: transparent; font-weight: 600; }

.cal .fc-event { cursor: pointer; }
.cal .is-duty { background-image: repeating-linear-gradient(-45deg, transparent 0 5px, rgba(127,127,127,.16) 5px 10px); }
.cal .is-private { background-image: repeating-linear-gradient(135deg, transparent 0 5px, rgba(127,127,127,.14) 5px 10px); }
.cal .ev-t {
  font-weight: 600; line-height: 1.2; overflow: hidden; text-overflow: ellipsis;
  display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2;
  hyphens: auto; -webkit-hyphens: auto; overflow-wrap: normal; word-break: normal;
}
/* совсем узкая плашка (пересечения на компьютере): по буквам не ломаем — одна строка с многоточием */
.cal .fc-timegrid-event .fc-event-main { container-type: inline-size; }
@container (max-width: 40px) { .cal .ev-t { -webkit-line-clamp: 1 !important; overflow-wrap: normal; } }
.cal .ev-t.one { display: block; white-space: nowrap; }
.cal .fc-timegrid-event .fc-event-main { position: relative; }
.cal .trip-chip {
  display: inline-flex; align-items: center; margin-right: 4px; padding: 0 5px; border-radius: 999px; font-size: 11px; font-weight: 700; line-height: 16px;
  background: var(--warn); color: #fff; cursor: pointer; vertical-align: 1px; position: relative;
}
.cal .trip-chip .i { font-size: 13px; stroke-width: 2.1 !important; }
.cal .trip-chip::after { content: ''; position: absolute; inset: -10px -6px; }
.cal .trip-chip.conflict { background: var(--red); }
.cal .ev-tm { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cal .fc-daygrid-block-event .fc-event-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block; }
.cal .fc-highlight { background: color-mix(in srgb, var(--tint) 18%, transparent); }
.cal .ev-tm { font-size: 11px; opacity: .8; }
.cal .fc-daygrid-dot-event.esc-conflict .fc-event-title::after { content: ' !'; color: var(--red); font-weight: 800; }
@media (max-width: 899px) {
  .cal .fc { font-size: 11px; }
  .cal .fc-col-header-cell-cushion { font-size: 11px; display: flex; flex-direction: column; align-items: center; }
  .cal .fc-col-header-cell-cushion .dn { font-size: 16px; min-width: 28px; height: 28px; margin: 0; }
  .cal .fc-daygrid-day-frame { min-height: 64px; }
  .cal .fc-daygrid-day-top { justify-content: center; }
  .cal .fc-daygrid-dot-event .fc-event-time { display: none; }
}
</style>
