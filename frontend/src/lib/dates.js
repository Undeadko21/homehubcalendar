// Работа с датами. Всё считаем в часовом поясе браузера: устройство дома
// стоит в том же поясе, что и семья. Сервер отдаёт время уже с поясом.

export const DAY = 86400000

export function startOfDay(d) {
  const x = new Date(d)
  x.setHours(0, 0, 0, 0)
  return x
}

export function addDays(d, n) {
  const x = new Date(d)
  x.setDate(x.getDate() + n)
  return x
}

export function startOfWeek(d) {
  const x = startOfDay(d)
  const wd = (x.getDay() + 6) % 7 // понедельник = 0
  return addDays(x, -wd)
}

export function startOfMonth(d) {
  return new Date(d.getFullYear(), d.getMonth(), 1)
}

export function isoDate(d) {
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

export function isoLocal(d) {
  const p = (n) => String(n).padStart(2, '0')
  return `${isoDate(d)}T${p(d.getHours())}:${p(d.getMinutes())}:00`
}

export function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

// Событие → интервалы Date. Для событий на весь день конец исключающий.
export function eventRange(e) {
  if (e.all_day) {
    const [y, m, d] = e.start.split('-').map(Number)
    const [y2, m2, d2] = e.end.split('-').map(Number)
    return { start: new Date(y, m - 1, d), end: new Date(y2, m2 - 1, d2) }
  }
  return { start: new Date(e.start), end: new Date(e.end) }
}

export function overlaps(e, from, to) {
  const r = eventRange(e)
  return r.start < to && (r.end > from || (+r.end === +r.start && r.start >= from))
}

const fmt = (opts) => new Intl.DateTimeFormat('ru-RU', opts)
const fTime = fmt({ hour: '2-digit', minute: '2-digit' })
const fDayLong = fmt({ weekday: 'long', day: 'numeric', month: 'long' })
const fDayShort = fmt({ weekday: 'short', day: 'numeric' })
const fMonth = fmt({ month: 'long', year: 'numeric' })
const fDayMonth = fmt({ day: 'numeric', month: 'long' })
const fWeekday = fmt({ weekday: 'short' })

export const formatTime = (d) => fTime.format(d)
export const formatDayLong = (d) => cap(fDayLong.format(d))
export const formatDayShort = (d) => fDayShort.format(d)
export const formatMonth = (d) => cap(fMonth.format(d))
export const formatDayMonth = (d) => fDayMonth.format(d)
export const formatWeekday = (d) => fWeekday.format(d)

export function cap(s) {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

export function formatEventTime(e) {
  if (e.all_day) {
    const r = eventRange(e)
    const days = Math.round((r.end - r.start) / DAY)
    if (days <= 1) return 'Весь день'
    return `${formatDayMonth(r.start)} — ${formatDayMonth(addDays(r.end, -1))}`
  }
  const r = eventRange(e)
  if (sameDay(r.start, r.end) || +r.end === +startOfDay(addDays(r.start, 1))) {
    return `${formatTime(r.start)}–${formatTime(r.end)}`
  }
  return `${formatDayMonth(r.start)} ${formatTime(r.start)} — ${formatDayMonth(r.end)} ${formatTime(r.end)}`
}

export function relativeDayName(d, today = new Date()) {
  const diff = Math.round((startOfDay(d) - startOfDay(today)) / DAY)
  if (diff === 0) return 'Сегодня'
  if (diff === 1) return 'Завтра'
  if (diff === -1) return 'Вчера'
  return formatDayLong(d)
}
