<template>
  <Sheet :open="!!e" :label="e?.title || ''" @close="close">
    <div v-if="e" class="ev" :style="{ '--c': color }">
      <div class="head">
        <h2>{{ e.title }}</h2>
        <button class="btn close" @click="close">Готово</button>
      </div>
      <p class="when">
        {{ dayLabel }}<br />
        <span class="time">{{ formatEventTime(e) }}</span>
        <span v-if="e.recurring" class="tag">повторяется</span>
        <span v-if="e.tentative" class="tag">под вопросом</span>
      </p>

      <!-- Чьё событие -->
      <div class="group">
        <div class="row stack">
          <div class="row-head">
            <span class="label">Чьё событие</span>
            <button v-if="!editingPeople" class="btn link" @click="startEdit">Изменить</button>
          </div>
          <div v-if="!editingPeople" class="persons">
            <span v-for="p in persons" :key="p.id" class="person" :style="{ '--c': p.color }">
              <i></i>{{ p.emoji }} {{ p.name }}
            </span>
            <span v-if="!persons.length" class="faint">Без владельца</span>
            <span v-if="e.people_override" class="faint small">выбрано вручную</span>
          </div>
          <template v-else>
            <PeoplePicker v-model="draft" label="Чьё событие" :disabled="saving" />
            <p class="faint small">
              {{ e.recurring ? 'Применится ко всем повторам. ' : '' }}Меняется только здесь — в Яндексе событие останется как было.
            </p>
            <div class="actions">
              <button class="btn filled" :disabled="saving" @click="savePeople(draft)">Сохранить</button>
              <button class="btn gray" :disabled="saving" @click="editingPeople = false">Отмена</button>
              <button v-if="e.people_override" class="btn" :disabled="saving" @click="savePeople(null)">Как в календаре</button>
            </div>
          </template>
        </div>
      </div>

      <!-- Кто отвозит / забирает -->
      <template v-if="e.escort">
        <h3 class="group-title">Отвезти и забрать: {{ childNames }}</h3>
        <div class="group">
          <div v-if="e.recurring" class="row">
            <div class="seg scope" role="tablist" aria-label="Как применить">
              <button :class="{ on: scope === 'series' }" @click="scope = 'series'">Всегда</button>
              <button :class="{ on: scope === 'once' }" @click="scope = 'once'">Только {{ shortDay }}</button>
            </div>
          </div>
          <div v-for="role in ROLES" :key="role.id" class="row stack">
            <div class="row-head">
              <span class="label">{{ role.label }} <span class="faint win">{{ windowText(role.id) }}</span></span>
              <button v-if="e.escort[role.id].scope === 'once'" class="btn link" :disabled="saving"
                      @click="setEscort(role.id, null, 'once')">Как обычно</button>
            </div>
            <div class="choices" role="radiogroup" :aria-label="role.label">
              <button v-for="p in adults" :key="p.id" role="radio" class="choice"
                      :aria-checked="e.escort[role.id].person === p.id"
                      :class="{ on: e.escort[role.id].person === p.id, free: e.escort[role.id].free.includes(p.id) }"
                      :style="{ '--c': p.color }" :disabled="saving" @click="setEscort(role.id, p.id)">
                {{ p.emoji }} {{ p.name }}
              </button>
              <button role="radio" class="choice skip" :aria-checked="e.escort[role.id].skip"
                      :class="{ on: e.escort[role.id].skip }" :disabled="saving" @click="setEscort(role.id, '-')">
                Не нужно
              </button>
            </div>
            <p v-if="e.escort[role.id].conflicts.length" class="conflict">
              {{ personName(e.escort[role.id].person) }} в это время занят(а):
              {{ e.escort[role.id].conflicts.map((c) => `${c.title} (${timeRange(c)})`).join(', ') }}.
              <template v-if="freeOthers(role.id).length">Свободны: {{ freeOthers(role.id).map(personName).join(', ') }}.</template>
            </p>
            <p v-else-if="!e.escort[role.id].person && !e.escort[role.id].skip" class="hint warn">
              Никто не назначен.
              <template v-if="e.escort[role.id].free.length">Свободны: {{ e.escort[role.id].free.map(personName).join(', ') }}.</template>
              <template v-else>Все взрослые в это время заняты.</template>
            </p>
            <p v-else-if="e.escort[role.id].person" class="hint ok">
              Конфликтов нет{{ e.escort[role.id].scope === 'once' ? ', замена только на этот день' : '' }}.
            </p>
          </div>
        </div>
        <p class="group-note">
          Учитывается {{ escortCfg.before_minutes }} мин до начала и {{ escortCfg.after_minutes }} мин после конца.
          Поменять можно в настройках.
        </p>
      </template>

      <div v-if="e.location || e.url || e.description" class="group details">
        <div v-if="e.location" class="row">
          <span class="label">Где</span>
          <a :href="mapUrl" target="_blank" rel="noopener" class="val">{{ e.location }}</a>
        </div>
        <div v-if="e.url" class="row">
          <span class="label">Ссылка</span>
          <a :href="e.url" target="_blank" rel="noopener" class="val">{{ e.url }}</a>
        </div>
        <div v-if="e.description" class="row stack desc">{{ e.description }}</div>
      </div>
      <p v-if="e.private" class="faint small">Детали скрыты: у календаря включено «только занят».</p>
      <p v-if="error" class="conflict">{{ error }}</p>
      <p class="faint small src">Календари: {{ calNames }}</p>
    </div>
  </Sheet>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { state, personById, eventColor, reload, refreshSelected } from '../lib/store'
import { eventRange, formatEventTime, formatTime, relativeDayName } from '../lib/dates'
import { api } from '../lib/api'
import PeoplePicker from './PeoplePicker.vue'
import Sheet from './Sheet.vue'

const ROLES = [
  { id: 'dropoff', label: 'Отвезти' },
  { id: 'pickup', label: 'Забрать' },
]

const e = computed(() => state.selected)
const color = computed(() => (e.value ? eventColor(e.value) : '#888'))
const persons = computed(() =>
  (e.value?.people || []).filter((id) => !id.startsWith('_')).map((id) => personById.value[id]).filter(Boolean),
)
const dayLabel = computed(() => {
  if (!e.value) return ''
  const d = eventRange(e.value).start
  const full = d.toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' })
  const rel = relativeDayName(d)
  return ['Сегодня', 'Завтра', 'Вчера'].includes(rel) ? `${rel}, ${full}` : full.charAt(0).toUpperCase() + full.slice(1)
})
const shortDay = computed(() => (e.value ? eventRange(e.value).start.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' }) : ''))
const mapUrl = computed(() => 'https://yandex.ru/maps/?text=' + encodeURIComponent(e.value?.location || ''))
const calNames = computed(() => {
  const all = state.config?.calendars || []
  return (e.value?.calendars || []).map((k) => all.find((c) => c.key === k)?.name || k).join(', ')
})
const adults = computed(() => (state.config?.people || []).filter((p) => !p.id.startsWith('_') && !p.needs_escort && !p.hidden))
const personName = (id) => personById.value[id]?.name || id
const childNames = computed(() => (e.value?.escort?.children || []).map(personName).join(', '))
const escortCfg = computed(() => state.config?.escort || { before_minutes: 30, after_minutes: 30 })
const timeRange = (c) => `${formatTime(new Date(c.start))}–${formatTime(new Date(c.end))}`
const freeOthers = (role) => e.value.escort[role].free.filter((id) => id !== e.value.escort[role].person)
function windowText(role) {
  const w = e.value.escort[role].window
  return `${formatTime(new Date(w[0]))}–${formatTime(new Date(w[1]))}`
}

const editingPeople = ref(false)
const saving = ref(false)
const error = ref('')
const draft = ref([])
const scope = ref('series')

watch(() => e.value?.id, () => {
  editingPeople.value = false
  error.value = ''
  scope.value = 'series'
})

function startEdit() {
  draft.value = (e.value?.people || []).filter((id) => !id.startsWith('_'))
  editingPeople.value = true
}

async function run(fn) {
  saving.value = true
  error.value = ''
  try {
    await fn()
    await refreshSelected()
    reload()
  } catch (err) {
    error.value = 'Не удалось сохранить: ' + err.message
  } finally {
    saving.value = false
  }
}

function savePeople(people) {
  return run(async () => {
    await api.setEventPeople(e.value.uid, people)
    editingPeople.value = false
  })
}

// Для разовых событий «вся серия» и «только этот день» — одно и то же, храним как серию.
function setEscort(role, person, forceScope) {
  const sc = forceScope || (e.value.recurring ? scope.value : 'series')
  return run(() => api.setEscort(e.value.uid, sc === 'once' ? e.value.start : null, role, person))
}

function close() { state.selected = null }
</script>

<style scoped>
.ev { padding-top: 6px; }
.head { display: flex; align-items: flex-start; gap: 8px; }
h2 { flex: 1; margin: 0; font-size: 22px; line-height: 1.2; font-weight: 700; letter-spacing: -0.02em; }
.close { margin: -2px -10px 0 0; font-weight: 600; }
.when { margin: 6px 0 16px; color: var(--ink-2); line-height: 1.45; }
.time { color: var(--ink); }
.tag { display: inline-block; font-size: 12px; background: var(--fill); color: var(--ink-2); border-radius: 6px; padding: 1px 7px; margin-left: 6px; }

.group { background: var(--surface-2); }
.row.stack { flex-direction: column; align-items: stretch; gap: 8px; padding-top: 10px; padding-bottom: 12px; }
.row-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.label { font-weight: 600; font-size: 15px; }
.win { font-weight: 400; margin-left: 4px; }
.row > .label { min-width: 64px; }
.val { overflow-wrap: anywhere; }
.btn.link { padding: 2px 0; font-weight: 500; }
.persons { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.person { --c: #888; display: inline-flex; align-items: center; gap: 6px; background: color-mix(in srgb, var(--c) 16%, var(--surface)); border-radius: 999px; padding: 3px 10px 3px 8px; font-weight: 600; font-size: 14px; }
.person i { width: 8px; height: 8px; border-radius: 50%; background: var(--c); }
.small { font-size: 13px; margin: 0; }
.actions { display: flex; gap: 8px; flex-wrap: wrap; }
.group-title { margin: 22px 4px 6px; }
.group-note { margin: 6px 4px 0; }
.scope { width: 100%; }
.scope button { flex: 1; }

.choices { display: flex; flex-wrap: wrap; gap: 6px; }
.choice {
  --c: #8e8e93; border: 0; background: var(--surface); border-radius: 999px; padding: 6px 12px;
  font-size: 14px; font-weight: 500; box-shadow: inset 0 0 0 1px var(--line);
}
.choice.free:not(.on) { box-shadow: inset 0 0 0 1.5px color-mix(in srgb, var(--ok) 70%, transparent); }
.choice.on { background: var(--c); color: #fff; box-shadow: none; font-weight: 600; }
.choice.skip.on { background: var(--ink-2); }
.conflict { color: var(--red); font-size: 13px; margin: 0; font-weight: 500; }
.hint { font-size: 13px; margin: 0; }
.hint.warn { color: var(--warn); }
.hint.ok { color: var(--ok); }
.details { margin-top: 20px; }
.desc { white-space: pre-wrap; overflow-wrap: anywhere; color: var(--ink-2); }
.src { margin-top: 14px; }
</style>
