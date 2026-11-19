<template>
  <div>
    <h3 class="group-title">Что изменилось за неделю</h3>
    <div class="group">
      <div v-if="!items.length" class="row muted">{{ failed ? 'Журнал не загрузился — попробуйте позже.' : loading ? 'Загружаю…' : 'Пока ничего не меняли. Здесь появятся добавленные, перенесённые и отменённые события, которые начинаются в ближайшие две недели.' }}</div>
      <div v-for="c in shown" :key="c.id" class="row chg">
        <span class="txt">
          <span class="t">{{ c.text }}</span>
          <span class="m">{{ when(c.at) }}<template v-if="c.origin"> · {{ c.origin }}</template><template v-if="names(c.people)"> · {{ names(c.people) }}</template></span>
        </span>
      </div>
      <button v-if="items.length > shown.length" class="row btn link more" @click="all = true">Показать все ({{ items.length }})</button>
    </div>
    <p class="group-note">
      «С iPhone», «с Android», «с компьютера» — правка через календарь; «в календаре …» — изменили прямо в Яндексе (или там,
      где этот календарь ведётся). Уведомления об изменениях — в «Напоминаниях».
    </p>
  </div>
</template>

<script setup>
// Журнал «что изменилось» (changes.py): последние 7 дней.
import { computed, ref } from 'vue'
import { api } from '../lib/api'
import { state } from '../lib/store'

const items = ref([])
const all = ref(false)
const shown = computed(() => (all.value ? items.value : items.value.slice(0, 8)))
const loading = ref(true)
const failed = ref(false)
api.eventChanges().then((r) => { items.value = r.items }).catch(() => { failed.value = true }).finally(() => { loading.value = false })
const names = (ids) => (ids || []).map((id) => (state.config?.people || []).find((p) => p.id === id)?.name).filter(Boolean).join(', ')
function when(at) {
  const d = new Date(at)
  const days = Math.floor((Date.now() - d) / 86400000)
  const t = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  return days < 1 && new Date().getDate() === d.getDate() ? `сегодня ${t}` : `${d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })} ${t}`
}
</script>

<style scoped>
.chg { align-items: flex-start; }
.more { width: 100%; }
.txt { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.t { font-weight: 500; }
.m { font-size: 13px; color: var(--ink-2); }
</style>
