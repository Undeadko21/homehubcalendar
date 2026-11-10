<template>
  <div v-if="st">
    <div class="group">
      <div class="row"><span class="lbl">Публичный адрес <small class="muted block">по нему приложения ходят вне дома; попадает в код подключения</small></span></div>
      <form class="row" @submit.prevent="savePublic" style="gap:8px">
        <input v-model="publicUrl" class="field" style="flex:1;min-width:0" placeholder="https://имя.ru" autocapitalize="off" autocomplete="off" aria-label="Публичный адрес" />
        <button class="btn" :disabled="busy || publicUrl.trim() === st.public_url">Сохранить</button>
      </form>
      <label class="row">
        <span class="lbl">Виджетам и приложениям — чтение с сервера
          <small class="muted block">Токен «только чтение»: виджеты и приложения берут свежую сводку прямо с сервера вне дома, а не из облака раз в час. Изменить данные он не может. После включения заново подключите приложения кодом из раздела «Облако» (в нём появится адрес и токен).</small></span>
        <input :checked="st.widget" type="checkbox" class="switch" @change="set({ widget: $event.target.checked })" />
      </label>
      <div v-if="st.widget" class="row">
        <span class="lbl">Токен виджетов <small class="muted block">если он попал не в те руки — выпустите новый; старый перестанет работать</small></span>
        <button class="btn" :disabled="busy" @click="rotate('widget')">Выпустить новый</button>
      </div>
    </div>
    <p v-if="err" class="group-note err">{{ err }}</p>

    <div class="group">
      <div class="row stack">
        <span class="lbl">Вход по QR-коду <small class="muted block">покажите код на уже открытом календаре и наведите камеру нового устройства: пароль вводить не нужно. Ссылка живёт 10 минут и срабатывает один раз.</small></span>
        <div class="qr-line">
          <button class="btn" :disabled="busy" @click="makeQr">{{ qr ? 'Новый код' : 'Показать код' }}</button>
          <span v-if="qr" class="muted small">осталось {{ left }} с</span>
        </div>
        <img v-if="qr" class="qr" :src="qr" alt="QR-код для входа" width="220" height="220" />
      </div>
    </div>

    <h3 class="group-title">Сервер в интернете (VPS)</h3>
    <div class="group">
      <label class="row">
        <span class="lbl">Следить за VPS <small class="muted block">агент на VPS проверяет туннель каждые 5 минут, присылает отчёт (диск, сертификат) и раз в сутки копию настроек</small></span>
        <input :checked="st.vps.enabled" type="checkbox" class="switch" @change="set({ vps: $event.target.checked })" />
      </label>
      <template v-if="st.vps.enabled">
        <div class="row stack">
          <span class="lbl">Установка на VPS <small class="muted block">выполните на VPS под root (один раз); токен внутри команды — не показывайте её посторонним</small></span>
          <div class="code"><code>{{ st.vps.install }}</code><button class="btn" @click="copy(st.vps.install)">{{ copied ? 'Скопировано' : 'Копировать' }}</button></div>
        </div>
        <div class="row">
          <span class="lbl">Последний отчёт</span>
          <span v-if="!st.vps.report" class="val muted">ещё не было</span>
          <span v-else class="val muted">{{ fmt(st.vps.report.at) }} · диск {{ st.vps.report.disk_pct }}%{{ certText }}</span>
        </div>
        <div v-for="p in st.vps.problems" :key="p" class="row"><span class="val err">{{ p }}</span></div>
        <div class="row">
          <span class="lbl">Копия настроек VPS <small class="muted block">Caddyfile, ключ туннеля, правила; попадает в ежедневную копию на Диске</small></span>
          <span v-if="st.vps.backup" class="val muted">{{ fmt(st.vps.backup.at) }}</span>
          <span v-else class="val muted">ещё нет</span>
          <a v-if="st.vps.backup" class="btn" href="/api/access/vps-backup" download>Скачать</a>
        </div>
        <div class="row">
          <span class="lbl">Токен VPS</span>
          <button class="btn" :disabled="busy" @click="rotate('vps')">Выпустить новый</button>
        </div>
      </template>
      <label class="row">
        <span class="lbl">Уведомление «дом недоступен» <small class="muted block">приходит на телефон через бесплатное приложение ntfy, если туннель или домашний сервер не отвечают больше 10 минут</small></span>
        <input :checked="st.ntfy.enabled" type="checkbox" class="switch" @change="set({ ntfy: $event.target.checked })" />
      </label>
      <label v-if="st.ntfy.enabled" class="row">
        <span class="lbl">Сообщать о входах <small class="muted block">новый адрес, вход по QR и подбор пароля — сразу на телефон</small></span>
        <input :checked="st.ntfy.login" type="checkbox" class="switch" @change="set({ login_alerts: $event.target.checked })" />
      </label>
      <template v-if="st.ntfy.enabled">
        <div class="row stack">
          <span class="lbl">Как получать <small class="muted block">установите приложение ntfy, нажмите «+» и подпишитесь на тему:</small></span>
          <div class="code"><code>{{ st.ntfy.topic }}</code><button class="btn" @click="copy(st.ntfy.topic)">Копировать</button></div>
          <small class="muted block">Тема — как пароль: кто её знает, видит ваши уведомления. После включения повторите установку на VPS, чтобы агент узнал тему.</small>
        </div>
        <div class="row"><button class="btn" :disabled="busy" @click="test">Отправить пробное уведомление</button>
          <span v-if="tested" class="val muted">{{ tested }}</span></div>
      </template>
    </div>

    <template v-if="dev && dev.pin">
      <h3 class="group-title">Устройства, вошедшие в календарь</h3>
      <div class="group">
        <div v-for="d in dev.sessions" :key="d.id" class="row">
          <span class="lbl">{{ d.label }}<b v-if="d.current" class="me"> · это устройство</b>
            <small class="muted block">{{ d.via }} · был {{ fmt(d.last) }} · {{ d.ip }}</small></span>
          <button class="btn" :disabled="busy" @click="revoke(d)">Отключить</button>
        </div>
        <div v-if="!dev.sessions.length" class="row"><span class="muted small">Пока никого нет.</span></div>
        <div class="row stack">
          <button class="btn" :disabled="busy" @click="revokeAll(true)">Отключить все, кроме этого</button>
          <small class="muted block">Отключённому устройству придётся ввести пароль заново.{{ dev.legacy ? ' Кнопка также отключит устройства, которые входили давно и ещё не заходили после обновления.' : '' }} Смена пароля отключает все устройства.</small>
        </div>
      </div>
      <template v-if="dev.log.length">
        <h3 class="group-title">Журнал безопасности</h3>
        <div class="group">
          <div v-for="(e, i) in dev.log" :key="i" class="row">
            <span class="lbl">{{ e.text }} <small class="muted block">{{ fmt(e.at) }}{{ e.ip ? ' · ' + e.ip : '' }}</small></span>
          </div>
        </div>
      </template>
    </template>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import QRCode from 'qrcode'
import { api } from '../lib/api'

const st = ref(null)
const publicUrl = ref('')
const busy = ref(false)
const err = ref('')
const copied = ref(false)
const tested = ref('')
const qr = ref('')
const dev = ref(null)
const probed = ref('')
const left = ref(0)
let timer = null

const fmt = (iso) => new Date(iso).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
const certText = computed(() => {
  const c = st.value?.vps.report?.certs || {}
  const k = Object.keys(c)
  return k.length ? ' · сертификат ' + k.map((n) => `${n}: ${c[n]} дн.`).join(', ') : ''
})

async function loadDevices() {
  try { dev.value = await api.sessions() } catch { /* список устройств необязателен */ }
}
async function probe() {
  busy.value = true; err.value = ''; probed.value = ''
  try {
    const r = await api.probeAccess()
    st.value = { ...st.value, checks: r.checks }
    probed.value = r.probe.ok ? `отвечает за ${r.probe.ms} мс` : `не отвечает (${r.probe.error})`
  } catch (e) { err.value = String(e.message || e) } finally { busy.value = false }
}
async function revoke(d) {
  if (!confirm(d.current ? 'Отключить это устройство? Придётся войти заново.' : `Отключить «${d.label}»?`)) return
  busy.value = true; err.value = ''
  try {
    const r = await api.revokeSession(d.id)
    if (r.was_current) location.reload()
    dev.value = r
  } catch (e) { err.value = String(e.message || e) } finally { busy.value = false }
}
async function revokeAll(keep) {
  if (!confirm('Отключить все устройства, кроме этого?')) return
  busy.value = true; err.value = ''
  try { dev.value = await api.revokeAll(keep); await load() } catch (e) { err.value = String(e.message || e) } finally { busy.value = false }
}
async function load() {
  loadDevices()
  try {
    st.value = await api.access()
    publicUrl.value = st.value.public_url || (location.protocol === 'https:' ? location.origin : '')
  } catch (e) { err.value = String(e.message || e) }
}
async function run(fn) {
  busy.value = true; err.value = ''
  try { st.value = await fn() } catch (e) { err.value = String(e.message || e) } finally { busy.value = false }
}
const set = (body) => run(() => api.putAccess(body))
const rotate = (which) => confirm('Выпустить новый токен? Старый перестанет работать.') && run(() => api.rotateAccess(which))
const savePublic = () => run(() => api.putAccess({ public_url: publicUrl.value.trim() }))

async function makeQr() {
  busy.value = true; err.value = ''
  try {
    const r = await api.loginQr()
    qr.value = await QRCode.toDataURL(r.url, { margin: 1, width: 440, errorCorrectionLevel: 'M' })
    left.value = r.ttl
    clearInterval(timer)
    timer = setInterval(() => { if (--left.value <= 0) { qr.value = ''; clearInterval(timer) } }, 1000)
  } catch (e) { err.value = String(e.message || e) } finally { busy.value = false }
}
async function copy(text) {
  try { await navigator.clipboard.writeText(text); copied.value = true; setTimeout(() => (copied.value = false), 1500) } catch { /* буфер недоступен */ }
}
async function test() {
  busy.value = true; tested.value = ''
  try { await api.ntfyTest(); tested.value = 'отправлено' } catch (e) { tested.value = String(e.message || e) } finally { busy.value = false }
}
onMounted(load)
onBeforeUnmount(() => clearInterval(timer))
</script>

<style scoped>
.dot { width: 10px; height: 10px; border-radius: 50%; flex: none; background: var(--ink-3); }
.dot.ok { background: #34c759; }
.dot.warn { background: #ff9500; }
.dot.bad { background: #ff3b30; }
.me { color: var(--red); font-weight: 600; }
.qr-line { display: flex; align-items: center; gap: 12px; }
.qr { display: block; margin: 8px 0 4px; border-radius: 10px; background: #fff; padding: 6px; }
</style>
