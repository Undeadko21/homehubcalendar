import { describe, expect, it, vi } from 'vitest'
import { vSwipe } from '../src/lib/swipe'

function row(handlers) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  vSwipe.mounted(el, { value: handlers })
  return el
}
const touch = (el, type, x, y) => {
  const e = new Event(type, { bubbles: true, cancelable: true })
  e.touches = type === 'touchend' ? [] : [{ clientX: x, clientY: y }]
  el.dispatchEvent(e)
}
function drag(el, dx, dy = 0) {
  touch(el, 'touchstart', 100, 100)
  touch(el, 'touchmove', 100 + dx / 2, 100 + dy / 2)
  touch(el, 'touchmove', 100 + dx, 100 + dy)
  touch(el, 'touchend')
}

describe('свайп по строке', () => {
  it('длинный свайп вправо и влево вызывает своё действие', () => {
    const right = vi.fn(), left = vi.fn()
    const el = row({ right, left })
    drag(el, 120)
    expect(right).toHaveBeenCalledTimes(1)
    drag(el, -120)
    expect(left).toHaveBeenCalledTimes(1)
  })
  it('короткий свайп ничего не делает', () => {
    const right = vi.fn()
    drag(row({ right }), 40)
    expect(right).not.toHaveBeenCalled()
  })
  it('вертикальная прокрутка не считается свайпом', () => {
    const right = vi.fn()
    drag(row({ right }), 90, 200)
    expect(right).not.toHaveBeenCalled()
  })
  it('направление без обработчика не срабатывает', () => {
    const left = vi.fn()
    const el = row({ left })
    drag(el, 150)
    expect(left).not.toHaveBeenCalled()
  })
  it('обработчики можно сменить на лету (updated)', () => {
    const a = vi.fn(), b = vi.fn()
    const el = row({ right: a })
    vSwipe.updated(el, { value: { right: b } })
    drag(el, 120)
    expect(a).not.toHaveBeenCalled()
    expect(b).toHaveBeenCalledTimes(1)
  })
})
