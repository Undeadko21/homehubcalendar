<template>
  <div>
    <h3 class="group-title">Другие календари (Teams, Битрикс24…)</h3>
    <div class="group">
      <template v-for="f in feeds" :key="f.id">
        <div class="row feed">
          <span class="lbl">{{ f.name || f.host }}
            <small class="muted block">{{ f.host }}</small>
            <small v-if="f.last_error" class="block err">Не обновляется{{ f.last_ok ? ' с ' + when(f.last_ok) : '' }}: {{ f.last_error }}</small>
            <small v-else-if="f.last_ok" class="block ok">Обновлён {{ when(f.last_ok) }}</small>
          </span>
          <span class="btns">
            <button class="btn" :disabled="busy" @click="startEdit(f)">Сменить ссылку</button>
            <button class="btn danger" :disabled="busy" @click="remove(f)">Удалить</button>
          </span>
        </div>
        <form v-if="edit === f.id" class="row stack editf" @submit.prevent="saveLink(f)">
          <input v-model="editName" class="inline" placeholder="Название" aria-label="Название подписки" />
          <input ref="editInput" v-model="editUrl" class="inline" type="password" autocomplete="off" autocapitalize="off"
                 placeholder="Новая ссылка на этот календарь (…/calendar.ics)" aria-label="Новая ссылка ICS" />
          <small class="muted">События, владельцы и назначения останутся — меняется только адрес. Если новая ссылка не откроется, прежняя сохранится. Оставьте поле ссылки пустым, чтобы поменять только название.</small>
          <span class="btns">
            <button class="btn filled" :disabled="busy || (!editUrl.trim() && editName.trim() === (f.name || ''))">{{ busy ? 'Проверяю…' : 'Сохранить' }}</button>
            <button type="button" class="btn" :disabled="busy" @click="edit = null">Отмена</button>
          </span>
        </form>
      </template>
      <form class="row stack" @submit.prevent="add">
        <input v-model="name" class="inline" placeholder="Название, например «Работа (Teams)»" aria-label="Название" />
        <input v-model="url" class="inline" type="password" autocomplete="off" autocapitalize="off"
               placeholder="Ссылка на календарь (…/calendar.ics)" aria-label="Ссылка ICS" />
        <button class="btn filled" :disabled="busy || !url.trim()">{{ busy ? 'Проверяю…' : 'Подключить' }}</button>
      </form>
    </div>
    <p v-if="msg" class="group-note" :class="isErr ? 'err' : 'ok'">{{ msg }}</p>
    <Help title="Как получить ссылку">
      <p>Подписка только для чтения. Outlook → Настройки → Календарь → Общие календари → «Опубликовать календарь» → ICS; Битрикс24 → Календарь → меню календаря → «Экспорт». Ссылка содержит секретный токен и хранится на сервере зашифрованной.</p>
      <p>После подключения выберите владельца календаря в разделе «Календари». Teams и Битрикс отдают изменения с задержкой, обычно до нескольких часов.</p>
    </Help>
  </div>
</template>

<script setup>
import Help from './Help.vue'
import { nextTick, onMounted, ref } from 'vue'
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

// Сменить ссылку (или название) у существующей подписки — календарь, его владельцы и назначения остаются.
const edit = ref(null)
const editUrl = ref('')
const editName = ref('')
const editInput = ref(null)
async function startEdit(f) {
  edit.value = edit.value === f.id ? null : f.id
  editUrl.value = ''
  editName.value = f.name || ''
  msg.value = ''
  await nextTick()
  const el = Array.isArray(editInput.value) ? editInput.value[0] : editInput.value
  el?.focus()
}
async function saveLink(f) {
  busy.value = true
  msg.value = ''
  try {
    const r = await api.saveFeed({ id: f.id, name: editName.value.trim(), url: editUrl.value.trim(), people: [] })
    isErr.value = !r.result.ok
    msg.value = r.result.ok ? `«${r.feed.name || r.feed.host}»: сохранено, событий ${r.result.objects}.` : 'Сохранено, но не загрузилось: ' + r.result.error
    edit.value = null
    await load()
    reload()
  } catch (e) { msg.value = e.message; isErr.value = true } finally { busy.value = false }
}
const when = (iso) => {
  const d = new Date(iso)
  const today = d.toDateString() === new Date().toDateString()
  return (today ? 'сегодня в ' : d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' }) + ' в ') + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

async function remove(f) {
  if (!confirm(`Отключить «${f.name || f.host}»? События из него пропадут из календаря.`)) return
  busy.value = true
  try { await api.deleteFeed(f.id); await load(); reload() } catch (e) { msg.value = e.message; isErr.value = true } finally { busy.value = false }
}
</script>

<style scoped>
.err { color: var(--red); }
.ok { color: var(--ok); }
.feed { align-items: flex-start; gap: 10px; flex-wrap: wrap; }
.feed .lbl { flex: 1 1 200px; min-width: 0; }
.btns { display: flex; gap: 6px; flex-wrap: wrap; }
.editf { gap: 8px; background: var(--fill); }
.block { display: block; }
.danger { color: var(--red); }
</style>
