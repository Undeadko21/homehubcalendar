// Горячие клавиши на компьютере. По физическим клавишам (event.code) — работают и в русской раскладке.
// Не мешают вводу текста, сочетаниям с Ctrl/Cmd/Alt и открытым листам (там — только Esc, его обрабатывает лист).
export const KEYS = [
  { keys: 'T', text: 'Сегодня' },
  { keys: '← →', text: 'Предыдущий / следующий день (неделя, месяц)' },
  { keys: 'N', text: 'Новое событие' },
  { keys: '/', text: 'Поиск' },
  { keys: '1 … 6', text: 'Сегодня, Лента, Неделя, Семья, Месяц, Список' },
  { keys: 'F', text: 'Свободное время' },
  { keys: 'L', text: 'Списки' },
  { keys: 'S', text: 'Настройки' },
  { keys: '?', text: 'Эта подсказка' },
]

const VIEWS = ['today', 'timeline', 'week', 'family', 'month', 'agenda']

export function attachHotkeys({ enabled, today, shift, newEvent, setView, help }) {
  const onKey = (e) => {
    if (!enabled() || e.ctrlKey || e.metaKey || e.altKey || e.repeat) return
    const t = e.target
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return
    if (document.querySelector('.backdrop')) return
    const c = e.code
    let done = true
    if (c === 'KeyT') today()
    else if (c === 'ArrowLeft') shift(-1)
    else if (c === 'ArrowRight') shift(1)
    else if (c === 'KeyN') newEvent()
    else if (c === 'Slash' && e.shiftKey) help()                 // «?» (Shift + /)
    else if (c === 'Slash') setView('search')   // «/» (по коду клавиши — и в русской раскладке, где там «.»)
    else if (/^Digit[1-6]$/.test(c)) setView(VIEWS[+c.slice(5) - 1])
    else if (c === 'KeyF') setView('free')
    else if (c === 'KeyL') setView('lists')
    else if (c === 'KeyS') setView('settings')
    else done = false
    if (done) e.preventDefault()
  }
  window.addEventListener('keydown', onKey)
  return () => window.removeEventListener('keydown', onKey)
}
