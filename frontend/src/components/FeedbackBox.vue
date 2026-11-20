<template>
  <div>
    <h3 class="group-title">Сообщить о проблеме</h3>
    <div class="group">
      <template v-if="!open">
        <button class="row btn link" @click="open = true">Что-то не так — написать разработчику</button>
      </template>
      <div v-else class="row stack">
        <textarea v-model="text" class="in" rows="4" maxlength="1000" placeholder="Что случилось и где? Например: «на неделе не открывается карточка бассейна»"></textarea>
        <label class="small faint att"><input v-model="attach" type="checkbox" /> Приложить сведения: экран, версию, устройство и последние ошибки</label>
        <div class="acts">
          <button class="btn" :disabled="busy" @click="open = false">Отмена</button>
          <button class="btn filled" :disabled="busy || text.trim().length < 3" @click="send">Отправить</button>
        </div>
      </div>
    </div>
    <p v-if="msg" class="faint small pad">{{ msg }}</p>
    <div v-if="items.length" class="group">
      <div v-for="f in items" :key="f.id" class="row between">
        <span class="t"><span class="faint small d">{{ when(f.at) }}</span>{{ f.text }}</span>
        <button class="btn link small" :aria-label="'Удалить сообщение ' + f.text" @click="del(f.id)">Удалить</button>
      </div>
    </div>
    <p v-if="open" class="faint small pad">Сообщение остаётся на домашнем сервере; утренний дозор его прочитает, поищет причину и подготовит исправление.
      В открытый репозиторий текст не попадает.</p>
  </div>
</template>

<script setup>
// «Сообщить о проблеме» (v0.21): → /api/feedback (дома) → /api/watch → утренний дозор (backend/app/feedback.py).
import { ref } from 'vue'
import { api } from '../lib/api'
import { state } from '../lib/store'
import { problems } from '../lib/report'

const open = ref(false)
const text = ref('')
const attach = ref(true)
const busy = ref(false)
const msg = ref('')
const items = ref([])
const when = (s) => new Date(s).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
const device = () => (/iPhone|iPad/.test(navigator.userAgent) ? 'iPhone/iPad' : /Android/.test(navigator.userAgent) ? 'Android'
  : /Mac/.test(navigator.platform) ? 'Mac' : 'компьютер') + (/HomeHubApp\//.test(navigator.userAgent) ? ' (приложение)' : ' (браузер)')

async function load() { try { items.value = (await api.feedbackList()).items } catch { /* необязательно */ } }
load()

async function send() {
  busy.value = true
  msg.value = ''
  try {
    const body = { text: text.value.trim() }
    if (attach.value) Object.assign(body, { screen: state.view || '', version: state.config?.version || '', device: device(), errors: [...problems.list] })
    await api.feedbackSend(body)
    text.value = ''
    open.value = false
    msg.value = 'Отправлено. Дозор разберёт утром.'
    await load()
  } catch (e) { msg.value = 'Не отправилось: ' + e.message } finally { busy.value = false }
}

async function del(id) {
  try { await api.feedbackDelete(id); await load() } catch (e) { msg.value = e.message }
}
</script>

<style scoped>
.in { width: 100%; box-sizing: border-box; font: inherit; border: 0; background: var(--fill); color: var(--ink); border-radius: 10px; padding: 10px; resize: vertical; }
.att { display: flex; gap: 8px; align-items: center; margin-top: 8px; }
.att input { accent-color: var(--accent, #ff3b30); }
.acts { display: flex; gap: 8px; justify-content: flex-end; margin-top: 10px; }
.between { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.t { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.d { display: block; }
.pad { padding: 0 16px; }
</style>
