<template>
  <div>
    <div class="group">
      <div v-for="p in ppl" :key="p.id" class="row stack">
        <span class="label"><i class="dot" :style="{ background: p.color }"></i>{{ p.emoji }} {{ p.name }}</span>
        <div class="choices" role="group" :aria-label="'Напоминать ' + p.name">
          <button v-for="m in choices" :key="m" type="button" class="choice skip" :class="{ on: has(p.id, m) }"
                  :aria-pressed="has(p.id, m)" :disabled="busy" @click="toggle(p.id, m)">{{ label(m) }}</button>
        </div>
      </div>
    </div>
    <p v-if="error" class="group-note err">{{ error }}</p>
    <p class="group-note">
      Можно выбрать несколько вариантов: например за день и за 30 минут. Напоминание приходит о событиях этого человека
      («Йога — через 30 минут»), у кого ничего не выбрано — без напоминаний. Событий на весь день и поездок это не касается.
      Чтобы уведомления приходили на телефон или Mac, в приложении отметьте, чьи напоминания показывать
      (Настройки → Напоминания).
    </p>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { api } from '../lib/api'
import { state } from '../lib/store'

const rules = ref({})
const choices = ref([5, 10, 15, 30, 60, 120, 1440])
const busy = ref(false)
const error = ref('')
const ppl = computed(() => (state.config?.people || []).filter((p) => !p.id.startsWith('_') && !p.hidden))
const label = (m) => (m >= 1440 ? 'за день' : m >= 60 ? `за ${m / 60} ч` : `за ${m} мин`)
const has = (id, m) => (rules.value[id] || []).includes(m)

api.eventReminders().then((r) => { rules.value = r.people; choices.value = r.choices }).catch(() => {})

async function toggle(id, m) {
  const cur = new Set(rules.value[id] || [])
  cur.has(m) ? cur.delete(m) : cur.add(m)
  const next = { ...rules.value, [id]: [...cur].sort((a, b) => b - a) }
  busy.value = true
  error.value = ''
  try {
    rules.value = (await api.saveEventReminders(next)).people
  } catch (e) {
    error.value = 'Не удалось сохранить: ' + e.message
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }
.choices { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.choice { border: 1px solid var(--line); background: var(--surface); color: var(--ink-2); border-radius: 999px; padding: 6px 12px; font-size: 14px; }
.choice.on { background: var(--red, #ff3b30); border-color: transparent; color: #fff; font-weight: 600; }
.choice:disabled { opacity: .6; }
.err { color: var(--red, #ff3b30); }
</style>
