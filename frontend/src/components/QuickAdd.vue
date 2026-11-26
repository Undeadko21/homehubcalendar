<template>
  <Sheet :open="state.quickAdd" title="Добавить фразой" label="Добавить фразой" :dismissible="!busy" @close="close">
    <label for="qa-text" class="qa-label">Событие, дело или покупка</label>
    <form class="qa" @submit.prevent="go">
      <input id="qa-text" ref="input" v-model="text" class="field"
             aria-label="Быстро добавить" autocomplete="off" enterkeyhint="go" />
      <MicButton :disabled="busy" @text="heard" @error="(m) => (error = m)" />
      <button class="btn filled" :disabled="busy || !text.trim()">{{ busy ? '…' : 'Добавить' }}</button>
    </form>
    <p v-if="error" class="err">{{ error }}</p>
    <div v-if="canWrite && recent.length" class="recent">
      <span class="faint small rl">Частые и недавние</span>
      <div class="chips">
        <button v-for="r in recent" :key="r.title" type="button" class="rchip" @click="useRecent(r)">
          <span class="rt">{{ r.title }}</span>
          <span class="rs">{{ recentSub(r) }}</span>
        </button>
      </div>
    </div>
    <div v-if="!state.editor" class="group">
      <button v-if="canWrite" type="button" class="row link" :disabled="busy" @click="form">Новое событие вручную</button>
      <button type="button" class="row link" :disabled="busy" @click="lists">Списки дел и покупок</button>
    </div>
  </Sheet>
</template>

<script setup>
// Тип записи определяет сервер по фразе.
import { computed, nextTick, ref, watch } from 'vue'
import { state, quickAdd, newEvent, setView, writableCalendars, personById } from '../lib/store'
import { api } from '../lib/api'
import Sheet from './Sheet.vue'
import MicButton from './MicButton.vue'

const text = ref('')
const busy = ref(false)
const error = ref('')
const input = ref(null)
const canWrite = computed(() => writableCalendars().length > 0)

// Частые и недавние события: нажатие открывает форму с заполненными названием, длительностью, участниками и местом.
const recent = ref([])
function recentSub(r) {
  const m = r.minutes
  const dur = m < 60 ? `${m} мин` : m % 60 ? `${Math.floor(m / 60)} ч ${m % 60} мин` : `${m / 60} ч`
  const who = (r.people || []).map((id) => personById.value[id]?.name).filter(Boolean).join(', ')
  return who ? `${dur} · ${who}` : dur
}
function useRecent(r) {
  if (busy.value) return
  const date = state.editor?.quickDate ?? state.editor?.date
  close()
  newEvent(date, r)
}

watch(() => state.quickAdd, async (v) => {
  if (!v) return
  api.recentEvents().then((r) => { recent.value = r.items || [] }).catch(() => { /* подсказка, не обязательна */ })
  text.value = ''
  error.value = ''
  await nextTick()
  setTimeout(() => input.value?.focus(), 60)
})

function close() { state.quickAdd = false }
async function go() {
  if (!text.value.trim() || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const draft = state.editor
    await quickAdd(text.value.trim(), draft?.date, draft)
    close()
  } catch (e) {
    error.value = e.message
  } finally { busy.value = false }
}
// Сказали голосом: фразу видно в поле, и она сразу добавляется (событие откроется в форме для проверки).
function heard(t) { text.value = t; go() }
function form() { close(); newEvent() }
function lists() { close(); setView('lists') }
</script>

<style scoped>
.qa { display: flex; gap: 8px; margin: 4px 0 12px; }
.qa-label { display: block; margin: 8px 0 6px; font-size: 13px; color: var(--ink-2); }
.field { flex: 1; min-width: 0; font: inherit; font-size: 17px; padding: 11px 14px; border: 0; border-radius: 12px; background: var(--fill); color: var(--ink); }
.err { color: var(--red); font-size: 14px; margin: 0 4px 10px; }
.group { background: var(--surface-2); margin-bottom: 12px; }
.row { width: 100%; border: 0; background: none; text-align: left; color: inherit; font: inherit; }
.row.link { color: var(--tint); }
.recent { margin: 0 0 12px; }
.rl { display: block; margin: 0 4px 6px; }
.chips { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 2px; scrollbar-width: none; }
.chips::-webkit-scrollbar { display: none; }
.rchip { flex: none; max-width: 190px; border: 0; border-radius: 12px; background: var(--surface-2); color: var(--ink); font: inherit;
  padding: 8px 12px; text-align: left; display: flex; flex-direction: column; gap: 1px; cursor: pointer; }
.rt { font-size: 15px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rs { font-size: 12px; color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.small { font-size: 13px; }
</style>
