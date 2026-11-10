<template>
  <div v-if="st">
    <!-- Сводка -->
    <template v-if="part === 'status'">
      <div class="group">
        <div v-for="c in st.checks" :key="c.id" class="row">
          <i class="dot" :class="c.level" aria-hidden="true"></i>
          <span class="lbl">{{ c.title }} <small v-if="c.detail" class="muted block">{{ c.detail }}</small></span>
        </div>
        <div class="row">
          <button class="btn" :disabled="busy" @click="probe">Проверить снаружи</button>
          <span v-if="probed" class="val muted">{{ probed }}</span>
        </div>
      </div>
      <p v-if="err" class="group-note err">{{ err }}</p>
      <Help title="Как это устроено">
        <p>Дома приложения ходят прямо на сервер. Вне дома они сначала пробуют публичный адрес (через ваш VPS), а если он недоступен — читают зашифрованный снимок из облака Яндекс.Диска. Зелёные точки — всё работает, красные — звено оборвано.</p>
      </Help>
    </template>

    <!-- Адрес и доступ приложений -->
    <template v-if="part === 'address'">
      <h3 class="group-title">Публичный адрес</h3>
      <form class="group" @submit.prevent="savePublic">
        <div class="row stack">
          <input v-model="publicUrl" class="field" placeholder="https://имя.ru" autocapitalize="off" autocomplete="off" aria-label="Публичный адрес" />
          <button class="btn filled" :disabled="busy || publicUrl.trim() === st.public_url">Сохранить</button>
        </div>
      </form>
      <p class="group-note">По этому адресу приложения заходят вне дома; он попадает в код подключения.</p>

      <h3 class="group-title">Приложения и виджеты вне дома</h3>
      <div class="group">
        <label class="row">
          <span class="lbl">Читать с сервера <small class="muted block">свежие данные вместо облака раз в час</small></span>
          <input :checked="st.widget" type="checkbox" class="switch" @change="set({ widget: $event.target.checked })" />
        </label>
        <div v-if="st.widget" class="row">
          <span class="lbl">Токен «только чтение»</span>
          <button class="btn" :disabled="busy" @click="rotate('widget')">Выпустить новый</button>
        </div>
      </div>
      <p v-if="err" class="group-note err">{{ err }}</p>
      <Help>
        <p>Токен даёт приложениям читать сводку по публичному адресу, но не менять данные. После включения заново подключите приложения новым кодом из раздела «Облако Яндекс.Диска». Если токен попал не в те руки — выпустите новый, старый перестанет работать.</p>
      </Help>
    </template>

    <!-- Устройства и вход -->
    <template v-if="part === 'devices'">
      <h3 class="group-title">Вход по QR-коду</h3>
      <div class="group">
        <div class="row stack">
          <div class="qr-line">
            <button class="btn" :disabled="busy" @click="makeQr">{{ qr ? 'Новый код' : 'Показать код' }}</button>
            <span v-if="qr" class="muted small">осталось {{ left }} с</span>
          </div>
          <img v-if="qr" class="qr" :src="qr" alt="QR-код для входа" width="220" height="220" />
        </div>
      </div>
      <p class="group-note">Наведите камеру нового устройства: пароль вводить не нужно. Ссылка живёт 10 минут и срабатывает один раз.</p>
      <p v-if="err" class="group-note err">{{ err }}</p>

      <template v-if="dev && dev.pin">
        <h3 class="group-title">Устройства</h3>
        <div class="group">
          <div v-for="d in dev.sessions" :key="d.id" class="row">
            <span class="lbl">{{ d.label }}<b v-if="d.current" class="me"> · это устройство</b>
              <small class="muted block">{{ d.via }} · был {{ fmt(d.last) }} · {{ d.ip }}</small></span>
            <button class="btn" :disabled="busy" @click="revoke(d)">Отключить</button>
          </div>
          <div v-if="!dev.sessions.length" class="row"><span class="muted small">Пока никого нет.</span></div>
          <div class="row"><button class="btn" :disabled="busy" @click="revokeAll(true)">Отключить все, кроме этого</button></div>
        </div>
        <p class="group-note">Отключённому устройству придётся ввести пароль заново. Смена пароля отключает все устройства.{{ dev.legacy ? ' Кнопка выше также отключит устройства, которые входили давно и ещё не заходили после обновления.' : '' }}</p>
        <template v-if="dev.log.length">
          <h3 class="group-title">Журнал безопасности</h3>
          <div class="group">
            <div v-for="(e, i) in dev.log" :key="i" class="row">
              <span class="lbl">{{ e.text }} <small class="muted block">{{ fmt(e.at) }}{{ e.ip ? ' · ' + e.ip : '' }}</small></span>
            </div>
          </div>
        </template>
      </template>
      <p v-else-if="dev" class="group-note">Пароль на вход не задан, поэтому устройства не различаются.</p>
    </template>

    <!-- VPS и уведомления -->
    <template v-if="part === 'vps'">
      <h3 class="group-title">Сервер в интернете (VPS)</h3>
      <div class="group">
        <label class="row">
          <span class="lbl">Следить за VPS <small class="muted block">отчёты о диске и сертификате, копия настроек раз в сутки</small></span>
          <input :checked="st.vps.enabled" type="checkbox" class="switch" @change="set({ vps: $event.target.checked })" />
        </label>
        <template v-if="st.vps.enabled">
          <div class="row">
            <span class="lbl">Последний отчёт</span>
            <span v-if="!st.vps.report" class="val muted">ещё не было</span>
            <span v-else class="val muted">{{ fmt(st.vps.report.at) }} · диск {{ st.vps.report.disk_pct }}%{{ certText }}</span>
          </div>
          <div v-for="p in st.vps.problems" :key="p" class="row"><span class="val err">{{ p }}</span></div>
          <div class="row">
            <span class="lbl">Копия настроек VPS</span>
            <span v-if="st.vps.backup" class="val muted">{{ fmt(st.vps.backup.at) }}</span>
            <span v-else class="val muted">ещё нет</span>
            <a v-if="st.vps.backup" class="btn" href="/api/access/vps-backup" download>Скачать</a>
          </div>
          <div class="row">
            <span class="lbl">Токен VPS</span>
            <button class="btn" :disabled="busy" @click="rotate('vps')">Выпустить новый</button>
          </div>
        </template>
      </div>
      <template v-if="st.vps.enabled">
        <h3 class="group-title">Установка агента</h3>
        <div class="group">
          <div class="row stack">
            <div class="code"><code>{{ st.vps.install }}</code><button class="btn" @click="copy(st.vps.install)">{{ copied ? 'Скопировано' : 'Копировать' }}</button></div>
          </div>
        </div>
        <p class="group-note">Выполните команду на VPS под root один раз. Токен внутри — не показывайте её посторонним.</p>
      </template>

      <h3 class="group-title">Уведомления на телефон</h3>
      <div class="group">
        <label class="row">
          <span class="lbl">Сообщать о сбоях <small class="muted block">если туннель или домашний сервер не отвечают больше 10 минут</small></span>
          <input :checked="st.ntfy.enabled" type="checkbox" class="switch" @change="set({ ntfy: $event.target.checked })" />
        </label>
        <label v-if="st.ntfy.enabled" class="row">
          <span class="lbl">Сообщать о входах <small class="muted block">новый адрес, вход по QR и подбор пароля</small></span>
          <input :checked="st.ntfy.login" type="checkbox" class="switch" @change="set({ login_alerts: $event.target.checked })" />
        </label>
        <template v-if="st.ntfy.enabled">
          <div class="row stack">
            <span class="lbl">Тема для подписки <small class="muted block">приложение ntfy → «+» → вставьте тему</small></span>
            <div class="code"><code>{{ st.ntfy.topic }}</code><button class="btn" @click="copy(st.ntfy.topic)">Копировать</button></div>
          </div>
          <div class="row"><button class="btn" :disabled="busy" @click="test">Отправить пробное уведомление</button>
            <span v-if="tested" class="val muted">{{ tested }}</span></div>
        </template>
      </div>
      <p v-if="err" class="group-note err">{{ err }}</p>
      <p v-if="st.ntfy.enabled" class="group-note">Тема — как пароль: кто её знает, видит ваши уведомления. После включения повторите установку на VPS, чтобы агент узнал тему.</p>
    </template>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import QRCode from 'qrcode'
import { api } from '../lib/api'
import Help from './Help.vue'

const props = defineProps({ part: { type: String, default: 'status' } })

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
  if (props.part === 'devices') loadDevices()
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
.qr-line { display: flex; align-items: center; gap: 12px; }
.qr { display: block; margin: 8px 0 4px; border-radius: 10px; background: #fff; padding: 6px; align-self: center; }
.dot { width: 10px; height: 10px; border-radius: 50%; flex: none; background: var(--ink-3); }
.dot.ok { background: #34c759; }
.dot.warn { background: #ff9500; }
.dot.bad { background: #ff3b30; }
.me { color: var(--red); font-weight: 600; }
.lbl { flex: 1; min-width: 0; }
.block { display: block; font-weight: 400; font-size: 13px; }
.val { text-align: right; font-size: 14px; overflow-wrap: anywhere; max-width: 60%; }
.err { color: var(--red); }
.small { font-size: 13px; }
.row.stack { flex-direction: column; align-items: stretch; gap: 8px; }
.code { display: flex; gap: 8px; align-items: center; }
.code code { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; background: var(--fill); padding: 6px 8px; border-radius: 8px; }
.switch {
  appearance: none; width: 51px; height: 31px; border-radius: 16px; background: var(--fill); position: relative;
  transition: background .2s; flex: none; margin: 0; cursor: pointer;
}
.switch::after { content: ''; position: absolute; top: 2px; left: 2px; width: 27px; height: 27px; border-radius: 50%; background: #fff; box-shadow: 0 2px 6px rgba(0,0,0,.2); transition: transform .2s; }
.switch:checked { background: var(--ok); }
.switch:checked::after { transform: translateX(20px); }
</style>
