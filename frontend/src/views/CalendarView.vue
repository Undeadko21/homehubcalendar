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
import { state, openEvent, eventColor } from '../lib/store'
import { useRange } from '../lib/useRange'
import { addDays, startOfWeek, startOfMonth, isoDate } from '../lib/dates'

const props = defineProps({ mode: { type: String, default: 'week' } })
const fc = ref(null)

// Диапазон, который загружаем: для месяца — с запасом на соседние недели в сетке.
const range = () => {
  if (props.mode === 'month') {
    const s = startOfWeek(startOfMonth(state.cursor))
    return { start: s, end: addDays(s, 42) }
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
      backgroundColor: e.all_day ? c : `color-mix(in srgb, ${c} 20%, var(--surface))`,
      borderColor: c,
      textColor: e.all_day ? '#fff' : 'var(--ink)',
      classNames: [e.private ? 'is-private' : ''],
      extendedProps: { src: e },
    }
  }),
)

const options = computed(() => ({
  plugins: [dayGridPlugin, timeGridPlugin],
  locale: ruLocale,
  initialView: props.mode === 'month' ? 'dayGridMonth' : 'timeGridWeek',
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
watch(() => [state.cursor, props.mode], () => {
  const api = fc.value?.getApi()
  if (!api) return
  api.changeView(props.mode === 'month' ? 'dayGridMonth' : 'timeGridWeek', state.cursor)
})
</script>

<style>
/* FullCalendar рендерит вне scoped-стилей — правим через переменные. */
.cal { padding: 12px 20px 28px; }
.cal .fc {
  --fc-border-color: var(--line);
  --fc-page-bg-color: var(--surface);
  --fc-neutral-bg-color: var(--surface-2);
  --fc-today-bg-color: color-mix(in srgb, var(--now) 6%, transparent);
  --fc-now-indicator-color: var(--now);
  --fc-event-border-color: transparent;
  font-size: 14px;
  background: var(--surface);
  border-radius: var(--radius-l);
  box-shadow: var(--shadow);
  overflow: hidden;
}
.cal .fc .fc-scrollgrid { border: 0; }
.cal .fc-col-header-cell-cushion, .cal .fc-daygrid-day-number { color: var(--ink); text-decoration: none; font-weight: 600; }
.cal .fc-col-header-cell-cushion { text-transform: capitalize; padding: 8px 4px; }
.cal .hd-weekend .fc-daygrid-day-number, .cal .hd-holiday .fc-daygrid-day-number, .cal .hd-dayoff .fc-daygrid-day-number,
.cal th.hd-weekend .fc-col-header-cell-cushion, .cal th.hd-holiday .fc-col-header-cell-cushion, .cal th.hd-dayoff .fc-col-header-cell-cushion { color: var(--holiday); }
.cal td.hd-holiday, .cal td.hd-dayoff { background: color-mix(in srgb, var(--holiday) 5%, transparent); }
.cal .fc-day-today .fc-daygrid-day-number { background: var(--now); color: #fff; border-radius: 999px; padding: 2px 8px; margin: 3px; }
.cal .fc-timegrid-event, .cal .fc-daygrid-block-event { border-left: 3px solid var(--fc-event-border-color) !important; border-radius: 6px; }
.cal .fc-timegrid-event .fc-event-main { color: var(--ink); padding: 2px 4px; }
.cal .fc-daygrid-dot-event { border-radius: 6px; }
.cal .fc-daygrid-dot-event .fc-event-title { font-weight: 600; }
.cal .fc-daygrid-dot-event:hover { background: var(--surface-2); }
.cal .fc-event { cursor: pointer; }
.cal .fc-timegrid-slot-label-cushion, .cal .fc-timegrid-axis-cushion { color: var(--ink-3); font-size: 12px; }
.cal .is-private { background-image: repeating-linear-gradient(135deg, transparent 0 5px, rgba(127,127,127,.12) 5px 10px); }
.cal .fc-popover { background: var(--surface); }
@media (max-width: 760px) {
  .cal { padding: 8px 6px 20px; }
  .cal .fc { font-size: 12px; }
}
</style>
