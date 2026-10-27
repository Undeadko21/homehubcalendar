<template>
  <section v-if="items.length" class="bd">
    <h2 class="sec">Дни рождения</h2>
    <div class="group">
      <div v-for="b in items" :key="b.name + b.date" class="row">
        <span class="cake" aria-hidden="true">🎂</span>
        <span class="main">
          <strong>{{ b.name }}</strong>
          <small>{{ dateText(b) }}<template v-if="b.turns"> · исполнится {{ b.turns }}</template></small>
        </span>
        <span class="cnt" :class="{ now: b.days === 0 }">{{ phrase(b.days) }}</span>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, watch } from 'vue'
import { api } from '../lib/api'
import { state } from '../lib/store'

const items = ref([])
const load = () => api.birthdays(30).then((r) => (items.value = r.upcoming.slice(0, 3))).catch(() => {})
watch(() => state.revision, load, { immediate: true })

const dateText = (b) => new Date(b.date + 'T00:00').toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
function phrase(n) {
  if (n === 0) return 'сегодня'
  if (n === 1) return 'завтра'
  const m = n % 100
  const w = m >= 11 && m <= 14 ? 'дней' : ({ 1: 'день', 2: 'дня', 3: 'дня', 4: 'дня' }[n % 10] || 'дней')
  return `через ${n} ${w}`
}
</script>

<style scoped>
.sec { font-size: 20px; font-weight: 700; margin: 0 0 10px; letter-spacing: -0.01em; }
.group { background: var(--surface-2); max-width: 760px; }
.cake { font-size: 22px; }
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.main small { color: var(--ink-2); font-size: 12px; }
.cnt { font-weight: 600; font-size: 14px; color: var(--ink-2); white-space: nowrap; }
.cnt.now { color: var(--red); }
</style>
