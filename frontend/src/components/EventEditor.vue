<template>
  <Sheet :open="!!ed" :label="isNew ? 'Новое событие' : 'Изменить событие'" @close="close">
    <form v-if="ed" class="editor" @submit.prevent="save">
      <div class="head">
        <button type="button" class="btn" :disabled="busy" @click="close">Отмена</button>
        <h2>{{ isNew ? 'Новое событие' : 'Событие' }}</h2>
        <button type="submit" class="btn filled" :disabled="busy || !f.title.trim()">{{ busy ? '…' : 'Сохранить' }}</button>
      </div>

      <div v-if="isNew" class="group">
        <div class="row between">
          <input v-model="quick" class="in" placeholder="Быстро: «Йога завтра в 18:30 у Оли»" autocomplete="off"
                 @keydown.enter.prevent="fillQuick" />
          <button type="button" class="btn link" :disabled="busy || !quick.trim()" @click="fillQuick">Разобрать</button>
        </div>
        <p v-if="quickNote" class="faint small qn">{{ quickNote }}</p>
      </div>

      <div class="group">
        <div class="row"><input v-model="f.title" class="in" placeholder="Название" autocomplete="off" required /></div>
        <div class="row"><input v-model="f.location" class="in" placeholder="Место" autocomplete="off" /></div>
      </div>

      <div class="group">
        <div class="row between">
          <label for="ee-all">Весь день</label>
          <input id="ee-all" v-model="f.allDay" type="checkbox" class="chk" />
        </div>
        <div class="row between">
          <label for="ee-sd">Начало</label>
          <span class="dt">
            <input id="ee-sd" v-model="f.startDate" type="date" required @change="syncEnd" />
            <input v-if="!f.allDay" v-model="f.startTime" type="time" required @change="syncEnd" />
          </span>
        </div>
        <div class="row between">
          <label for="ee-ed">Конец</label>
          <span class="dt">
            <input id="ee-ed" v-model="f.endDate" type="date" required />
            <input v-if="!f.allDay" v-model="f.endTime" type="time" required />
          </span>
        </div>
        <div class="row between">
          <label for="ee-rep">Повтор</label>
          <select id="ee-rep" v-model="f.repeat">
            <option v-if="!isNew && ed.event?.recurring" value="keep">Как есть</option>
            <option value="">Не повторять</option>
            <option value="daily">Каждый день</option>
            <option value="weekly">Каждую неделю</option>
            <option value="monthly">Каждый месяц</option>
            <option value="yearly">Каждый год</option>
          </select>
        </div>
        <div v-if="f.repeat && f.repeat !== 'keep'" class="row between">
          <label for="ee-until">Повторять до</label>
          <input id="ee-until" v-model="f.until" type="date" />
        </div>
        <div class="row between">
          <label for="ee-cal">Календарь</label>
          <select id="ee-cal" v-model="f.calendar" :disabled="!isNew">
            <option v-for="c in cals" :key="c.key" :value="c.key">{{ c.name }}</option>
          </select>
        </div>
      </div>
      <p v-if="!isNew && ed.event?.recurring" class="faint small">
        Это повторяющееся событие: изменения времени и названия применятся ко всей серии.
      </p>

      <div v-if="warns.length" class="group warns">
        <div v-for="(x, i) in warns" :key="i" class="row wrow" :class="x.level">
          <span class="wdot"></span><span>{{ x.text }}</span>
        </div>
      </div>

      <div class="group">
        <div class="row stack">
          <span class="label">Чьё событие</span>
          <PeoplePicker v-model="f.people" label="Чьё событие" :disabled="busy" />
          <p class="faint small">Ничего не выбрано — по владельцам календаря и словам в названии.</p>
        </div>
      </div>

      <div class="group">
        <div class="row stack"><textarea v-model="f.description" class="in" rows="3" placeholder="Заметки"></textarea></div>
      </div>

      <p v-if="error" class="conflict">{{ error }}</p>

      <div v-if="!isNew" class="group">
        <div v-if="!confirmDel" class="row">
          <button type="button" class="btn danger" :disabled="busy" @click="confirmDel = true">Удалить…</button>
        </div>
        <div v-else class="row stack">
          <span class="label">Удалить из Яндекс.Календаря?</span>
          <div class="actions">
            <button v-if="ed.event.recurring" type="button" class="btn danger" :disabled="busy" @click="remove(true)">Только это</button>
            <button type="button" class="btn danger" :disabled="busy" @click="remove(false)">
              {{ ed.event.recurring ? 'Всю серию' : 'Удалить' }}
            </button>
            <button type="button" class="btn gray" :disabled="busy" @click="confirmDel = false">Нет</button>
          </div>
        </div>
      </div>
    </form>
  </Sheet>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { state, reload, writableCalendars } from '../lib/store'
import { api } from '../lib/api'
import { eventRange, isoDate, isoLocal, addDays } from '../lib/dates'
import PeoplePicker from './PeoplePicker.vue'
import Sheet from './Sheet.vue'

const ed = computed(() => state.editor)
const isNew = computed(() => !ed.value?.event)
const cals = computed(() => writableCalendars())
const busy = ref(false)
const error = ref('')
const confirmDel = ref(false)
const quick = ref('')
const quickNote = ref('')
const f = reactive({ title: '', location: '', description: '', allDay: false, startDate: '', startTime: '', endDate: '',
  endTime: '', repeat: '', until: '', calendar: '', people: [] })
let origPeople = []
const warns = ref([])

// Проверка конфликтов по мере ввода (с паузой, чтобы не спрашивать сервер на каждую цифру).
let wt = 0
let wseq = 0
watch(() => [ed.value, f.startDate, f.startTime, f.endDate, f.endTime, f.allDay, f.calendar, f.title, JSON.stringify(f.people)], () => {
  clearTimeout(wt)
  warns.value = []
  if (!ed.value || f.allDay || !f.calendar || !f.startDate || !f.startTime || !f.endTime) return
  wt = setTimeout(async () => {
    const p = payload()
    if (new Date(p.end) <= new Date(p.start)) return
    const my = ++wseq
    try {
      const r = await api.conflicts({ calendar: f.calendar, title: f.title, start: p.start, end: p.end, all_day: false,
        location: f.location, people: f.people.length ? f.people : null, uid: ed.value.event?.uid || null })
      if (my === wseq) warns.value = r.items || []
    } catch { /* предупреждения — подсказка, не обязательное условие */ }
  }, 450)
})

const pad = (n) => String(n).padStart(2, '0')
const hm = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`
const LS = 'homecal.lastCalendar'

watch(ed, (v) => {
  error.value = ''
  confirmDel.value = false
  quick.value = ''
  quickNote.value = ''
  if (!v) return
  if (v.event) {
    const e = v.event
    const r = eventRange(e)
    Object.assign(f, { title: e.title, location: e.location || '', description: e.description || '', allDay: !!e.all_day,
      repeat: e.recurring ? 'keep' : '', until: '' })
    f.startDate = isoDate(r.start)
    f.endDate = isoDate(e.all_day ? addDays(r.end, -1) : r.end)
    f.startTime = e.all_day ? '09:00' : hm(r.start)
    f.endTime = e.all_day ? '10:00' : hm(r.end)
    const w = cals.value.map((c) => c.key)
    f.calendar = (e.calendars || []).find((k) => w.includes(k)) || w[0] || ''
    f.people = e.people_override ? (e.people || []).filter((id) => !id.startsWith('_')) : []
  } else {
    const d = new Date(v.date || new Date())
    const now = new Date()
    const h = d.toDateString() === now.toDateString() ? Math.min(now.getHours() + 1, 22) : 10
    Object.assign(f, { title: '', location: '', description: '', allDay: false, repeat: '', until: '', people: [] })
    f.startDate = isoDate(d); f.endDate = isoDate(d)
    f.startTime = `${pad(h)}:00`; f.endTime = `${pad(h + 1)}:00`
    let last = ''
    try { last = localStorage.getItem(LS) || '' } catch {}
    const w = cals.value.map((c) => c.key)
    f.calendar = w.includes(last) ? last : w[0] || ''
  }
  origPeople = [...f.people]
})

// Сдвигаем конец вместе с началом, чтобы длительность не терялась.
let prev = null
watch(() => [f.startDate, f.startTime], ([d, t], old) => {
  if (!old || !old[0]) return
  const a = new Date(`${old[0]}T${old[1] || '00:00'}`)
  const b = new Date(`${f.endDate}T${f.endTime || '00:00'}`)
  const n = new Date(`${d}T${t || '00:00'}`)
  if (isNaN(a) || isNaN(b) || isNaN(n)) return
  const e = new Date(n.getTime() + (b - a))
  f.endDate = isoDate(e); f.endTime = hm(e)
})
function syncEnd() {}

function close() { state.editor = null }

async function fillQuick() {
  if (!quick.value.trim()) return
  quickNote.value = ''
  try {
    const r = await api.quick(quick.value)
    f.title = r.title || f.title
    f.allDay = r.all_day
    f.startDate = r.date; f.endDate = r.date
    if (!r.all_day) { f.startTime = r.start; f.endTime = r.end }
    f.repeat = r.repeat?.freq || ''
    if (r.people.length) f.people = r.people
    quickNote.value = 'Проверьте поля ниже и нажмите «Сохранить»' + (r.notes.length ? ' · ' + r.notes.join(', ') : '')
  } catch (err) {
    quickNote.value = 'Не удалось разобрать: ' + err.message
  }
}

function payload() {
  const sd = f.allDay ? `${f.startDate}T00:00:00` : `${f.startDate}T${f.startTime}:00`
  let ed_ = f.endDate
  if (f.allDay) ed_ = isoDate(addDays(new Date(`${f.endDate}T00:00`), 1)) // исключающий конец
  const end = f.allDay ? `${ed_}T00:00:00` : `${f.endDate}T${f.endTime}:00`
  return { start: sd, end, all_day: f.allDay }
}

async function save() {
  error.value = ''
  const p = payload()
  if (!f.allDay && new Date(p.end) <= new Date(p.start)) { error.value = 'Конец должен быть позже начала'; return }
  if (f.allDay && f.endDate < f.startDate) { error.value = 'Конец раньше начала'; return }
  busy.value = true
  try {
    const repeat = f.repeat && f.repeat !== 'keep' ? { freq: f.repeat, until: f.until || null } : null
    if (isNew.value) {
      await api.createEvent({ calendar: f.calendar, title: f.title.trim(), ...p, location: f.location,
        description: f.description, repeat, people: f.people.length ? f.people : null })
      try { localStorage.setItem(LS, f.calendar) } catch {}
    } else {
      const e = ed.value.event
      const body = { calendar: f.calendar, title: f.title.trim(), ...p, location: f.location, description: f.description }
      if (e.recurring) body.occurrence = e.start
      if (f.repeat !== 'keep') { body.repeat_set = true; body.repeat = repeat }
      if (JSON.stringify(f.people) !== JSON.stringify(origPeople)) { body.people_set = true; body.people = f.people.length ? f.people : null }
      await api.updateEvent(e.uid, body)
    }
    state.editor = null
    reload()
  } catch (err) {
    error.value = err.message
  } finally {
    busy.value = false
  }
}

async function remove(onlyThis) {
  busy.value = true
  error.value = ''
  try {
    const e = ed.value.event
    await api.deleteEvent(e.uid, f.calendar, onlyThis ? e.start : null)
    state.editor = null
    reload()
  } catch (err) {
    error.value = err.message
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
.in { width: 100%; border: 0; background: transparent; font: inherit; color: var(--ink); padding: 4px 0; outline: none; resize: vertical; }
.dt { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.dt input, select { font: inherit; color: var(--ink); background: var(--fill, rgba(120,120,128,.12)); border: 0; border-radius: 8px; padding: 5px 8px; }
.chk { width: 22px; height: 22px; accent-color: var(--red, #ff3b30); }
.actions { display: flex; gap: 8px; flex-wrap: wrap; }
.danger { color: var(--red, #ff3b30); }
.warns .wrow { display: flex; gap: 10px; align-items: flex-start; font-size: 14px; }
.wdot { width: 8px; height: 8px; border-radius: 50%; flex: none; margin-top: 6px; background: var(--red, #ff3b30); }
.wrow.info .wdot { background: var(--orange, #ff9500); }
.wrow.info { color: var(--muted, #8a8a8e); }
.conflict { color: var(--red, #ff3b30); font-size: 14px; }
.small { font-size: 13px; }
</style>
