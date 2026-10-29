<template>
  <div>
    <h3 class="group-title">Другие календари (Teams, Битрикс24…)</h3>
    <div class="group">
      <div v-for="f in feeds" :key="f.id" class="row">
        <span class="lbl">{{ f.name || f.host }} <small class="muted block">{{ f.host }}</small></span>
        <button class="btn danger" :disabled="busy" @click="remove(f)">Удалить</button>
      </div>
      <form class="row stack" @submit.prevent="add">
        <input v-model="name" class="inline" placeholder="Название, например «Работа (Teams)»" aria-label="Название" />
        <input v-model="url" class="inline" type="password" autocomplete="off" autocapitalize="off"
               placeholder="Ссылка на календарь (…/calendar.ics)" aria-label="Ссылка ICS" />
        <button class="btn filled" :disabled="busy || !url.trim()">{{ busy ? 'Проверяю…' : 'Подключить' }}</button>
      </form>
    </div>
    <p v-if="msg" class="group-note" :class="isErr ? 'err' : 'ok'">{{ msg }}</p>
    <p class="group-note">
      Подписка только для чтения. Ссылку берут в самом календаре: Outlook → Настройки → Календарь → Общие календари →
      «Опубликовать календарь» → ICS; Битрикс24 → Календарь → меню календаря → «Экспорт». Ссылка содержит секретный токен и
      хранится на сервере зашифрованной. После подключения выберите владельца календаря в «Календарях». Teams и Битрикс отдают
      изменения с задержкой, обычно до нескольких часов.
    </p>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../lib/api'
import { reload } from '../lib/store'

const feeds = ref([])
const name = ref('')
const url = ref('')
const busy = ref(false)
const msg = ref('')
const isErr = ref(false)

async function load() { try { feeds.value = await api.feeds() } catch (e) { msg.value = e.message; isErr.value = true } }
onMounted(load)

async function add() {
  busy.value = true
  msg.value = ''
  try {
    const r = await api.saveFeed({ name: name.value, url: url.value.trim(), people: [] })
    isErr.value = !r.result.ok
    msg.value = r.result.ok ? `Подключено: событий ${r.result.objects}.` : 'Сохранено, но не загрузилось: ' + r.result.error
    name.value = ''
    url.value = ''
    await load()
    reload()
  } catch (e) { msg.value = e.message; isErr.value = true } finally { busy.value = false }
}

async function remove(f) {
  if (!confirm(`Отключить «${f.name || f.host}»? События из него пропадут из календаря.`)) return
  busy.value = true
  try { await api.deleteFeed(f.id); await load(); reload() } catch (e) { msg.value = e.message; isErr.value = true } finally { busy.value = false }
}
</script>

<style scoped>
.err { color: var(--red); }
.block { display: block; }
.danger { color: var(--red); }
</style>
