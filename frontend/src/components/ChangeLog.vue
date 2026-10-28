<template>
  <div>
    <p v-if="data.pending" class="group-note warn">
      Не отправлено в Яндекс: {{ data.pending }}. Сервер Яндекса не ответил — повторю сам каждые 2 минуты.
      <button class="btn link" :disabled="busy" @click="flush">Повторить сейчас</button>
    </p>
    <p v-if="data.error" class="group-note err">Яндекс отклонил запись: {{ data.error }}</p>
    <div v-if="data.items.length" class="group">
      <div v-for="c in data.items" :key="c.id" class="row stack">
        <div class="row-head">
          <span class="label">{{ c.title }}</span>
          <button v-if="c.action !== 'undo'" class="btn link" :disabled="busy" @click="undo(c)">Отменить</button>
        </div>
        <span class="faint small">{{ ACTION[c.action] }} · {{ when(c.t) }}</span>
      </div>
    </div>
    <p v-else class="group-note">Пока правок не было. Здесь появятся создание, изменение и удаление событий из календаря.</p>
    <p v-if="error" class="group-note err">{{ error }}</p>
    <p class="group-note">«Отменить» возвращает событие, каким оно было: создание удаляет его, удаление создаёт заново, правка возвращает прежние данные. Хранятся последние 40 правок.</p>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { api } from '../lib/api'
import { reload } from '../lib/store'

const ACTION = { create: 'Создано', update: 'Изменено', delete: 'Удалено', undo: 'Отмена' }
const data = reactive({ items: [], pending: 0, error: null })
const busy = ref(false)
const error = ref('')
const when = (t) => new Date(t).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

async function load() {
  try { Object.assign(data, await api.changes()) } catch (e) { error.value = e.message }
}
async function run(fn) {
  busy.value = true; error.value = ''
  try { await fn(); await load(); reload() } catch (e) { error.value = e.message } finally { busy.value = false }
}
const undo = (c) => run(() => api.undoChange(c.id))
const flush = () => run(() => api.flushChanges())
load()
</script>

<style scoped>
.err { color: var(--red, #ff3b30); }
.warn { color: #b25e00; }
.small { font-size: 13px; }
</style>
