<template>
  <Sheet :open="!!ed && !state.quickAdd" :label="isNew ? 'Новое событие' : 'Изменить событие'" :dismissible="!busy" @close="close">
    <form v-if="ed" class="editor" @submit.prevent="save">
      <div class="head">
        <button type="button" class="btn" :disabled="busy" @click="close">Отмена</button>
        <h2>{{ isNew ? 'Новое событие' : 'Событие' }}</h2>
        <button type="submit" class="btn filled" :disabled="busy || parsing || !f.title.trim()">{{ busy ? '…' : 'Сохранить' }}</button>
      </div>

      <div class="group fields">
        <div class="row"><input v-model="f.title" class="in title-in" aria-label="Название" placeholder="Название" autocomplete="off" required /></div>
        <div class="row"><input v-model="f.location" class="in" aria-label="Место" placeholder="Место" autocomplete="off" /></div>
      </div>

      <div v-if="isNew" class="phrase-group">
        <div class="phrase-row">
          <input v-model="phrase" class="phrase-input" aria-label="Добавить фразой" placeholder="Добавить фразой"
                 autocomplete="off" enterkeyhint="go" :disabled="busy || parsing" @keydown.enter.prevent="parsePhrase" />
          <MicButton :disabled="busy || parsing" @text="dictate" @error="phraseError = $event" />
          <button v-if="phrase.trim()" type="button" class="btn gray" :disabled="busy || parsing" @click="parsePhrase">
            {{ parsing ? '…' : 'Заполнить' }}
          </button>
        </div>
        <p v-if="phraseError" class="conflict" role="alert">{{ phraseError }}</p>
      </div>

      <div class="group fields">
        <div class="row between">
          <label for="ee-sd">{{ showEndDate ? 'Дата начала' : 'Дата' }}</label>
          <input id="ee-sd" v-model="f.startDate" type="date" required />
        </div>
        <div v-if="showEndDate" class="row between">
          <label for="ee-ed">Дата окончания</label>
          <input id="ee-ed" v-model="f.endDate" type="date" required />
        </div>
        <label class="row between all-day">
          <span>Весь день</span>
          <input id="ee-all" v-model="f.allDay" type="checkbox" class="chk" />
        </label>
        <div v-if="!f.allDay" class="row times">
          <label class="time-field">Начало<input v-model="f.startTime" type="time" required /></label>
          <label class="time-field">Конец<input v-model="f.endTime" type="time" required /></label>
        </div>
      </div>

      <div v-if="hasPeople" class="group fields">
        <div class="row stack">
          <span class="label">Кто участвует</span>
          <PeoplePicker v-model="f.people" label="Кто участвует" :disabled="busy" />
        </div>
      </div>

      <p v-if="parseNotes.length" class="hint" role="status">{{ parseNotes.join(' · ') }}</p>
      <p v-if="error" class="conflict" role="alert">{{ error }}</p>
      <div v-if="warns.length" class="group warns" role="status">
        <div v-for="(x, i) in warns" :key="i" class="row wrow" :class="x.level">
          <span class="wdot"></span><span>{{ x.text }}</span>
        </div>
      </div>

      <button type="button" class="more-btn" :aria-expanded="more" aria-controls="ee-more" @click="more = !more">
        <span>Подробнее</span>
        <small v-if="!more" class="hint">{{ moreSummary }}</small>
        <span class="chev" :class="{ open: more }" aria-hidden="true">›</span>
      </button>
      <div id="ee-more" v-show="more">
        <div v-if="!f.allDay" class="group fields">
          <div class="row stack" role="group" aria-label="Длительность">
            <span>Длительность</span>
            <div class="durs">
              <button v-for="m in DURS" :key="m" type="button" class="dur" :class="{ on: duration === m }"
                      :aria-pressed="duration === m" @click="setDuration(m)">{{ durLabel(m) }}</button>
            </div>
          </div>
        </div>
        <div class="group fields">
          <div class="row between">
            <label for="ee-rep">Повтор</label>
            <select id="ee-rep" v-model="f.repeat">
              <option v-if="!isNew && ed.event?.recurring" value="keep">Как есть</option>
              <option value="">Не повторять</option>
              <option value="daily">Каждый день</option>
              <option value="weekly">Каждую неделю</option>
              <option value="biweekly">Каждые 2 недели</option>
              <option value="monthly">Каждый месяц, {{ startDay }}-го</option>
              <option value="monthly_nth">Каждый месяц, {{ nthText }}</option>
              <option v-if="isLastWd" value="monthly_last">Каждый месяц, {{ lastText }}</option>
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
        <div class="group fields">
          <div class="row"><textarea v-model="f.description" class="in" rows="3" aria-label="Заметки" placeholder="Заметки"></textarea></div>
        </div>
        <div v-if="isNew" class="group fields">
          <div class="row"><button type="button" class="btn" :disabled="busy" @click="openWizard">Секция или кружок по дням недели…</button></div>
          <div class="row"><button type="button" class="btn" :disabled="busy || parsing" @click="state.quickAdd = true">Частые события, дела и покупки</button></div>
        </div>
      </div>
      <div v-if="!isNew && ed.event?.recurring" class="group">
        <div class="row between">
          <label for="ee-scope">Изменить</label>
          <select id="ee-scope" v-model="f.scope">
            <option value="series">Всю серию</option>
            <option value="following">Это и следующие</option>
            <option value="once">Только это</option>
          </select>
        </div>
      </div>

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
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { state, reload, writableCalendars } from '../lib/store'
import { api } from '../lib/api'
import { DAY, eventRange, isoDate, addDays } from '../lib/dates'
import MicButton from './MicButton.vue'
import PeoplePicker from './PeoplePicker.vue'
import Sheet from './Sheet.vue'

const ed = computed(() => state.editor)
const isNew = computed(() => !ed.value?.event)
const cals = computed(() => writableCalendars())
const hasPeople = computed(() => (state.config?.people || []).some((p) => !p.id.startsWith('_')))
const busy = ref(false)
const error = ref('')
const phrase = ref('')
const phraseError = ref('')
const parsing = ref(false)
const confirmDel = ref(false)
const parseNotes = ref([])
const f = reactive({ title: '', location: '', description: '', allDay: false, startDate: '', startTime: '', endDate: '',
  endTime: '', repeat: '', until: '', calendar: '', people: [], scope: 'series' })
let origPeople = []
const warns = ref([])
const more = ref(false)
const showEndDate = computed(() => !isNew.value || more.value || f.endDate !== f.startDate)
const DURS = [30, 60, 90, 120]
const durLabel = (m) => (m < 60 ? `${m} мин` : m % 60 ? `${Math.floor(m / 60)},5 ч` : `${m / 60} ч`)
const duration = computed(() => {
  const a = new Date(`${f.startDate}T${f.startTime || '00:00'}`), b = new Date(`${f.endDate}T${f.endTime || '00:00'}`)
  return isNaN(a) || isNaN(b) ? null : Math.round((b - a) / 60000)
})
function setDuration(m) {
  const a = new Date(`${f.startDate}T${f.startTime || '00:00'}`)
  if (isNaN(a)) return
  const e = new Date(a.getTime() + m * 60000)
  f.endDate = isoDate(e); f.endTime = hm(e)
}
// Показываем назначение события и явно заполненные настройки даже при свёрнутых подробностях.
const moreSummary = computed(() => {
  const parts = []
  const calendar = cals.value.find((c) => c.key === f.calendar)
  if (calendar) parts.push(calendar.name)
  if (f.repeat) parts.push('Повтор')
  if (f.description) parts.push('Заметки')
  return parts.join(' · ') || 'Календарь, повтор и заметки'
})

// Проверка конфликтов по мере ввода (с паузой, чтобы не спрашивать сервер на каждую цифру).
let wt = 0
let wseq = 0
watch(() => [ed.value, f.startDate, f.startTime, f.endDate, f.endTime, f.allDay, f.calendar, f.title, f.location, f.people], () => {
  const my = ++wseq
  clearTimeout(wt)
  warns.value = []
  if (!ed.value || f.allDay || !f.calendar || !f.startDate || !f.startTime || !f.endTime) return
  wt = setTimeout(async () => {
    const p = payload()
    if (new Date(p.end) <= new Date(p.start)) return
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

// Пока форма заполняется целиком (открытие, плашка из «+»), конец за началом не двигаем — он уже посчитан.
let filling = false
watch(ed, (v) => {
  filling = true
  nextTick(() => { filling = false })
  error.value = ''
  phrase.value = ''
  phraseError.value = ''
  parsing.value = false
  confirmDel.value = false
  parseNotes.value = []
  more.value = false
  if (!v) return
  if (v.event) {
    const e = v.event
    const r = eventRange(e)
    Object.assign(f, { title: e.title, location: e.location || '', description: e.description || '', allDay: !!e.all_day,
      repeat: e.recurring ? 'keep' : '', until: '', scope: 'series' })
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
    if (v.end && v.allDay) {   // протянули по дням месяца: весь день, конец — последний выделенный день
      f.allDay = true; f.endDate = isoDate(addDays(new Date(v.end), -1))
    } else if (v.end) {   // протянули по сетке: точное время начала и конца
      const e2 = new Date(v.end)
      f.startTime = hm(d); f.endDate = isoDate(e2); f.endTime = hm(e2)
    }
    if (v.people) f.people = v.people.filter((id) => (state.config?.people || []).some((p) => p.id === id))
    let last = ''
    try { last = localStorage.getItem(LS) || '' } catch {}
    const w = cals.value.map((c) => c.key)
    f.calendar = w.includes(last) ? last : w[0] || ''
    // Плашка «частые и недавние» из «+»: название, длительность, участники, место и привычное время.
    const t = v.template
    if (t) {
      f.title = t.title
      f.location = t.location || ''
      f.people = (t.people || []).filter((id) => (state.config?.people || []).some((p) => p.id === id))
      if (w.includes(t.calendar)) f.calendar = t.calendar
      if (/^\d\d:\d\d$/.test(t.time || '')) f.startTime = t.time
      const end = new Date(new Date(`${f.startDate}T${f.startTime}`).getTime() + (t.minutes || 60) * 60000)
      f.endDate = isoDate(end); f.endTime = hm(end)
    }
  }
  origPeople = [...f.people]
})

watch(() => ed.value?.parsed, (parsed) => { if (parsed) applyParsed(parsed) })

// Сдвигаем конец вместе с началом, чтобы длительность не терялась.
watch(() => [f.startDate, f.startTime], ([d, t], old) => {
  if (filling || !old[0] || !d || !f.endDate) return
  if (f.allDay) {
    const days = (Date.parse(f.endDate) - Date.parse(old[0])) / DAY
    f.endDate = isoDate(addDays(new Date(`${d}T12:00`), days))
    return
  }
  const a = new Date(`${old[0]}T${old[1] || '00:00'}`)
  const b = new Date(`${f.endDate}T${f.endTime || '00:00'}`)
  const n = new Date(`${d}T${t || '00:00'}`)
  if (isNaN(a) || isNaN(b) || isNaN(n)) return
  const e = new Date(n.getTime() + (b - a))
  f.endDate = isoDate(e); f.endTime = hm(e)
})

function close() { if (!busy.value) state.editor = null }
function openWizard() { state.editor = null; state.wizard = true }

async function parsePhrase() {
  const text = phrase.value.trim()
  if (!text || busy.value || parsing.value || !ed.value || !isNew.value) return
  const draft = ed.value
  phraseError.value = ''
  parsing.value = true
  try {
    const parsed = await api.quick(text)
    if (ed.value !== draft) return
    if (parsed.kind !== 'event') { phraseError.value = 'Введите фразу о событии, например «Встреча завтра в 18:30».'; return }
    applyParsed(parsed, true)
    phrase.value = ''
  } catch (err) {
    if (ed.value === draft) phraseError.value = err.message
  } finally {
    if (ed.value === draft) parsing.value = false
  }
}

function dictate(text) {
  phrase.value = text
  parsePhrase()
}

function applyParsed(r, keepUnspecified = false) {
  filling = true
  f.title = r.title || f.title
  const defaultDate = 'дата не указана — взято сегодня'
  const keepDate = keepUnspecified && r.notes.includes(defaultDate) && !!f.startDate
  const date = keepDate ? f.startDate : r.date
  if (!keepUnspecified || !r.all_day) {
    f.allDay = r.all_day
    f.startDate = date; f.endDate = date
    if (!r.all_day) { f.startTime = r.start; f.endTime = r.end }
  } else if (!keepDate) {
    const days = (Date.parse(f.endDate) - Date.parse(f.startDate)) / DAY
    f.startDate = date
    f.endDate = isoDate(addDays(new Date(`${date}T12:00`), Number.isFinite(days) ? days : 0))
  }
  if (r.location) f.location = r.location
  if (!keepUnspecified || r.repeat) {
    f.repeat = r.repeat?.nth === -1 ? 'monthly_last' : r.repeat?.nth ? 'monthly_nth' : r.repeat?.freq || ''
  }
  if (r.people.length) f.people = r.people
  parseNotes.value = keepDate ? r.notes.filter((note) => note !== defaultDate) : r.notes
  nextTick(() => { filling = false })
}

// Повтор по дате начала: «каждые 2 недели», «каждый месяц, 3-й четверг», «… последний четверг» (v0.21)
const WD = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']
const WD_ACC = ['понедельник', 'вторник', 'среду', 'четверг', 'пятницу', 'субботу', 'воскресенье']
const WD_LAST = ['последний понедельник', 'последний вторник', 'последнюю среду', 'последний четверг', 'последнюю пятницу',
  'последнюю субботу', 'последнее воскресенье']
const startD = computed(() => new Date(`${f.startDate || isoDate(new Date())}T12:00`))
const wdIdx = computed(() => (startD.value.getDay() + 6) % 7)
const startDay = computed(() => startD.value.getDate())
const nthNum = computed(() => Math.floor((startDay.value - 1) / 7) + 1)
const nthText = computed(() => `${nthNum.value}-й ${WD_ACC[wdIdx.value]}`.replace(/^(\d)-й (среду|пятницу|субботу)$/, '$1-ю $2')
  .replace(/^(\d)-й воскресенье$/, '$1-е воскресенье'))
const isLastWd = computed(() => { const d = new Date(startD.value); d.setDate(d.getDate() + 7); return d.getMonth() !== startD.value.getMonth() })
const lastText = computed(() => WD_LAST[wdIdx.value])
// «Последний четверг» есть, только пока дата — в последней неделе месяца; иначе — «N-й четверг»
watch(isLastWd, (v) => { if (!v && f.repeat === 'monthly_last') f.repeat = 'monthly_nth' })
function repeatRule(v) {
  if (v === 'biweekly') return { freq: 'weekly', interval: 2 }
  if (v === 'monthly_nth') return { freq: 'monthly', nth: nthNum.value, byday: [WD[wdIdx.value]] }
  if (v === 'monthly_last') return { freq: 'monthly', nth: -1, byday: [WD[wdIdx.value]] }
  return { freq: v }
}

function payload() {
  const sd = f.allDay ? `${f.startDate}T00:00:00` : `${f.startDate}T${f.startTime}:00`
  let ed_ = f.endDate
  if (f.allDay) ed_ = isoDate(addDays(new Date(`${f.endDate}T00:00`), 1)) // исключающий конец
  const end = f.allDay ? `${ed_}T00:00:00` : `${f.endDate}T${f.endTime}:00`
  return { start: sd, end, all_day: f.allDay }
}

async function save() {
  if (busy.value || parsing.value || !f.title.trim()) return
  error.value = ''
  const p = payload()
  if (!f.allDay && new Date(p.end) <= new Date(p.start)) {
    error.value = 'Конец должен быть позже начала. Для события после полуночи укажите дату окончания.'
    more.value = true
    return
  }
  if (f.allDay && f.endDate < f.startDate) { error.value = 'Конец раньше начала'; return }
  busy.value = true
  try {
    const repeat = f.repeat && f.repeat !== 'keep' ? { ...repeatRule(f.repeat), until: f.until || null } : null
    if (isNew.value) {
      await api.createEvent({ calendar: f.calendar, title: f.title.trim(), ...p, location: f.location,
        description: f.description, repeat, people: f.people.length ? f.people : null })
      try { localStorage.setItem(LS, f.calendar) } catch {}
    } else {
      const e = ed.value.event
      const body = { calendar: f.calendar, title: f.title.trim(), ...p, location: f.location, description: f.description }
      if (e.recurring) { body.occurrence = e.start; if (f.scope !== 'series') body.scope = f.scope }
      if (f.repeat !== 'keep' && f.scope !== 'once') { body.repeat_set = true; body.repeat = repeat }
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
.head {
  position: sticky; top: 0; z-index: 1; display: flex; align-items: center; justify-content: space-between;
  gap: 6px; background: var(--surface); padding: 6px 0 10px; margin-bottom: 4px;
}
.head h2 { margin: 0; font-size: 17px; font-weight: 600; }
.head .btn { min-height: 40px; padding-inline: 10px; }
.editor :deep(:is(input, button, select, textarea)) { scroll-margin-top: 64px; }
.group { margin-bottom: 10px; }
.fields { background: var(--surface-2); }
.group .row { padding-inline: 12px; }
.fields .row + .row::before { left: 12px; right: 12px; }
.durs { display: flex; gap: 6px; flex-wrap: wrap; }
.dur { border: 0; border-radius: 999px; padding: 7px 12px; font: inherit; font-size: 13px; background: var(--fill); color: var(--ink-2); }
.dur.on { background: var(--tint); color: #fff; font-weight: 600; }
.more-btn {
  width: 100%; min-height: 44px; display: flex; align-items: center; gap: 10px; margin: 0 0 10px; padding: 8px 12px; border: 0; border-radius: var(--radius-m);
  background: var(--surface-2); color: var(--tint); font: inherit; font-weight: 600; text-align: left;
}
.more-btn small { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 400; }
.phrase-group { margin-bottom: 10px; }
.phrase-row { display: flex; align-items: stretch; gap: 6px; }
.phrase-input {
  flex: 1; min-width: 0; min-height: 44px; border: 0; border-radius: 10px; padding: 6px 12px;
  background: var(--surface-2); color: var(--ink); font: inherit; font-size: 16px;
}
.phrase-input::placeholder { color: var(--ink-2); opacity: 1; }
.phrase-row .btn { padding-inline: 8px; }
.chev { margin-left: auto; color: var(--ink-3); transition: transform .2s; font-size: 20px; line-height: 1; }
.chev.open { transform: rotate(90deg); }
.between { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.in { width: 100%; min-width: 0; border: 0; background: transparent; font: inherit; color: var(--ink); padding: 4px 0; resize: vertical; }
.in.title-in { font-size: 20px; font-weight: 600; }
.times { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.time-field { display: grid; grid-template-columns: minmax(0, 1fr); gap: 4px; color: var(--ink-2); font-size: 13px; }
.fields input[type=date], .fields input[type=time], select {
  min-width: 0; max-width: 100%; min-height: 34px; font: inherit; color: var(--ink); background: var(--fill);
  border: 0; border-radius: 8px; padding: 5px 8px;
}
.fields input[type=time] { width: 100%; font-size: 16px; }
.fields input[type=date] { width: min(58%, 160px); }
select { min-width: 0; max-width: 62%; text-overflow: ellipsis; }   /* «Каждый месяц, последнюю пятницу» не раздвигает строку */
.all-day { cursor: pointer; }
.chk { width: 22px; height: 22px; accent-color: var(--red, #ff3b30); }
.editor :deep(.picker .opt) { min-height: 36px; }
.actions { display: flex; gap: 8px; flex-wrap: wrap; }
.danger { color: var(--red, #ff3b30); }
.warns .wrow { display: flex; gap: 10px; align-items: flex-start; font-size: 14px; }
.wdot { width: 8px; height: 8px; border-radius: 50%; flex: none; margin-top: 6px; background: var(--red, #ff3b30); }
.wrow.info .wdot { background: var(--orange, #ff9500); }
.wrow.info { color: var(--muted, #8a8a8e); }
.conflict { color: var(--red, #ff3b30); font-size: 14px; margin: 6px 12px 10px; }
.hint { color: var(--ink-2); font-size: 13px; }
@media (max-width: 374px) {
  .head h2 { font-size: 15px; }
  .head .btn { font-size: 13px; padding-inline: 6px; }
}
</style>
