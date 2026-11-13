import { describe, expect, it } from 'vitest'
import { eventIcon, titleWithIcon } from '../src/lib/icons'
import { state } from '../src/lib/store'

describe('значки событий', () => {
  it('узнаёт по словам названия и места', () => {
    expect(eventIcon({ title: 'Бассейн' })).toBe('🏊')
    expect(eventIcon({ title: 'Приём', location: 'Поликлиника №3' })).toBe('🩺')
    expect(eventIcon({ title: 'ДР Маши' })).toBe('🎂')
    expect(eventIcon({ title: 'Собрание в школе' })).toBe('📚')
    expect(eventIcon({ title: 'Тренировка в зале' })).toBe('🏋️')
  })
  it('короткие слова — только целиком (русские границы слов)', () => {
    expect(eventIcon({ title: 'Залог за квартиру' })).toBe('')
    expect(eventIcon({ title: 'Хоровод' })).toBe('')
    expect(eventIcon({ title: 'Хор' })).toBe('🎵')
    expect(eventIcon({ title: 'Садовод' })).toBe('')
    expect(eventIcon({ title: 'Тортик' })).toBe('')
    expect(eventIcon({ title: 'ТО машины' })).toBe('🚗')
  })
  it('приватные без значка, дни рождения всегда с тортом', () => {
    expect(eventIcon({ title: 'Бассейн', private: true })).toBe('')
    expect(eventIcon({ title: 'Оля', birthday: true })).toBe('🎂')
  })
  it('в названии значок появляется только при включённой настройке', () => {
    state.icons = false
    expect(titleWithIcon({ title: 'Бассейн' })).toBe('Бассейн')
    state.icons = true
    expect(titleWithIcon({ title: 'Бассейн' })).toBe('🏊 Бассейн')
    expect(titleWithIcon({ title: 'Что-то' })).toBe('Что-то')
    state.icons = false
  })
})
