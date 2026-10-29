// Перетаскивание блоков указателем (мышь — сразу, палец — после долгого нажатия, чтобы работала прокрутка).
// handlers: { onMove(dx, dy, ev), onEnd(dx, dy, ev) → Promise|void, onCancel() }
const LONG_PRESS = 420

export function startDrag(ev, el, handlers) {
  if (ev.pointerType === 'mouse' && ev.button !== 0) return
  const x0 = ev.clientX, y0 = ev.clientY
  const touch = ev.pointerType !== 'mouse'
  let active = false
  let timer = null
  const block = (e) => { if (active) e.preventDefault() }

  const begin = () => {
    active = true
    try { el.setPointerCapture(ev.pointerId) } catch {}
    el.classList.add('dragging')
    el.style.pointerEvents = 'none'
    window.addEventListener('touchmove', block, { passive: false })
  }
  const cleanup = () => {
    clearTimeout(timer)
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', up)
    window.removeEventListener('pointercancel', cancel)
    window.removeEventListener('touchmove', block)
    el.classList.remove('dragging')
    el.style.pointerEvents = ''
  }
  const move = (e) => {
    const dx = e.clientX - x0, dy = e.clientY - y0
    if (!active) {
      if (Math.hypot(dx, dy) < (touch ? 10 : 5)) return
      if (touch) { cleanup(); return }   // палец поехал до долгого нажатия — это прокрутка
      begin()
    }
    e.preventDefault()
    handlers.onMove(dx, dy, e)
  }
  const up = async (e) => {
    const was = active
    cleanup()
    if (!was) return
    // после перетаскивания не открываем карточку события
    const stop = (c) => { c.stopPropagation(); c.preventDefault() }
    window.addEventListener('click', stop, { capture: true, once: true })
    setTimeout(() => window.removeEventListener('click', stop, { capture: true }), 50)
    await handlers.onEnd(e.clientX - x0, e.clientY - y0, e)
  }
  const cancel = () => {
    const was = active
    cleanup()
    if (was) handlers.onCancel?.()
  }
  window.addEventListener('pointermove', move, { passive: false })
  window.addEventListener('pointerup', up)
  window.addEventListener('pointercancel', cancel)
  if (touch) timer = setTimeout(begin, LONG_PRESS)
}

/** День (data-day), над которым отпустили: ищем среди всех элементов под указателем, а не только верхний. */
export function dayUnder(x, y) {
  for (const el of document.elementsFromPoint(x, y)) {
    const d = el.closest?.('[data-day]')
    if (d) return d.getAttribute('data-day')
  }
  return null
}
