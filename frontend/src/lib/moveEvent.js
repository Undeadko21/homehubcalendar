// Перенос события (перетаскиванием в любом виде): общая логика отправки на сервер.
import { state, reload, writableCalendars } from './store'
import { api } from './api'
import { isoDate, isoLocal, addDays } from './dates'
import { problems } from './report'

export function writableCal(e) {
  return (e.calendars || []).find((k) => writableCalendars().some((c) => c.key === k))
}

// Двигать можно события в календарях Яндекса; приватные, поездки и дни рождения — нет.
export const canMove = (e) => !!e && !e.private && !e.duty && !e.birthday && !!writableCal(e)

async function send(e, cal, start, end, scope) {
  const body = { calendar: cal, all_day: !!e.all_day }
  if (e.all_day) {
    end = end || addDays(start, 1)
    Object.assign(body, { start: isoDate(start) + 'T00:00:00', end: isoDate(end) + 'T00:00:00' })
  } else {
    end = end || new Date(start.getTime() + 3600_000)
    Object.assign(body, { start: isoLocal(start), end: isoLocal(end) })
  }
  if (e.recurring) { body.occurrence = e.start; body.scope = scope }
  await api.updateEvent(e.uid, body)
}

/** true — перенесено; 'ask' — у повторяющегося спросим «только это / вся серия»; false — ошибка. */
export async function moveEvent(e, start, end) {
  const cal = writableCal(e)
  if (!cal) return false
  if (e.recurring) {
    state.moveAsk = { e, cal, start, end, label: start.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' }) }
    return 'ask'
  }
  try {
    await send(e, cal, start, end)
    await reload()
    return true
  } catch (err) {
    problems.list.push('Не удалось перенести событие: ' + err.message)
    return false
  }
}

export async function confirmMove(scope) {
  const a = state.moveAsk
  if (!a) return
  try {
    await send(a.e, a.cal, a.start, a.end, scope)
    state.moveAsk = null
    await reload()
  } catch (err) {
    problems.list.push('Не удалось перенести событие: ' + err.message)
    state.moveAsk = null
  }
}
