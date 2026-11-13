import { beforeEach, describe, expect, it } from 'vitest'
import { state, driverFixes, personMark, undoOf, toast, hideToast, finishOnboarding } from '../src/lib/store'
import { NEWS, NEWS_LATEST, unseenNews, markNewsSeen } from '../src/lib/news'

const people = [
  { id: 'mama', name: 'Мама', color: '#f00' }, { id: 'papa', name: 'Папа', color: '#00f' },
  { id: 'masha', name: 'Маша', color: '#0f0' }, { id: 'mark', name: 'Марк', color: '#ff0' },
]
beforeEach(() => { state.config = { people, calendars: [] } })

const trip = (dropoff, pickup, extra = {}) => ({ uid: 'u', title: 'Танцы', escort: { mode: 'escort', dropoff, pickup }, ...extra })
const role = (person, free, conflicts = []) => ({ person, free, conflicts, skip: false })

describe('замена водителя', () => {
  it('никто не назначен — предлагает первого свободного', () => {
    const f = driverFixes(trip(role(null, ['papa', 'mama']), role(null, ['mama'])))
    expect(f.map((x) => [x.role, x.person, x.label])).toEqual([['dropoff', 'papa', 'Назначить: Папа'], ['pickup', 'mama', 'Назначить: Мама']])
  })
  it('назначенный занят — замена на свободного, но не на него же', () => {
    const f = driverFixes(trip(role('papa', ['papa', 'mama'], [{ title: 'Работа' }]), role('mama', [])))
    expect(f).toHaveLength(1)
    expect(f[0]).toMatchObject({ role: 'dropoff', person: 'mama', label: 'Заменить на Мама' })
  })
  it('всё в порядке, «не нужно», «вместе» — без предложений', () => {
    expect(driverFixes(trip(role('papa', ['mama']), role('mama', [])))).toEqual([])
    expect(driverFixes(trip({ ...role(null, ['papa']), skip: true }, { ...role(null, ['papa']), skip: true }))).toEqual([])
    expect(driverFixes({ escort: { mode: 'together' } })).toEqual([])
    expect(driverFixes({})).toEqual([])
  })
  it('некого предложить — молчит', () => {
    expect(driverFixes(trip(role(null, []), role('mama', ['mama'], [{}])))).toEqual([])
  })
  it('у повторяющегося события уточняет, что только на этот день', () => {
    expect(driverFixes(trip(role(null, ['papa']), role('mama', []), { recurring: true }))[0].done).toContain('только в этот день')
  })
})

describe('буквы людей', () => {
  it('одна буква, а при совпадении первой — две', () => {
    expect(personMark.value).toEqual({ mama: 'Ма', papa: 'П', masha: 'Ма', mark: 'Ма' })
  })
})

describe('отмена и плашка', () => {
  it('undoOf пуст без номеров журнала', () => {
    expect(undoOf([])).toBeNull()
    expect(undoOf(undefined)).toBeNull()
    expect(typeof undoOf(['a'])).toBe('function')
  })
  it('плашка показывает текст и кнопку отмены', () => {
    toast('Перенесено', () => {})
    expect(state.toast.text).toBe('Перенесено')
    expect(typeof state.toast.undo).toBe('function')
    hideToast()
    expect(state.toast).toBeNull()
  })
})

describe('что нового', () => {
  it('номера идут по убыванию без повторов', () => {
    const ns = NEWS.map((x) => x.n)
    expect(ns).toEqual([...ns].sort((a, b) => b - a))
    expect(new Set(ns).size).toBe(ns.length)
    expect(NEWS_LATEST).toBe(ns[0])
  })
  it('во время знакомства точки нет, после него — все записи считаются новыми', () => {
    state.onboarded = false; state.newsSeen = 0
    expect(unseenNews.value).toBe(0)
    finishOnboarding()
    expect(unseenNews.value).toBe(NEWS.length)
  })
  it('давнему устройству показывает непрочитанное и гасит после открытия', () => {
    state.onboarded = true; state.newsSeen = NEWS_LATEST - 3; state.newsSeenAtOpen = null
    expect(unseenNews.value).toBe(3)
    markNewsSeen()
    expect(unseenNews.value).toBe(0)
    expect(state.newsSeen).toBe(NEWS_LATEST)
  })
})
