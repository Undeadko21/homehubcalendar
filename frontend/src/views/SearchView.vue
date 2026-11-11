<template>
  <div class="search">
    <form class="bar" @submit.prevent="run">
      <input ref="input" v-model="text" class="field" type="search" inputmode="search" enterkeyhint="search"
             placeholder="Название, место или описание" aria-label="Поиск по событиям" autocomplete="off" />
    </form>

    <div class="filters">
      <div class="chips" role="group" aria-label="Чьи события">
        <button v-for="p in persons" :key="p.id" class="chip" :class="{ on: who.includes(p.id) }" :style="{ '--c': p.color }"
                :aria-pressed="who.includes(p.id)" @click="togglePerson(p.id)">{{ p.emoji }} {{ p.name }}</button>
      </div>
      <div class="selects">
        <select v-model="period" class="sel" aria-label="Период">
          <option v-for="o in PERIODS" :key="o.id" :value="o.id">{{ o.label }}</option>
        </select>
        <template v-if="period === 'custom'">
          <input v-model="from" class="sel" type="date" aria-label="С" />
          <input v-model="to" class="sel" type="date" aria-label="По" />
        </template>
        <select v-if="calendars.length > 1" v-model="calendar" class="sel" aria-label="Календарь">
          <option value="">Все календари</option>
          <option v-for="c in calendars" :key="c.key" :value="c.key">{{ c.name }}</option>
        </select>
        <button v-if="filtered" class="btn link" @click="resetFilters">Сбросить</button>
      </div>
    </div>

    <p v-if="!active" class="hint">Введите слово или выберите человека, период или календарь. Без периода ищет за последние 2 месяца и на год вперёд.</p>
    <p v-else-if="loading && !results.length" class="hint">Ищу…</p>
    <p v-else-if="error" class="hint err">{{ error }}</p>
    <div v-else-if="!results.length" class="none">
      <strong>Ничего не найдено</strong>
      <span>{{ filtered ? 'Попробуйте убрать часть фильтров или расширить период.' : 'Проверьте написание или попробуйте другое слово.' }}</span>
      <button v-if="filtered" class="btn link" @click="resetFilters">Сбросить фильтры</button>
    </div>
    <template v-else>
      <p class="hint count">Найдено: {{ results.length }}{{ results.length >= 300 ? '+' : '' }}</p>
      <div class="group">
        <div v-for="e in results" :key="e.id" class="row res" :style="{ '--c': eventColor(e) }">
          <button class="open" @click="openEvent(e)">
            <span class="bar-c" aria-hidden="true"></span>
            <span class="body">
              <span class="t">{{ e.title }}</span>
              <span class="s">{{ when(e) }}<template v-if="e.location"> · {{ e.location }}</template></span>
              <span class="who">{{ e.people.map((p) => personById[p]?.name).filter(Boolean).join(', ') }}</span>
            </span>
          </button>
          <button class="btn sm day" :aria-label="'Показать день на ленте: ' + when(e)" @click="goToDay(eventRange(e).start)">К дню ›</button>
        </div>
        <p v-if="results.length >= 300" class="hint">Показаны первые 300 — уточните запрос.</p>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../lib/api'
import { state, openEvent, eventColor, personById, people, goToDay } from '../lib/store'
import { formatTime, eventRange, addDays, startOfWeek, startOfMonth, isoDate } from '../lib/dates'

const PERIODS = [
  { id: '', label: 'Любое время' },
  { id: 'future', label: 'Предстоящие' },
  { id: 'week', label: 'Эта неделя' },
  { id: 'month', label: 'Этот месяц' },
  { id: 'past', label: 'Прошедшие (год)' },
  { id: 'custom', label: 'Свой период…' },
]

// Фильтры переживают переход к событию и обратно.
let saved = {}
try { saved = JSON.parse(sessionStorage.getItem('homecal.search') || '{}') } catch { /* без хранилища */ }
const text = ref(saved.text || '')
const who = ref(saved.who || [])
const period = ref(saved.period || '')
const from = ref(saved.from || '')
const to = ref(saved.to || '')
const calendar = ref(saved.calendar || '')
const results = ref([])
const loading = ref(false)
const error = ref('')
const input = ref(null)
let timer, seq = 0

const persons = computed(() => people.value.filter((p) => !p.id.startsWith('_')))
const calendars = computed(() => (state.config?.calendars || []).filter((c) => !c.hidden))
const filtered = computed(() => who.value.length > 0 || !!period.value || !!calendar.value)
const active = computed(() => text.value.trim().length >= 2 || filtered.value)

function togglePerson(id) {
  who.value = who.value.includes(id) ? who.value.filter((x) => x !== id) : [...who.value, id]
}
function resetFilters() { who.value = []; period.value = ''; calendar.value = ''; from.value = ''; to.value = '' }

function range() {
  const today = new Date()
  switch (period.value) {
    case 'future': return { start: isoDate(today), end: isoDate(addDays(today, 365)) }
    case 'week': { const s = startOfWeek(today); return { start: isoDate(s), end: isoDate(addDays(s, 6)) } }
    case 'month': { const s = startOfMonth(today); return { start: isoDate(s), end: isoDate(new Date(s.getFullYear(), s.getMonth() + 1, 0)) } }
    case 'past': return { start: isoDate(addDays(today, -365)), end: isoDate(addDays(today, -1)) }
    case 'custom': return { ...(from.value ? { start: from.value } : {}), ...(to.value ? { end: to.value } : {}) }
    default: return {}
  }
}

async function run() {
  try {
    sessionStorage.setItem('homecal.search', JSON.stringify({ text: text.value, who: who.value, period: period.value, from: from.value, to: to.value, calendar: calendar.value }))
  } catch { /* без хранилища */ }
  if (!active.value) { results.value = []; return }
  const my = ++seq
  loading.value = true
  error.value = ''
  try {
    const params = { q: text.value.trim(), ...range() }
    if (who.value.length) params.people = who.value.join(',')
    if (calendar.value) params.calendar = calendar.value
    const r = await api.search(params)
    if (my === seq) results.value = period.value === 'past' ? [...r].reverse() : r
  } catch (e) {
    if (my === seq) error.value = 'Не удалось выполнить поиск: ' + e.message
  } finally {
    if (my === seq) loading.value = false
  }
}
watch(text, () => { clearTimeout(timer); timer = setTimeout(run, 300) })
watch([who, period, from, to, calendar, () => state.revision], run)
onMounted(() => { if (!text.value) input.value?.focus(); run() })

function when(e) {
  const d = eventRange(e).start
  const day = d.toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric', month: 'short', year: d.getFullYear() === new Date().getFullYear() ? undefined : 'numeric' })
  return e.all_day ? `${day}, весь день` : `${day}, ${formatTime(d)}`
}
</script>

<style scoped>
.search { padding: 12px 16px 32px; max-width: 760px; }
.field {
  width: 100%; box-sizing: border-box; font: inherit; font-size: 17px; padding: 10px 14px; border: 0;
  border-radius: 10px; background: var(--fill); color: var(--ink);
}
.filters { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  --c: #8e8e93; border: 0; border-radius: 999px; padding: 5px 12px; font: inherit; font-size: 14px; font-weight: 500;
  background: var(--surface); color: var(--ink); box-shadow: inset 0 0 0 1px var(--line);
}
.chip.on { background: var(--c); color: #fff; box-shadow: none; font-weight: 600; }
.selects { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.sel { font: inherit; font-size: 14px; padding: 6px 8px; border-radius: 8px; border: .5px solid var(--line); background: var(--surface); color: var(--ink); max-width: 100%; }
.hint { color: var(--ink-3); font-size: 14px; margin: 14px 4px; }
.hint.err { color: var(--red); }
.hint.count { margin-bottom: 0; }
.none { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; margin-top: 16px; padding: 16px; border-radius: var(--radius-m); background: var(--surface-2); }
.none strong { font-size: 17px; }
.none span { color: var(--ink-2); font-size: 14px; }
.res { padding: 0; align-items: stretch; gap: 0; }
.open { flex: 1; min-width: 0; display: flex; gap: 12px; align-items: stretch; border: 0; background: none; text-align: left; color: inherit; font: inherit; padding: 10px 8px 10px 16px; }
.open:hover { background: var(--fill); }
.day { flex: none; align-self: center; margin-right: 10px; color: var(--tint); font-weight: 600; white-space: nowrap; }
.bar-c { width: 4px; border-radius: 2px; background: var(--c); flex: none; }
.body { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.t { font-weight: 600; }
.s { font-size: 13px; color: var(--ink-2); }
.who { font-size: 12px; color: var(--ink-3); }
.group { margin-top: 8px; }
</style>
