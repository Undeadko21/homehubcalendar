// Значок 🚗 на плашке события ребёнка: «?» — никто не назначен отвезти/забрать, «!» — назначенный занят.
import { eventRange } from './dates'

export const tripIssue = (e, now = new Date()) =>
  !!(e?.escort && e.escort.mode === 'escort' && e.escort_issue && !e.duty && eventRange(e).end > now)
export const chipLabel = (e) =>
  e?.escort_issue === 'conflict' ? 'Тот, кто везёт, в это время занят — выбрать другого' : 'Не выбрано, кто отвозит или забирает — выбрать'

const SEEN = 'homecal.tripChipHint'
// Один раз объясняем значок при первом показе.
export function chipHintOnce(toast) {
  if (document.querySelector('.backdrop')) return   // открыт лист — подскажем в другой раз
  if (typeof document !== 'undefined' && new URLSearchParams(location.search).has('kiosk')) return   // экран на стене — без подсказок
  try {
    if (localStorage.getItem(SEEN)) return
    localStorage.setItem(SEEN, '1')
  } catch { return }
  toast('🚗? — не выбрано, кто везёт. Нажмите на значок, чтобы выбрать.')
}
