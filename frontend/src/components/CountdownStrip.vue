<template>
  <section v-if="items.length" class="cd">
    <h2 class="sec">Скоро</h2>
    <div class="cards">
      <button v-for="c in items" :key="c.uid" class="card" @click="open(c)">
        <span class="num">{{ c.days === 0 ? '★' : c.days }}</span>
        <span class="unit">{{ c.days === 0 ? 'сегодня' : c.days === 1 ? 'день — завтра' : unit(c.days) + ' осталось' }}</span>
        <span class="t">{{ c.title }}</span>
        <small>{{ dateText(c) }}</small>
      </button>
    </div>
  </section>
</template>

<script setup>
// Обратный отсчёт до важных событий (звёздочка в карточке события): «12 дней до Отпуска».
import { ref, watch } from 'vue'
import { api } from '../lib/api'
import { state, goToDay } from '../lib/store'

const items = ref([])
const load = () => api.countdowns().then((r) => (items.value = r.slice(0, 4))).catch(() => {})
watch(() => state.revision, load, { immediate: true })

function unit(n) {
  const m = n % 100
  if (m >= 11 && m <= 14) return 'дней'
  return { 1: 'день', 2: 'дня', 3: 'дня', 4: 'дня' }[n % 10] || 'дней'
}
const dateText = (c) => new Date(c.all_day ? c.start.slice(0, 10) + 'T00:00' : c.start)
  .toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric', month: 'long' })
function open(c) { goToDay(new Date(c.all_day ? c.start.slice(0, 10) + 'T00:00' : c.start)) }
</script>

<style scoped>
.sec { font-size: 20px; font-weight: 700; margin: 0 0 10px; letter-spacing: -0.01em; }
.cards { display: flex; gap: 10px; overflow-x: auto; padding-bottom: 2px; max-width: 760px; }
.card {
  flex: 0 0 auto; min-width: 128px; max-width: 200px; display: flex; flex-direction: column; align-items: flex-start; gap: 0;
  padding: 12px 14px; border: 0; border-radius: 14px; background: var(--surface-2); color: var(--ink); font: inherit; text-align: left; cursor: pointer;
}
.num { font-family: var(--font-display); font-size: 34px; font-weight: 700; line-height: 1; color: var(--red); letter-spacing: -0.02em; }
.unit { font-size: 13px; color: var(--ink-2); margin-bottom: 6px; }
.t { font-weight: 600; font-size: 15px; line-height: 1.25; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
small { color: var(--ink-3); font-size: 12px; margin-top: 2px; }
</style>
