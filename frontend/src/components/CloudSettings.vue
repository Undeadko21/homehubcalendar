<template>
  <div>
    <h3 class="group-title">Облако</h3>
    <div class="group">
      <div class="row">
        <span class="lbl">Состояние</span>
        <span v-if="!st" class="val muted">…</span>
        <span v-else-if="!st.configured" class="val muted">не подключено</span>
        <span v-else-if="st.last_error" class="val err">{{ st.last_error }}</span>
        <span v-else-if="st.ops_error" class="val err">{{ st.ops_error }}</span>
        <span v-else class="val muted">снимок обновлён {{ st.last_ok ? fmt(st.last_ok) : 'скоро' }}</span>
      </div>
      <template v-if="st?.configured">
        <div class="row">
          <button class="btn" :disabled="busy" @click="push">Обновить снимок сейчас</button>
          <button class="btn danger" :disabled="busy" @click="off">Отключить</button>
        </div>
      </template>
    </div>
    <p v-if="msg" class="group-note" :class="{ err: isErr }">{{ msg }}</p>

    <!-- Токен: кнопкой или вручную -->
    <h3 class="group-title">Токен Яндекс.Диска</h3>
    <div class="group">
      <div v-if="st?.client_id" class="row">
        <span class="lbl">Получить автоматически <small class="muted block">откроется Яндекс, нажмите «Разрешить» — токен сохранится сам</small></span>
        <a class="btn filled" :href="authUrl">Получить токен</a>
      </div>
      <form class="row" @submit.prevent="save">
        <input v-model="token" class="inline grow" type="password" autocomplete="off" autocapitalize="off"
               :placeholder="st?.configured ? 'токен сохранён; вставьте новый, чтобы заменить' : 'или вставьте токен вручную'"
               aria-label="Токен Яндекс.Диска" />
        <button class="btn" :disabled="busy || !token.trim()">{{ busy ? 'Проверяю…' : 'Сохранить' }}</button>
      </form>
      <form class="row stack" @submit.prevent="saveClient">
        <span class="lbl">ID приложения <small class="muted block">ClientID с oauth.yandex.ru — нужен один раз, чтобы работала кнопка «Получить токен»</small></span>
        <div class="code">
          <input v-model="clientId" class="field grow-in" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="32 знака" aria-label="ID приложения Яндекса" />
          <button class="btn" :disabled="busy || clientId.trim() === (st?.client_id || '')">Сохранить</button>
        </div>
      </form>
    </div>
    <Help title="Как настроить кнопку «Получить токен» (один раз)">
      <p>1. Откройте <a href="https://oauth.yandex.ru/client/new" target="_blank" rel="noopener">oauth.yandex.ru → Создать приложение</a> (в том аккаунте, где ваш Диск). Платформа — «Веб-сервисы».</p>
      <p>2. В поле Redirect URI (Callback URL) добавьте адрес: <code class="sel">{{ redirect }}</code>
        <button class="btn mini" @click="copyText(redirect)">Копировать</button>
        <br>Если открываете календарь и дома, и через интернет — добавьте оба адреса (вторым строкой).</p>
      <p>3. Доступы: «Яндекс.Диск REST API» — «Доступ к папке приложения на Диске» (или «Запись в любом месте на Диске») и «Чтение всего Диска».</p>
      <p>4. Скопируйте ClientID приложения в поле «ID приложения» выше и сохраните. Дальше токен получается одной кнопкой — в том числе когда старый истечёт.</p>
    </Help>

    <!-- Подключение устройств -->
    <template v-if="st?.configured && st.code">
      <h3 class="group-title">Подключить устройство</h3>
      <div class="group">
        <div v-if="inApp" class="row">
          <span class="lbl">Это приложение <small class="muted block">{{ appState }}</small></span>
          <button class="btn" :disabled="!st.code" @click="connectApp">{{ connected ? 'Переподключить' : 'Подключить' }}</button>
        </div>
        <div class="row stack">
          <span class="lbl">QR-код для нового устройства <small class="muted block">наведите камеру телефона — откроется страница с кнопкой «Открыть в приложении»</small></span>
          <div class="qr-line">
            <button class="btn" @click="toggleQr">{{ qr ? 'Скрыть' : 'Показать QR-код' }}</button>
          </div>
          <img v-if="qr" class="qr" :src="qr" alt="QR-код подключения" width="240" height="240" />
          <small v-if="qr" class="muted block">Ссылка ведёт на {{ connectHost }}. Уже подключённые устройства продолжают работать как раньше — им ничего делать не нужно.</small>
        </div>
        <div class="row stack">
          <span class="lbl">Код подключения <small class="muted block">если удобнее вставить вручную</small></span>
          <div class="code"><code>{{ st.code }}</code><button class="btn" @click="copy">{{ copied ? 'Скопировано' : 'Копировать' }}</button></div>
        </div>
      </div>
      <p class="group-note">Код и QR — как ключ от дома: показывайте их только своим.</p>

      <template v-if="st.alice">
        <h3 class="group-title">Навык Алисы</h3>
        <div class="group">
          <div class="row stack">
            <small class="muted block">Значения для переменных функции HOMEHUB_URL и HOMEHUB_KEY (инструкция в папке alice/).</small>
            <div class="code"><code>{{ st.alice.url }}</code><button class="btn" @click="copyText(st.alice.url)">Копировать</button></div>
            <div class="code"><code>{{ st.alice.key }}</code><button class="btn" @click="copyText(st.alice.key)">Копировать</button></div>
            <template v-if="st.alice.token">
              <small class="muted block">Необязательно: HOMEHUB_TOKEN — тогда Алиса сможет и записывать («добавь на завтра в 18:00 врача Марку»). Даёт доступ к папке приложения на Диске.</small>
              <div class="code"><code>{{ tokenShown ? st.alice.token : '••••••••••••' }}</code>
                <button class="btn" @click="tokenShown = !tokenShown">{{ tokenShown ? 'Скрыть' : 'Показать' }}</button>
                <button class="btn" @click="copyText(st.alice.token)">Копировать</button></div>
            </template>
          </div>
        </div>
      </template>
    </template>

    <Help title="Как работает облако">
      <p>Сервер кладёт зашифрованный снимок (виджет и напоминания на 7 дней) в папку приложения на Яндекс.Диске, а телефон читает его, когда не видит сервер дома. Читать снимок можно только с кодом подключения.</p>
      <p>Вне дома приложение может менять назначения поездок и списки: оно кладёт команды в ту же папку, а сервер их подхватывает (до минуты). Сюда же раз в сутки пишется зашифрованная копия базы.</p>
    </Help>
  </div>
</template>

<script setup>
import { copyToClipboard } from '../lib/clipboard'
import { computed, onMounted, ref } from 'vue'
import QRCode from 'qrcode'
import Help from './Help.vue'
import { api } from '../lib/api'

const st = ref(null)
const token = ref('')
const busy = ref(false)
const msg = ref('')
const isErr = ref(false)
const copied = ref(false)
const tokenShown = ref(false)
const inApp = typeof window !== 'undefined' && !!window.HomeHubApp?.setCloud
const connected = ref(false)
async function copyText(t) {
  const ok = await copyToClipboard(t)
  msg.value = ok ? 'Скопировано.' : 'Не удалось скопировать автоматически: нажмите на значение, чтобы выделить, и скопируйте вручную.'
  isErr.value = !ok
}
const fmt = (s) => new Date(s).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

const appState = computed(() => (connected.value ? 'подключено: вне дома читает снимок из облака' : 'не подключено'))
function readApp() {
  try { connected.value = !!JSON.parse(window.HomeHubApp.cloudState()).connected } catch {}
}
const clientId = ref('')
const pub = ref('')
async function load() {
  try {
    st.value = await api.cloud()
    clientId.value = st.value.client_id || ''
  } catch (e) { msg.value = e.message; isErr.value = true }
  api.access().then((a) => { pub.value = a.public_url || '' }).catch(() => {})
}
// Возврат с Яндекса (main.js сохранил токен и оставил результат)
try {
  const r = sessionStorage.getItem('cloudOauth')
  if (r) { sessionStorage.removeItem('cloudOauth'); isErr.value = r.startsWith('err:'); msg.value = r.slice(4) }
} catch { /* без хранилища */ }
const redirect = `${location.origin}/yandex-oauth`
const authUrl = computed(() => `https://oauth.yandex.ru/authorize?response_type=token&force_confirm=yes&client_id=${encodeURIComponent(st.value?.client_id || '')}&redirect_uri=${encodeURIComponent(redirect)}`)
async function saveClient() {
  await run(() => api.saveCloudClient(clientId.value.trim()), 'ID приложения сохранён — теперь можно нажать «Получить токен».')
}
// QR ведёт на страницу /connect публичного адреса (или текущего, если его нет); сам код — после «#», на сервер он не уходит.
const qr = ref('')
const connectBase = computed(() => pub.value || location.origin)
const connectHost = computed(() => connectBase.value.replace(/^https?:\/\//, ''))
async function toggleQr() {
  if (qr.value) { qr.value = ''; return }
  qr.value = await QRCode.toDataURL(`${connectBase.value}/connect#${st.value.code}`, { margin: 1, width: 480, errorCorrectionLevel: 'L' })
}
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
  const ok = await copyToClipboard(st.value.code)
  copied.value = ok
  msg.value = ok ? '' : 'Не удалось скопировать автоматически: нажмите на код, чтобы выделить его, и скопируйте вручную.'
  isErr.value = !ok
  if (ok) setTimeout(() => (copied.value = false), 2000)
}
</script>

<style scoped>
.qr-line { display: flex; align-items: center; gap: 12px; }
.qr { display: block; margin: 6px auto 2px; border-radius: 10px; background: #fff; padding: 6px; }
.lbl { flex: 1; min-width: 0; }
.row.stack { flex-direction: column; align-items: stretch; gap: 8px; }
a.btn { text-decoration: none; }
.mini { padding: 2px 6px; font-size: 13px; }
.grow-in { flex: 1; min-width: 0; }
.sel { user-select: all; -webkit-user-select: all; font-size: 12px; background: var(--fill); padding: 2px 6px; border-radius: 6px; overflow-wrap: anywhere; }
.inline { border: 0; background: none; text-align: right; flex: 1; min-width: 0; padding: 4px 0; outline: none; color: inherit; font: inherit; }
.inline::placeholder { color: var(--ink-3); }
.grow { text-align: left; }
.err { color: var(--red); }
.block { display: block; }
.code { display: flex; gap: 8px; align-items: center; }
.code code { user-select: all; -webkit-user-select: all; cursor: text; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; background: var(--fill); padding: 6px 8px; border-radius: 8px; }
.danger { color: var(--red); }
.val { text-align: right; font-size: 14px; overflow-wrap: anywhere; max-width: 60%; }
</style>
