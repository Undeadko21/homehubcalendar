<template>
  <Sheet :open="!!e" :title="e ? 'Кто везёт' : ''" @close="close">
    <div v-if="e" class="dp">
      <p class="what"><strong>{{ e.title }}</strong> · {{ when }}</p>
      <div v-if="e.recurring" class="seg scope" role="tablist" aria-label="Как применить">
        <button :class="{ on: scope === 'series' }" @click="scope = 'series'">Всегда</button>
        <button :class="{ on: scope === 'once' }" @click="scope = 'once'">Только {{ shortDay }}</button>
      </div>
      <div v-for="role in roles" :key="role.id" class="role">
        <div class="rh">{{ role.label }} <span class="faint">{{ role.window }}</span></div>
        <div class="drivers" role="radiogroup" :aria-label="role.label">
          <button v-for="p in adults" :key="p.id" role="radio" class="driver" :style="{ '--c': p.color }"
                  :aria-checked="role.r.person === p.id" :class="{ on: role.r.person === p.id, busy: !role.r.free.includes(p.id) }"
                  :disabled="saving" @click="pick(role.id, p.id)">
            <span class="ava">{{ p.emoji || p.name.slice(0, 1) }}</span>
            <span class="dn">{{ p.name }}</span>
            <span class="ds">{{ role.r.free.includes(p.id) ? 'свободен' : 'занят(а)' }}</span>
          </button>
          <button role="radio" class="driver skip" :aria-checked="!!role.r.skip" :class="{ on: role.r.skip }" :disabled="saving" @click="pick(role.id, '-')">
            <span class="ava">—</span><span class="dn">Не нужно</span><span class="ds">&nbsp;</span>
          </button>
        </div>
      </div>
      <p v-if="error" class="conflict">{{ error }}</p>
      <button class="btn link more" @click="full">Все настройки поездки ›</button>
    </div>
  </Sheet>
</template>

<script setup>
// Быстрый выбор «кто отвозит / забирает» по значку 🚗 на плашке — без карточки события.
import { computed, ref, watch } from 'vue'
import { state, reload, openEvent, toast } from '../lib/store'
import { isoLocal, addDays } from '../lib/dates'
import { api } from '../lib/api'
import { haptic } from '../lib/haptic'
import { eventRange, formatTime, relativeDayName } from '../lib/dates'
import Sheet from './Sheet.vue'

const e = computed(() => state.driverPick)
const scope = ref('once')
const saving = ref(false)
const error = ref('')
watch(() => e.value?.id, () => { scope.value = 'once'; error.value = '' })   // по id: свежие данные того же события не сбрасывают выбор

const adults = computed(() => (state.config?.people || []).filter((p) => !p.id.startsWith('_') && !p.needs_escort && !p.hidden))
const shortDay = computed(() => e.value ? eventRange(e.value).start.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' }) : '')
const when = computed(() => {
  if (!e.value) return ''
  const r = eventRange(e.value)
  return `${relativeDayName(r.start) || shortDay.value}, ${formatTime(r.start)}–${formatTime(r.end)}`
})
const roles = computed(() => {
  const esc = e.value?.escort
  if (!esc || esc.mode !== 'escort') return []
  return [['dropoff', 'Отвезти'], ['pickup', 'Забрать']]
    .filter(([id]) => esc[id] && (!esc.only || esc.only === id))
    .map(([id, label]) => {
      const r = esc[id]
      const w = r.window ? `${formatTime(new Date(r.window[0]))}–${formatTime(new Date(r.window[1]))}` : ''
      return { id, label, r: { free: [], ...r }, window: w }
    })
})

async function pick(role, person) {
  const ev = e.value
  const info = ev.escort[role]
  info.person = person === '-' ? null : person   // показываем выбор сразу
  info.skip = person === '-'
  haptic('tap')
  saving.value = true
  error.value = ''
  try {
    await api.setEscort(ev.uid, ev.recurring && scope.value === 'once' ? ev.start : null, role, person)
    haptic('success')
    reload()
    // Проверяем по свежим данным: разовая замена на этот день важнее «Всегда» — тогда честно об этом говорим.
    const fresh = await freshEvent(ev)
    if (fresh && state.driverPick === ev) state.driverPick = fresh
    const r = fresh?.escort?.[role]
    if (r && scope.value === 'series' && r.scope === 'once' && (person === '-' ? !r.skip : r.person !== person)) {
      error.value = `На ${shortDay.value} стоит разовая замена — она важнее «Всегда». Выберите «Только ${shortDay.value}» или откройте все настройки поездки.`
      return
    }
    if (roles.value.every((x) => x.r.person || x.r.skip)) { close(); toast('Сохранено') }
  } catch (err) {
    error.value = 'Не удалось сохранить: ' + err.message
    const fresh = await freshEvent(ev).catch(() => null)   // вернуть то, что на самом деле сохранено
    if (fresh && state.driverPick === ev) state.driverPick = fresh
    reload()
  } finally {
    saving.value = false
  }
}
async function freshEvent(ev) {
  const d = new Date(ev.all_day ? ev.start + 'T00:00' : ev.start)
  const list = await api.events(isoLocal(addDays(d, -1)), isoLocal(addDays(d, 2)))
  return list.find((x) => x.id === ev.id) || list.find((x) => x.uid === ev.uid && x.start === ev.start) || null
}
function close() { state.driverPick = null }
function full() { const ev = e.value; close(); openEvent(ev) }
</script>

<style scoped>
.dp { display: flex; flex-direction: column; gap: 14px; padding-bottom: 8px; }
.what { margin: 0; color: var(--ink-2); }
.what strong { color: var(--ink); }
.rh { font-weight: 600; margin-bottom: 8px; }
.drivers { display: grid; grid-template-columns: repeat(auto-fill, minmax(76px, 1fr)); gap: 8px; }
.driver {
  --c: #888; display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 10px 6px; border-radius: 14px;
  border: 1.5px solid var(--line); background: var(--surface); color: var(--ink); font: inherit; cursor: pointer;
}
.driver .ava { width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center; font-size: 22px; background: color-mix(in srgb, var(--c) 22%, var(--surface)); }
.driver .dn { font-weight: 600; font-size: 14px; }
.driver .ds { font-size: 12px; color: var(--green, #34c759); }
.driver.busy .ds { color: var(--ink-3); }
.driver.on { border-color: var(--c); background: color-mix(in srgb, var(--c) 12%, var(--surface)); }
.driver.skip.on { border-color: var(--ink-3); }
.more { align-self: flex-start; }
.conflict { color: var(--red); margin: 0; }
</style>
