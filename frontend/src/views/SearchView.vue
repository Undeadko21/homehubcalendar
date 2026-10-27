<template>
  <div class="search">
    <form class="bar" @submit.prevent="run">
      <input ref="input" v-model="text" class="field" type="search" inputmode="search" enterkeyhint="search"
             placeholder="Название, место или описание" aria-label="Поиск по событиям" autocomplete="off" />
    </form>
    <p v-if="text.trim().length < 2" class="hint">Ищет по событиям за последние 2 месяца и на год вперёд.</p>
    <p v-else-if="loading" class="hint">Ищу…</p>
    <p v-else-if="error" class="hint err">{{ error }}</p>
    <p v-else-if="!results.length" class="hint">Ничего не найдено.</p>
    <div v-else class="group">
      <button v-for="e in results" :key="e.id" class="row res" :style="{ '--c': eventColor(e) }" @click="openEvent(e)">
        <span class="bar-c" aria-hidden="true"></span>
        <span class="body">
          <span class="t">{{ e.title }}</span>
          <span class="s">{{ when(e) }}<template v-if="e.location"> · {{ e.location }}</template></span>
          <span class="who">{{ e.people.map((p) => personById[p]?.name).filter(Boolean).join(', ') }}</span>
        </span>
      </button>
      <p v-if="results.length >= 300" class="hint">Показаны первые 300 — уточните запрос.</p>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { api } from '../lib/api'
import { openEvent, eventColor, personById } from '../lib/store'
import { formatTime, eventRange } from '../lib/dates'

const text = ref('')
const results = ref([])
const loading = ref(false)
const error = ref('')
const input = ref(null)
let timer, seq = 0

async function run() {
  const q = text.value.trim()
  if (q.length < 2) { results.value = []; return }
  const my = ++seq
  loading.value = true
  error.value = ''
  try {
    const r = await api.search(q)
    if (my === seq) results.value = r
  } catch (e) {
    if (my === seq) error.value = 'Не удалось выполнить поиск: ' + e.message
  } finally {
    if (my === seq) loading.value = false
  }
}
watch(text, () => { clearTimeout(timer); timer = setTimeout(run, 300) })
onMounted(() => input.value?.focus())

function when(e) {
  const d = eventRange(e).start
  const day = d.toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric', month: 'short', year: d.getFullYear() === new Date().getFullYear() ? undefined : 'numeric' })
  return e.all_day ? `${day}, весь день` : `${day}, ${formatTime(d)}`
}
</script>

<style scoped>
.search { padding: 12px 16px 32px; max-width: 760px; }
.field {
  width: 100%; box-sizing: border-box; font: inherit; font-size: 17px; padding: 10px 14px; border: 0;
  border-radius: 10px; background: var(--fill); color: var(--ink);
}
.hint { color: var(--ink-3); font-size: 14px; margin: 14px 4px; }
.hint.err { color: var(--red); }
.res { width: 100%; border: 0; background: none; text-align: left; color: inherit; align-items: stretch; }
.res:hover { background: var(--fill); }
.bar-c { width: 4px; border-radius: 2px; background: var(--c); flex: none; }
.body { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.t { font-weight: 600; }
.s { font-size: 13px; color: var(--ink-2); }
.who { font-size: 12px; color: var(--ink-3); }
.group { margin-top: 14px; }
</style>
