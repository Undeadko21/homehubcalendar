// Свайп влево/вправо по «Сегодня», «Неделе», «Ленте» и «Семье» — следующий/прошлый день (неделя, период).
// Содержимое едет за пальцем, после порога — переход с анимацией (View Transitions) и лёгкой вибрацией.
// Не мешает: прокрутке вверх-вниз, горизонтальной прокрутке широких сеток (пока им есть куда ехать),
// долгому нажатию (перетаскивание и создание событий), открытым листам.
import { haptic } from './haptic'

const THRESHOLD = 70
const LONG_PRESS = 380

function scrollsX(el, stop, dir) {
  for (let n = el; n && n !== stop; n = n.parentElement) {
    if (n.scrollWidth <= n.clientWidth + 1) continue
    const ox = getComputedStyle(n).overflowX
    if (ox !== 'auto' && ox !== 'scroll') continue
    if (dir < 0 && n.scrollLeft + n.clientWidth < n.scrollWidth - 1) return true   // палец влево — сетке есть куда ехать вправо
    if (dir > 0 && n.scrollLeft > 0) return true
  }
  return false
}

export function attachDaySwipe(el, { enabled, go }) {
  let x0 = 0, y0 = 0, t0 = 0, mode = null, dx = 0, target = null
  const reset = (animateBack) => {
    el.style.transition = animateBack ? 'transform .2s ease, opacity .2s ease' : ''
    el.style.transform = ''
    el.style.opacity = ''
    if (animateBack) setTimeout(() => { el.style.transition = '' }, 220)
  }
  const start = (e) => {
    mode = null; dx = 0
    if (!enabled() || e.touches.length !== 1 || document.querySelector('.backdrop, .dragging, .fc-event-dragging, .fc-event-resizing')) { mode = 'off'; return }
    target = e.target
    if (target.closest?.('input, textarea, select, .trip-chip, .fc-highlight, .no-swipe')) { mode = 'off'; return }
    x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; t0 = Date.now()
  }
  const move = (e) => {
    if (mode === 'off' || mode === 'v') return
    const t = e.touches[0]
    dx = t.clientX - x0
    const dy = t.clientY - y0
    if (!mode) {
      if (Math.abs(dx) < 12 && Math.abs(dy) < 12) return
      if (Date.now() - t0 > LONG_PRESS) { mode = 'off'; return }   // это долгое нажатие — перетаскивание/создание
      if (Math.abs(dx) > Math.abs(dy) * 1.5 && !scrollsX(target, el, dx)) mode = 'h'
      else { mode = 'v'; return }
    }
    el.style.transform = `translateX(${dx * 0.35}px)`
    el.style.opacity = String(1 - Math.min(Math.abs(dx) / 900, 0.25))
  }
  const end = () => {
    if (mode !== 'h') { mode = null; return }
    mode = null
    if (Math.abs(dx) >= THRESHOLD) {
      haptic('tap')
      reset(false)
      go(dx < 0 ? 1 : -1)
    } else reset(true)
  }
  el.addEventListener('touchstart', start, { passive: true })
  el.addEventListener('touchmove', move, { passive: true })
  el.addEventListener('touchend', end)
  el.addEventListener('touchcancel', () => { mode = null; reset(true) })
}
