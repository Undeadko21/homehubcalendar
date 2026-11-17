import { describe, it, expect } from 'vitest'
import { onColor } from '../src/lib/contrast'
import { tripIssue } from '../src/lib/trip'

describe('onColor — текст на насыщенной плашке', () => {
  it('на светлых цветах тёмный, на тёмных белый', () => {
    expect(onColor('#ffcc00')).toBe('#1d1d1f')
    expect(onColor('#34c759')).toBe('#1d1d1f')
    expect(onColor('#007aff')).toBe('#fff')
    expect(onColor('#5856d6')).toBe('#fff')
  })
  it('непонятный цвет — белый, как было', () => {
    expect(onColor('')).toBe('#fff')
    expect(onColor('red')).toBe('#fff')
  })
})

describe('tripIssue — значок 🚗', () => {
  const now = new Date('2026-11-17T12:00:00')
  const ev = (o) => ({ start: '2026-11-17T15:00:00', end: '2026-11-17T16:00:00', all_day: false, escort: { mode: 'escort' }, escort_issue: 'unassigned', ...o })
  it('показывается у будущего события ребёнка без водителя', () => expect(tripIssue(ev(), now)).toBe(true))
  it('не показывается у прошедшего', () => expect(tripIssue(ev({ start: '2026-11-17T08:00:00', end: '2026-11-17T09:00:00' }), now)).toBe(false))
  it('не показывается, если всё назначено, «дома» или это сама поездка', () => {
    expect(tripIssue(ev({ escort_issue: null }), now)).toBe(false)
    expect(tripIssue(ev({ escort: { mode: 'home' } }), now)).toBe(false)
    expect(tripIssue(ev({ duty: { role: 'pickup' } }), now)).toBe(false)
  })
})

describe('newEventAt — форма на протянутый отрезок', () => {
  it('кладёт начало, конец и человека; весь день — флагом', async () => {
    const { state, newEventAt } = await import('../src/lib/store')
    const a = new Date('2026-11-18T18:30:00'), b = new Date('2026-11-18T20:00:00')
    newEventAt(a, b, ['mama'])
    expect(state.editor).toEqual({ date: a, end: b, people: ['mama'] })
    newEventAt(a, b, null, true)
    expect(state.editor).toEqual({ date: a, end: b, allDay: true })
    state.editor = null
  })
})
