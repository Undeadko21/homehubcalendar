<template>
  <div>
    <div class="group">
      <div class="row">
        <span class="lbl">Состояние</span>
        <span v-if="!st" class="val muted">…</span>
        <span v-else-if="!st.configured" class="val muted">не подключено</span>
        <span v-else-if="st.last_error" class="val err">{{ st.last_error }}</span>
        <span v-else class="val muted">снимок обновлён {{ st.last_ok ? fmt(st.last_ok) : 'скоро' }}</span>
      </div>
      <form class="row" @submit.prevent="save">
        <input v-model="token" class="inline grow" type="password" autocomplete="off" autocapitalize="off"
               :placeholder="st?.configured ? 'токен сохранён; вставьте новый, чтобы заменить' : 'токен Яндекс.Диска'"
               aria-label="Токен Яндекс.Диска" />
        <button class="btn filled" :disabled="busy || !token.trim()">{{ busy ? 'Проверяю…' : 'Сохранить' }}</button>
      </form>
      <template v-if="st?.configured">
        <div v-if="inApp" class="row">
          <span class="lbl">Это приложение <small class="muted block">{{ appState }}</small></span>
          <button class="btn" :disabled="!st.code" @click="connectApp">{{ connected ? 'Переподключить' : 'Подключить' }}</button>
        </div>
        <div v-else-if="st.code" class="row stack">
          <span class="lbl">Код подключения <small class="muted block">для приложения на другом телефоне; дома проще нажать «Подключить» в самом приложении</small></span>
          <div class="code"><code>{{ st.code }}</code><button class="btn" @click="copy">{{ copied ? 'Скопировано' : 'Копировать' }}</button></div>
        </div>
        <div class="row">
          <button class="btn" :disabled="busy" @click="push">Обновить снимок сейчас</button>
          <button class="btn danger" :disabled="busy" @click="off">Отключить</button>
        </div>
      </template>
    </div>
    <p v-if="msg" class="group-note" :class="{ err: isErr }">{{ msg }}</p>
    <p class="group-note">
      Сервер кладёт зашифрованный снимок (виджет и напоминания на 7 дней) в папку приложения на Яндекс.Диске, а телефон
      читает его, когда не видит сервер дома. Читать снимок можно только с кодом подключения. Токен хранится на сервере и
      нужен только для записи в эту папку.
    </p>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../lib/api'

const st = ref(null)
const token = ref('')
const busy = ref(false)
const msg = ref('')
const isErr = ref(false)
const copied = ref(false)
const inApp = typeof window !== 'undefined' && !!window.HomeHubApp?.setCloud
const connected = ref(false)
const fmt = (s) => new Date(s).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

const appState = computed(() => (connected.value ? 'подключено: вне дома читает снимок из облака' : 'не подключено'))
function readApp() {
  try { connected.value = !!JSON.parse(window.HomeHubApp.cloudState()).connected } catch {}
}
async function load() { try { st.value = await api.cloud() } catch (e) { msg.value = e.message; isErr.value = true } }
onMounted(() => { load(); if (inApp) readApp() })

async function run(fn, ok) {
  busy.value = true
  msg.value = ''
  try {
    st.value = await fn()
    isErr.value = !!st.value.last_error
    msg.value = st.value.last_error ? '' : ok
  } catch (e) { msg.value = e.message; isErr.value = true } finally { busy.value = false }
}
async function save() {
  await run(() => api.saveCloud(token.value.trim()), 'Подключено. Снимок загружен на Диск.')
  if (!isErr.value) token.value = ''
}
const push = () => run(() => api.pushCloud(), 'Снимок обновлён.')
async function off() {
  if (!confirm('Отключить облако? Вне дома виджет и напоминания перестанут обновляться.')) return
  await run(() => api.saveCloud(null), 'Отключено.')
}
function connectApp() {
  try {
    window.HomeHubApp.setCloud(st.value.code)
    msg.value = 'Приложение подключено к облаку.'
    isErr.value = false
  } catch (e) { msg.value = 'Не удалось подключить: ' + e.message; isErr.value = true }
  setTimeout(readApp, 800)
}
async function copy() {
  try { await navigator.clipboard.writeText(st.value.code); copied.value = true; setTimeout(() => (copied.value = false), 2000) } catch {}
}
</script>

<style scoped>
.err { color: var(--red); }
.block { display: block; }
.code { display: flex; gap: 8px; align-items: center; }
.code code { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; background: var(--fill); padding: 6px 8px; border-radius: 8px; }
.danger { color: var(--red); }
.val { text-align: right; font-size: 14px; overflow-wrap: anywhere; max-width: 60%; }
</style>
