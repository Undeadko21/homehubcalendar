<template>
  <Sheet :open="!!state.personSheet" :title="data ? `${data.person.emoji || ''} ${data.person.name}` : 'Профиль'" @close="state.personSheet = null">
    <div v-if="err" class="group"><div class="row"><span class="err">{{ err }}</span></div></div>
    <div v-else-if="!data" class="group"><div class="row"><span class="muted">Загружаю…</span></div></div>
    <template v-else>
      <h3 class="group-title">Ближайшее</h3>
      <div class="group">
        <div v-if="!data.next.length" class="row"><span class="muted">Ничего в ближайшие две недели</span></div>
        <button v-for="e in data.next" :key="e.id" class="row link" @click="open(e)">
          <span class="lbl">{{ e.title }}</span>
          <span class="val muted">{{ when(e) }}</span>
        </button>
      </div>

      <template v-if="data.regular.length">
        <h3 class="group-title">Регулярно</h3>
        <div class="group">
          <div v-for="(r, i) in data.regular" :key="i" class="row stack">
            <span class="lbl">{{ r.title }}</span>
            <span class="muted sub">{{ r.days.join(', ') }} в {{ r.time }}<template v-if="r.dropoff || r.pickup">
              · везёт {{ r.dropoff || '—' }}, забирает {{ r.pickup || '—' }}</template></span>
          </div>
        </div>
      </template>

      <template v-if="data.duties.length">
        <h3 class="group-title">Поездки на неделю ({{ data.duties_count }})</h3>
        <div class="group">
          <div v-for="(d, i) in data.duties" :key="i" class="row">
            <span class="lbl">{{ d.title }}</span><span class="val muted">{{ when(d) }}</span>
          </div>
        </div>
      </template>

      <template v-if="data.todos.length">
        <h3 class="group-title">Дела</h3>
        <div class="group">
          <div v-for="t in data.todos" :key="t.id" class="row">
            <span class="lbl">{{ t.text }}</span><span class="val muted">{{ t.due ? 'до ' + t.due.slice(8) + '.' + t.due.slice(5, 7) : t.list }}</span>
          </div>
        </div>
      </template>
    </template>
  </Sheet>
</template>

<script setup>
// Профиль человека: что у него впереди, регулярные занятия и кто его возит, поездки и дела — одним листом.
import { ref, watch } from 'vue'
import Sheet from './Sheet.vue'
import { api } from '../lib/api'
import { state, openEvent } from '../lib/store'
import { formatTime } from '../lib/dates'

const data = ref(null)
const err = ref('')

watch(() => state.personSheet, async (id) => {
  data.value = null
  err.value = ''
  if (!id) return
  try { data.value = await api.person(id) } catch (e) { err.value = e.message }
}, { immediate: true })

function when(e) {
  const d = new Date(e.all_day ? e.start + 'T00:00' : e.start)
  const day = d.toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric', month: 'short' })
  return e.all_day ? day : `${day}, ${formatTime(d)}`
}

function open(e) {
  state.personSheet = null
  openEvent(e)
}
</script>

<style scoped>
.row.link { width: 100%; text-align: left; background: none; border: 0; font: inherit; color: inherit; }
.row.stack { flex-direction: column; align-items: flex-start; gap: 2px; }
.sub { font-size: 13px; }
</style>
