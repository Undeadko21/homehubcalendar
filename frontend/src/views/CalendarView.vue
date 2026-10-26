<template>
  <div class="cal" :class="mode">
    <FullCalendar ref="fc" :options="options" />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import FullCalendar from '@fullcalendar/vue3'
import dayGridPlugin from '@fullcalendar/daygrid'
import timeGridPlugin from '@fullcalendar/timegrid'
import ruLocale from '@fullcalendar/core/locales/ru'
import { state, openEvent, eventColor, screen } from '../lib/store'
import { useRange } from '../lib/useRange'
import { addDays, startOfDay, startOfWeek, startOfMonth, isoDate } from '../lib/dates'

const props = defineProps({ mode: { type: String, default: 'week' } })
const fc = ref(null)
const viewName = computed(() => (props.mode === 'month' ? 'dayGridMonth' : screen.narrow ? 'timeGrid3' : 'timeGridWeek'))

// Диапазон, который загружаем: для месяца — с запасом на соседние недели в сетке.
const range = () => {
  if (props.mode === 'month') {
    const s = startOfWeek(startOfMonth(state.cursor))
    return { start: s, end: addDays(s, 42) }
  }
  if (screen.narrow) {
    const s = startOfDay(state.cursor)
    return { start: s, end: addDays(s, 3) }
  }
  const s = startOfWeek(state.cursor)
  return { start: s, end: addDays(s, 7) }
}
const { events, holidayMap } = useRange(range)

const fcEvents = computed(() =>
  events.value.map((e) => {
    const c = eventColor(e)
    return {
      id: e.id,
      title: e.title + (e.people.length > 1 ? ` (${e.people.length})` : ''),
      start: e.start,
      end: e.end,
      allDay: e.all_day,
      backgroundColor: e.all_day ? `color-mix(in srgb, ${c} 85%, var(--surface))` : `color-mix(in srgb, ${c} 18%, var(--surface))`,
      borderColor: c,
      textColor: e.all_day ? '#fff' : `color-mix(in srgb, ${c} 62%, var(--ink))`,
      classNames: [e.private ? 'is-private' : '', e.escort_issue ? 'esc-' + e.escort_issue : ''],
      extendedProps: { src: e },
    }
  }),
)

const options = computed(() => ({
  plugins: [dayGridPlugin, timeGridPlugin],
  locale: ruLocale,
  initialView: viewName.value,
  views: { timeGrid3: { type: 'timeGrid', duration: { days: 3 } } },
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
  eventTimeFormat: { hour: '2-digit', minute: '2-digit', hour12: false },
  // Шапка дня как в Календаре Apple: «пн 26», сегодня — число в красном круге
  dayHeaderContent: (arg) => {
    if (props.mode === 'month') return arg.date.toLocaleDateString('ru-RU', { weekday: 'short' })
    const wd = arg.date.toLocaleDateString('ru-RU', { weekday: 'short' })
    return { html: `<span class="wd">${wd}</span> <span class="dn">${arg.date.getDate()}</span>` }
  },
  ...(props.mode === 'month' ? { dayCellContent: (arg) => ({ html: `<span class="dn">${arg.date.getDate()}</span>` }) } : {}),
  displayEventEnd: false,
  // В неделе — как у Apple: сначала название, под ним время начала
  eventContent: (arg) => {
    if (!arg.view.type.startsWith('timeGrid') || arg.event.allDay) return true
    const esc = (s) => s.replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[ch])
    return { html: `<div class="ev-t">${esc(arg.event.title)}</div><div class="ev-tm">${esc(arg.timeText)}</div>` }
  },
  events: fcEvents.value,
  eventClick: (info) => openEvent(info.event.extendedProps.src),
  dayCellClassNames: (arg) => dayClasses(arg.date),
  dayHeaderClassNames: (arg) => dayClasses(arg.date),
  dayCellDidMount: (arg) => {
    const h = holidayMap.value[isoDate(arg.date)]
    if (h) arg.el.title = h.name
  },
}))

function dayClasses(d) {
  const h = holidayMap.value[isoDate(d)]
  const weekend = d.getDay() === 0 || d.getDay() === 6
  if (h) return [`hd-${h.type}`]
  return weekend ? ['hd-weekend'] : []
}

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

/* неделя */
.cal .fc-timegrid-slot { height: 2.6em; }
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
.cal .is-private { background-image: repeating-linear-gradient(135deg, transparent 0 5px, rgba(127,127,127,.14) 5px 10px); }
.cal .fc-timegrid-event.esc-conflict { box-shadow: inset 0 0 0 1.5px var(--red) !important; }
.cal .fc-timegrid-event.esc-unassigned { box-shadow: inset 0 0 0 1.5px var(--warn) !important; }
.cal .ev-t { font-weight: 600; line-height: 1.2; overflow: hidden; }
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
