<template>
  <Sheet :open="state.wizard" label="Мастер секции" @close="close">
    <form v-if="state.wizard" class="wiz" @submit.prevent="save">
      <div class="head">
        <button type="button" class="btn" :disabled="busy" @click="close">Отмена</button>
        <h2>Секция или кружок</h2>
        <button type="submit" class="btn filled" :disabled="busy || !ready">{{ busy ? '…' : 'Создать' }}</button>
      </div>

      <div class="group">
        <div class="row"><input v-model="f.title" class="in" placeholder="Название (например, Ушу)" autocomplete="off" required /></div>
        <div class="row"><input v-model="f.location" class="in" placeholder="Место" autocomplete="off" /></div>
      </div>

      <div class="group">
        <div class="row stack">
          <span class="label">Кто занимается</span>
          <PeoplePicker v-model="f.people" label="Кто занимается" :disabled="busy" />
        </div>
      </div>

      <div class="group">
        <div class="row stack">
          <span class="label">Дни недели</span>
          <div class="days" role="group" aria-label="Дни недели">
            <button v-for="d in DAYS" :key="d.n" type="button" class="day" :class="{ on: has(d.n) }"
                    :aria-pressed="has(d.n)" @click="toggleDay(d.n)">{{ d.s }}</button>
          </div>
        </div>
      </div>

      <div v-for="r in f.rows" :key="r.day" class="group">
        <div class="row between"><b>{{ DAYS[r.day].l }}</b>
          <span class="dt"><input v-model="r.start" type="time" required @change="shiftEnd(r)" /> – <input v-model="r.end" type="time" required /></span></div>
        <div v-if="kids" class="row between"><label>Отвезти</label>
          <select v-model="r.dropoff"><option value="">Не назначать</option><option value="-">Не нужно</option>
            <option v-for="a in adults" :key="a.id" :value="a.id">{{ a.name }}</option></select></div>
        <div v-if="kids" class="row between"><label>Забрать</label>
          <select v-model="r.pickup"><option value="">Не назначать</option><option value="-">Не нужно</option>
            <option v-for="a in adults" :key="a.id" :value="a.id">{{ a.name }}</option></select></div>
        <div v-if="kids" class="row between"><label>В пути, мин</label>
          <input v-model.number="r.travel" type="number" min="0" max="240" step="5" class="num" placeholder="как в настройках" /></div>
        <p v-for="(w, i) in warns[r.day] || []" :key="i" class="warn small">{{ w }}</p>
      </div>

      <div class="group">
        <div class="row between"><label for="w-from">Начиная с</label><input id="w-from" v-model="f.from" type="date" required /></div>
        <div class="row between"><label for="w-until">До (включительно)</label><input id="w-until" v-model="f.until" type="date" /></div>
        <div class="row between">
          <label for="w-cal">Календарь</label>
          <select id="w-cal" v-model="f.calendar"><option v-for="c in cals" :key="c.key" :value="c.key">{{ c.name }}</option></select>
        </div>
      </div>
      <p class="faint small">Дни с одинаковым временем и водителями станут одной повторяющейся серией, остальные — отдельными.
        Если «до» не указано, занятия повторяются без конца (удалить серию можно в карточке события).</p>

      <p v-if="error" class="warn">{{ error }}</p>
      <p v-if="done" class="faint">{{ done }}</p>
    </form>
  </Sheet>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { state, reload, writableCalendars } from '../lib/store'
import { api } from '../lib/api'
import { isoDate } from '../lib/dates'
import PeoplePicker from './PeoplePicker.vue'
import Sheet from './Sheet.vue'

const DAYS = [['пн', 'Понедельник'], ['вт', 'Вторник'], ['ср', 'Среда'], ['чт', 'Четверг'], ['пт', 'Пятница'], ['сб', 'Суббота'], ['вс', 'Воскресенье']]
  .map(([s, l], n) => ({ n, s, l }))
const busy = ref(false)
const error = ref('')
const done = ref('')
const warns = ref({})
const cals = computed(() => writableCalendars())
const people = computed(() => (state.config?.people || []).filter((p) => !p.id.startsWith('_')))
const adults = computed(() => people.value.filter((p) => !p.needs_escort))
const kids = computed(() => f.people.some((id) => people.value.find((p) => p.id === id)?.needs_escort))
const f = reactive({ title: '', location: '', people: [], rows: [], from: '', until: '', calendar: '' })
const ready = computed(() => f.title.trim() && f.rows.length && f.from && f.calendar)
const has = (n) => f.rows.some((r) => r.day === n)

watch(() => state.wizard, (v) => {
  if (!v) return
  error.value = ''; done.value = ''; warns.value = {}
  Object.assign(f, { title: '', location: '', people: [], rows: [], from: isoDate(new Date()), until: '' })
  f.calendar = cals.value[0]?.key || ''
})

function toggleDay(n) {
  if (has(n)) { f.rows = f.rows.filter((r) => r.day !== n); return }
  const last = f.rows[f.rows.length - 1]
  f.rows = [...f.rows, { day: n, start: last?.start || '17:00', end: last?.end || '18:00', dropoff: last?.dropoff || '',
    pickup: last?.pickup || '', travel: last?.travel || null }].sort((a, b) => a.day - b.day)
}
function shiftEnd(r) { if (r.end <= r.start) { const [h, m] = r.start.split(':').map(Number); r.end = `${String((h + 1) % 24).padStart(2, '0')}:${String(m).padStart(2, '0')}` } }

// Предупреждения о конфликтах по первому занятию каждого дня.
let t = 0
watch(() => JSON.stringify([f.rows, f.people, f.from, f.calendar, f.title]), () => {
  clearTimeout(t)
  t = setTimeout(async () => {
    const out = {}
    for (const r of f.rows) {
      try {
        const d0 = new Date(`${f.from}T00:00`)
        d0.setDate(d0.getDate() + ((r.day - ((d0.getDay() + 6) % 7)) + 7) % 7)
        const day = isoDate(d0)
        const res = await api.conflicts({ calendar: f.calendar, title: f.title, start: `${day}T${r.start}:00`, end: `${day}T${r.end}:00`,
          all_day: false, location: f.location, people: f.people.length ? f.people : null })
        const w = (res.items || []).filter((x) => x.level === 'warn').map((x) => x.text)
        if (w.length) out[r.day] = w
      } catch { /* подсказка */ }
    }
    warns.value = out
  }, 500)
})

function close() { state.wizard = false }

async function save() {
  error.value = ''
  busy.value = true
  try {
    await api.createSection({
      calendar: f.calendar, title: f.title.trim(), location: f.location, people: f.people.length ? f.people : null,
      from_date: f.from, until: f.until || null,
      rows: f.rows.map((x) => ({ day: x.day, start: x.start, end: x.end, dropoff: x.dropoff || null, pickup: x.pickup || null,
        travel: x.travel || null })),
    })
    state.wizard = false
    reload()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin: 6px 0 12px; }
.head h2 { margin: 0; font-size: 17px; font-weight: 600; }
.group { margin-bottom: 12px; }
.between { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.in { width: 100%; border: 0; background: transparent; font: inherit; color: var(--ink); padding: 4px 0; outline: none; }
.days { display: flex; gap: 6px; flex-wrap: wrap; }
.day { border: 1px solid var(--line); background: var(--surface); color: var(--ink-2); border-radius: 999px; min-width: 44px; padding: 8px 10px; font: inherit; }
.day.on { background: var(--red, #ff3b30); border-color: transparent; color: #fff; font-weight: 600; }
input[type=time], input[type=date], input.num, select { font: inherit; color: var(--ink); background: var(--fill, rgba(120,120,128,.12)); border: 0; border-radius: 8px; padding: 5px 8px; }
input.num { width: 120px; text-align: right; }
.warn { color: var(--red, #ff3b30); font-size: 14px; margin: 2px 0 6px; }
.small { font-size: 13px; }
</style>
