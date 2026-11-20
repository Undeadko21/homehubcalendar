<template>
  <div v-if="supported">
    <h3 class="group-title">Уведомления в этом браузере</h3>
    <div class="group">
      <div class="row between">
        <label for="bp-on">Присылать в этот браузер</label>
        <input id="bp-on" type="checkbox" class="switch" :checked="on" :disabled="busy || denied" @change="toggle($event.target)" />
      </div>
      <div v-if="on" class="row stack">
        <span class="label">Чьи напоминания</span>
        <div class="choices" role="group" aria-label="Чьи напоминания присылать в этот браузер">
          <button v-for="p in ppl" :key="p.id" type="button" class="choice skip" :class="{ on: people.includes(p.id) }"
                  :aria-pressed="people.includes(p.id)" :disabled="busy" @click="togglePerson(p.id)">{{ p.emoji }} {{ p.name }}</button>
        </div>
        <p class="faint small">Никто не выбран — все. Срочное («некому везти») и сводка приходят всегда.</p>
      </div>
      <button v-if="on" class="row btn link" :disabled="busy" @click="test">Проверить — прислать уведомление</button>
    </div>
    <p v-if="denied" class="faint small pad">Браузер запретил уведомления для этого сайта — разрешите их в настройках браузера (значок замка у адреса).</p>
    <p v-else-if="msg" class="faint small pad">{{ msg }}</p>
    <p class="faint small pad">«Пора выезжать», напоминания о событиях, срочное и «кто что изменил» — как на телефоне.
      Работает, пока браузер открыт (вкладку можно закрыть). Для телефонов и Mac — приложения.</p>
  </div>
</template>

<script setup>
// Web Push (v0.21): подписка этого браузера → сервер раз в минуту шлёт подошедшие напоминания (backend/app/webpush.py).
import { computed, onMounted, ref } from 'vue'
import { api } from '../lib/api'
import { state } from '../lib/store'

const inApp = typeof window !== 'undefined' && (window.HomeHubApp || window.webkit?.messageHandlers?.homehub || /HomeHubApp\//.test(navigator.userAgent))
const supported = !inApp && typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
const on = ref(false)
const people = ref([])
const busy = ref(false)
const msg = ref('')
const denied = ref(supported && Notification.permission === 'denied')
const ppl = computed(() => (state.config?.people || []).filter((p) => !p.id.startsWith('_') && !p.hidden))

const keyBytes = (b64) => {
  const s = atob((b64 + '='.repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(s, (c) => c.charCodeAt(0))
}
const reg = () => navigator.serviceWorker.ready
const current = async () => (await reg()).pushManager.getSubscription()
const device = () => (/Mac/.test(navigator.platform) ? 'Mac' : /Win/.test(navigator.platform) ? 'Windows' : 'Компьютер') + ' · ' +
  (/Edg\//.test(navigator.userAgent) ? 'Edge' : /Firefox\//.test(navigator.userAgent) ? 'Firefox' : /Chrome\//.test(navigator.userAgent) ? 'Chrome' : 'Safari')

onMounted(async () => {
  if (!supported) return
  try {
    const s = await current()
    if (s) {
      const st = await api.pushStatus(s.endpoint)
      on.value = st.subscribed
      people.value = st.people || []
      if (!st.subscribed) await save(s)   // подписка браузера есть, а сервер её забыл (новая база) — восстановить молча
    }
  } catch { /* нет service worker (разработка) */ }
})

async function save(s) {
  await api.pushSubscribe(s.toJSON(), people.value, device())
  on.value = true
}

async function toggle(el) {
  const want = el.checked
  busy.value = true
  msg.value = ''
  try {
    if (want) {
      const perm = await Notification.requestPermission()
      if (perm !== 'granted') { denied.value = perm === 'denied'; msg.value = 'Без разрешения браузера уведомления не придут.'; return }
      const { key } = await api.pushKey()
      const s = (await current()) || await (await reg()).pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) })
      await save(s)
      msg.value = 'Готово. Нажмите «Проверить», чтобы увидеть, как выглядит уведомление.'
    } else {
      const s = await current()
      if (s) { await api.pushUnsubscribe(s.endpoint); await s.unsubscribe() }
      on.value = false
    }
  } catch (e) { msg.value = 'Не получилось: ' + e.message } finally {
    busy.value = false
    el.checked = on.value   // разрешение не дали или ошибка — переключатель показывает правду
  }
}

async function togglePerson(id) {
  people.value = people.value.includes(id) ? people.value.filter((x) => x !== id) : [...people.value, id]
  busy.value = true
  try { const s = await current(); if (s) await save(s) } catch (e) { msg.value = e.message } finally { busy.value = false }
}

async function test() {
  busy.value = true
  msg.value = ''
  try { const s = await current(); await api.pushTest(s.endpoint); msg.value = 'Отправлено — уведомление появится через пару секунд.' }
  catch (e) { msg.value = 'Не дошло: ' + e.message } finally { busy.value = false }
}
</script>

<style scoped>
.pad { padding: 0 16px; }
.between { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.choices { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.choice { border: 1px solid var(--line); background: var(--surface); color: var(--ink-2); border-radius: 999px; padding: 6px 12px; font-size: 14px; }
.choice.on { background: var(--red, #ff3b30); border-color: transparent; color: #fff; font-weight: 600; }
.choice:disabled { opacity: .6; }
</style>
