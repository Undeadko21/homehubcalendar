<template>
  <Sheet :open="state.quickAdd" title="Добавить" label="Добавить" @close="close">
    <form class="qa" @submit.prevent="go">
      <input ref="input" v-model="text" class="field" placeholder="Событие, дело или покупка — одной фразой"
             aria-label="Быстро добавить" autocomplete="off" enterkeyhint="go" />
      <button class="btn filled" :disabled="busy || !text.trim()">{{ busy ? '…' : 'Добавить' }}</button>
    </form>
    <p v-if="error" class="err">{{ error }}</p>
    <div class="group ex">
      <button v-for="x in EXAMPLES" :key="x.t" type="button" class="row exr" @click="text = x.t; input?.focus()">
        <span class="kind" :class="x.k">{{ x.label }}</span><span class="ph">{{ x.t }}</span>
      </button>
    </div>
    <p class="faint small note">Событие откроется в форме для проверки, дело и покупки добавятся сразу.</p>
    <div class="group">
      <button v-if="canWrite" type="button" class="row link" @click="form">Событие — заполнить форму</button>
      <button v-if="canWrite" type="button" class="row link" @click="wizard">Секция или кружок по дням недели</button>
      <button type="button" class="row link" @click="lists">Открыть списки дел и покупок</button>
    </div>
  </Sheet>
</template>

<script setup>
// Единое «+»: одно поле для события, дела и покупки; тип определяет сервер по фразе.
import { computed, nextTick, ref, watch } from 'vue'
import { state, quickAdd, newEvent, setView, writableCalendars } from '../lib/store'
import Sheet from './Sheet.vue'

const EXAMPLES = [
  { k: 'ev', label: 'Событие', t: 'Йога завтра в 18:30 у Оли' },
  { k: 'todo', label: 'Дело', t: 'Дело: оплатить кружок до пятницы' },
  { k: 'shop', label: 'Покупки', t: 'Купить молоко, хлеб и сыр' },
]
const text = ref('')
const busy = ref(false)
const error = ref('')
const input = ref(null)
const canWrite = computed(() => writableCalendars().length > 0)

watch(() => state.quickAdd, async (v) => {
  if (!v) return
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
    await quickAdd(text.value.trim())
    close()
  } catch (e) {
    error.value = e.message
  } finally { busy.value = false }
}
function form() { close(); newEvent() }
function wizard() { close(); state.wizard = true }
function lists() { close(); setView('lists') }
</script>

<style scoped>
.qa { display: flex; gap: 8px; margin: 4px 0 12px; }
.field { flex: 1; min-width: 0; font: inherit; font-size: 17px; padding: 11px 14px; border: 0; border-radius: 12px; background: var(--fill); color: var(--ink); }
.err { color: var(--red); font-size: 14px; margin: 0 4px 10px; }
.group { background: var(--surface-2); margin-bottom: 12px; }
.row { width: 100%; border: 0; background: none; text-align: left; color: inherit; font: inherit; }
.row.link { color: var(--tint); }
.exr { gap: 10px; align-items: center; }
.kind { font-size: 12px; font-weight: 700; border-radius: 6px; padding: 2px 7px; color: #fff; flex: none; width: 66px; text-align: center; }
.kind.ev { background: #007aff; } .kind.todo { background: #ff9500; } .kind.shop { background: #34c759; }
.ph { color: var(--ink-2); font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.note { margin: -4px 4px 14px; }
.small { font-size: 13px; }
</style>
