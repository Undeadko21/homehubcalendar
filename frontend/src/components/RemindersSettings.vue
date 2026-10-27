<template>
  <div>
    <div class="group">
      <label class="row">
        <span class="lbl">Напоминать <small class="muted block">уведомления на этом телефоне</small></span>
        <input v-model="cfg.enabled" type="checkbox" class="switch" @change="save" />
      </label>
      <template v-if="cfg.enabled">
        <label class="row">
          <span class="lbl">О поездках за</span>
          <select v-model.number="cfg.lead" class="sel" @change="save">
            <option v-for="m in LEADS" :key="m" :value="m">{{ m }} мин</option>
          </select>
        </label>
        <div class="row stack">
          <span class="lbl">Чьи поездки <small class="muted block">{{ cfg.people.length ? 'только выбранных' : 'всех взрослых' }}</small></span>
          <div class="chips">
            <button v-for="a in adults" :key="a.id" class="chip" :class="{ on: cfg.people.includes(a.id) }"
                    :style="{ '--c': a.color }" :aria-pressed="cfg.people.includes(a.id)" @click="toggle(a.id)">
              {{ a.emoji }} {{ a.name }}
            </button>
          </div>
        </div>
        <div class="row">
          <button class="btn" @click="test">Проверить уведомление</button>
        </div>
      </template>
    </div>
    <p v-if="cfg.enabled && !granted" class="group-note err">
      Android не разрешает приложению показывать уведомления.
      <button class="btn link" @click="ask">Разрешить</button>
    </p>
    <p class="group-note">
      Что приходит: «Отвезти Марка — в 10:10» за выбранное время до выезда, вечером накануне — конфликты и поездки без
      водителя на завтра, утром — дни рождения. Проверка идёт раз в 15 минут, интернет снаружи не нужен — только домашняя сеть.
      Если телефон долго не был дома, напоминания появятся, как только он вернётся в Wi-Fi.
    </p>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { state } from '../lib/store'

const LEADS = [10, 15, 30, 45, 60, 90, 120]
const adults = computed(() => (state.config?.people || []).filter((p) => !p.id.startsWith('_') && !p.needs_escort && !p.hidden))
const cfg = reactive({ enabled: false, lead: 30, people: [] })
const granted = ref(true)

function read() {
  try {
    const v = JSON.parse(window.HomeHubApp.getNotify())
    Object.assign(cfg, { enabled: !!v.enabled, lead: v.lead || 30, people: v.people || [] })
    granted.value = v.granted !== false
  } catch {}
}
read()

function save() {
  try {
    if (cfg.enabled) window.HomeHubApp.requestNotifications()
    window.HomeHubApp.setNotify(cfg.enabled, cfg.people.join(','), cfg.lead)
  } catch {}
  setTimeout(read, 1500)
}
function toggle(id) {
  const i = cfg.people.indexOf(id)
  if (i >= 0) cfg.people.splice(i, 1)
  else cfg.people.push(id)
  save()
}
function test() { try { window.HomeHubApp.testNotification() } catch {} }
function ask() { try { window.HomeHubApp.requestNotifications() } catch {}; setTimeout(read, 3000) }
</script>

<style scoped>
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  border: 1.5px solid var(--line); background: none; border-radius: 999px; padding: 6px 14px; font-size: 14px;
}
.chip.on { background: var(--c); border-color: var(--c); color: #fff; font-weight: 600; }
.err { color: var(--red); }
.block { display: block; }
</style>
