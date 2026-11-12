import { haptic } from './haptic'

// Свайп по строке списка пальцем: v-swipe="{ right: fn, left: fn }".
// Работает на касаниях (мышь не трогаем), вертикальная прокрутка остаётся; строка едет за пальцем и подсвечивается,
// когда отпускание уже сработает. Перетаскивание долгим нажатием (lib/drag.js) не мешает: оно отменяется при движении.
const THRESHOLD = 72

function attach(el, binding) {
  let x0 = 0, y0 = 0, dx = 0, mode = null   // mode: null — ещё не ясно, 'swipe', 'scroll'
  const opts = () => el._swipe || {}
  const reset = () => {
    el.style.transition = 'transform .18s'
    el.style.transform = ''
    el.classList.remove('swipe-go', 'swiping')
    setTimeout(() => { el.style.transition = '' }, 200)
  }
  const start = (e) => {
    if (e.touches.length !== 1) return
    x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; dx = 0; mode = null
  }
  const move = (e) => {
    if (mode === 'scroll' || e.touches.length !== 1) return
    dx = e.touches[0].clientX - x0
    const dy = e.touches[0].clientY - y0
    if (!mode) {
      if (Math.abs(dx) < 12 && Math.abs(dy) < 12) return
      const allowed = (dx > 0 && opts().right) || (dx < 0 && opts().left)
      mode = Math.abs(dx) > Math.abs(dy) * 1.5 && allowed ? 'swipe' : 'scroll'
      if (mode === 'swipe') el.classList.add('swiping')
    }
    if (mode !== 'swipe') return
    if ((dx > 0 && !opts().right) || (dx < 0 && !opts().left)) dx = 0
    if (e.cancelable) e.preventDefault()
    el.style.transform = `translateX(${dx}px)`
    const go = Math.abs(dx) >= THRESHOLD
    if (go && !el.classList.contains('swipe-go')) haptic('tap')
    el.classList.toggle('swipe-go', go)
  }
  const end = () => {
    if (mode !== 'swipe') { mode = null; return }
    mode = null
    const fn = Math.abs(dx) >= THRESHOLD ? (dx > 0 ? opts().right : opts().left) : null
    reset()
    if (fn) {
      // после свайпа не открываем карточку/не переключаем галочку обычным нажатием
      const stop = (c) => { c.stopPropagation(); c.preventDefault() }
      window.addEventListener('click', stop, { capture: true, once: true })
      setTimeout(() => window.removeEventListener('click', stop, { capture: true }), 80)
      fn()
    }
  }
  el.addEventListener('touchstart', start, { passive: true })
  el.addEventListener('touchmove', move, { passive: false })
  el.addEventListener('touchend', end)
  el.addEventListener('touchcancel', () => { mode = null; reset() })
  el.style.touchAction = 'pan-y'
}

export const vSwipe = {
  mounted(el, binding) { el._swipe = binding.value; attach(el, binding) },
  updated(el, binding) { el._swipe = binding.value },
}
