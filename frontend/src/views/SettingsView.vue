<template>
  <div class="settings">
    <section v-for="acc in accounts" :key="acc.id" id="accounts">
      <h2>Учётная запись Яндекса</h2>
      <p class="muted">
        Нужен логин и <strong>пароль приложения</strong>, а не основной пароль. Создайте его на
        <a href="https://id.yandex.ru/security/app-passwords" target="_blank" rel="noopener">id.yandex.ru → Пароли приложений</a>,
        тип «Календарь». Пароль хранится только на вашем сервере.
      </p>
      <form class="account" @submit.prevent="saveAccount(acc)">
        <label>Логин
          <input v-model="acc.username" type="email" autocomplete="username" autocapitalize="off" placeholder="ivanov@yandex.ru" />
        </label>
        <label>Пароль приложения
          <input v-model="acc.password" type="password" autocomplete="new-password"
                 :placeholder="acc.has_password ? 'сохранён — оставьте пустым, чтобы не менять' : 'вставьте пароль приложения'" />
        </label>
        <button class="btn primary" :disabled="acc.busy || !acc.username">{{ acc.busy ? 'Проверяю…' : 'Сохранить и подключить' }}</button>
        <p v-if="acc.result" :class="acc.result.ok ? 'ok' : 'err'">
          {{ acc.result.ok ? `Подключено: календарей ${acc.result.calendars}, записей ${acc.result.objects}.` : 'Не удалось подключиться: ' + acc.result.error }}
        </p>
      </form>
    </section>

    <section>
      <h2>Синхронизация</h2>
      <p v-if="!sources.length" class="muted">
        Источники ещё не настроены. Добавьте их в файл config.yaml на сервере (см. README).
      </p>
      <ul class="sources">
        <li v-for="s in sources" :key="s.source_id" :class="{ bad: s.last_error }">
          <strong>{{ s.source_id }}</strong>
          <span v-if="s.last_error" class="err">Ошибка: {{ s.last_error }}</span>
          <span v-else class="muted">
            {{ s.last_ok ? 'обновлено ' + fmt(s.last_ok) : 'ещё не обновлялось' }}, записей: {{ s.objects_count }}
          </span>
        </li>
      </ul>
      <button class="btn" :disabled="busy" @click="sync">{{ busy ? 'Обновляю…' : 'Обновить сейчас' }}</button>
    </section>

    <section>
      <h2>Люди</h2>
      <div class="people">
        <div v-for="p in editPeople" :key="p.id" class="person">
          <input v-model="p.color" type="color" :aria-label="'Цвет: ' + p.name" @change="savePerson(p)" />
          <input v-model="p.emoji" class="emoji" maxlength="4" placeholder="🙂" aria-label="Значок" @change="savePerson(p)" />
          <input v-model="p.name" class="name" aria-label="Имя" @change="savePerson(p)" />
          <label class="chk"><input v-model="p.hidden" type="checkbox" @change="savePerson(p)" /> скрыть</label>
          <button class="btn icon" :aria-label="'Удалить ' + p.name" @click="removePerson(p)">✕</button>
          <input v-model="p.keywords" class="keywords" :aria-label="'Слова автопривязки: ' + p.name"
                 placeholder="Слова для автопривязки через запятую, например: Марк, бассейн, садик"
                 @change="savePerson(p)" />
        </div>
      </div>
      <p class="faint small">
        Если слово встречается в названии события из любого календаря, событие появится и у этого человека.
      </p>
      <form class="add" @submit.prevent="addPerson">
        <input v-model="newName" placeholder="Имя, например «Бабушка»" aria-label="Имя нового человека" />
        <button class="btn" :disabled="!newName.trim()">Добавить человека</button>
      </form>
    </section>

    <section>
      <h2>Календари</h2>
      <p class="muted">
        Отметьте, чьи события в календаре, — можно несколько человек. Изменения сохраняются сразу
        и не сбрасываются при синхронизации. Участников отдельного события можно поменять в его карточке.
      </p>
      <div class="table">
        <div v-for="c in editCals" :key="c.key" class="crow" :class="{ hidden: c.hidden }">
          <span class="swatch" :style="{ background: colorOf(c) }"></span>
          <span class="cname">{{ c.name }}<small class="faint">{{ c.people.length ? '' : 'нет владельца — события попадут в «Без владельца»' }}</small></span>
          <div class="flags">
            <label class="chk"><input v-model="c.private" type="checkbox" @change="patch(c, { private: c.private })" /> только «занят»</label>
            <label class="chk"><input v-model="c.hidden" type="checkbox" @change="patch(c, { hidden: c.hidden })" /> скрыть</label>
          </div>
          <PeoplePicker v-model="c.people" class="owners" :label="'Чей календарь ' + c.name"
                        @update:model-value="(v) => patch(c, { people: v })" />
        </div>
        <p v-if="!editCals.length" class="muted">Календари появятся после первой синхронизации.</p>
      </div>
    </section>

    <section>
      <h2>Экран на стене</h2>
      <p class="muted">Откройте эту ссылку на планшете в полноэкранном режиме. Ночью экран приглушается, данные обновляются сами.</p>
      <code class="link">{{ kioskUrl }}</code>
      <p class="faint small">Добавьте <code>&amp;rotate=60</code>, чтобы каждую минуту переключаться между «Сегодня» и «Лентой».</p>
    </section>

    <p class="faint small">Версия {{ state.config?.version }}</p>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '../lib/api'
import { state, reload, syncNow } from '../lib/store'
import PeoplePicker from '../components/PeoplePicker.vue'

const busy = ref(false)
const newName = ref('')
const sources = computed(() => state.status?.sources || [])
const editPeople = ref([])
const editCals = ref([])
const accounts = ref([])

watch(() => state.config, (c) => {
  editPeople.value = (c?.people || []).filter((p) => !p.id.startsWith('_')).map((p) => ({ ...p, hidden: !!p.hidden }))
  editCals.value = (c?.calendars || []).map((x) => ({ ...x, people: [...(x.people || [])], hidden: !!x.hidden, private: !!x.private }))
  const prev = Object.fromEntries(accounts.value.map((a) => [a.id, a]))
  accounts.value = (c?.accounts || []).map((a) => ({ ...a, password: '', busy: false, result: prev[a.id]?.result || null }))
}, { immediate: true })

const kioskUrl = computed(() => `${location.origin}/?kiosk&view=today`)
const fmt = (s) => new Date(s).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
const colorOf = (c) => editPeople.value.find((p) => p.id === c.people[0])?.color || c.color || '#8a94a6'

async function sync() {
  busy.value = true
  try { await syncNow() } finally { busy.value = false }
}
async function saveAccount(acc) {
  acc.busy = true
  acc.result = null
  try {
    const res = await api.saveAccount(acc.id, acc.username, acc.password || null)
    acc.result = res
    acc.password = ''
    await reload()
  } catch (e) {
    acc.result = { ok: false, error: e.message }
  } finally {
    acc.busy = false
  }
}
async function savePerson(p) {
  await api.savePerson({ ...p, hidden: !!p.hidden, sort: Number(p.sort) || 0, keywords: p.keywords || '' })
  await reload()
}
async function removePerson(p) {
  if (!confirm(`Удалить «${p.name}»? Его календари и события останутся у других владельцев или без владельца.`)) return
  await api.deletePerson(p.id)
  await reload()
}
async function addPerson() {
  const name = newName.value.trim()
  const id = translit(name) || 'p' + Date.now()
  const palette = ['#4f7cff', '#e0457b', '#22a06b', '#e8a400', '#b45cf0', '#0fa5b5', '#f2643d']
  await api.savePerson({ id, name, color: palette[editPeople.value.length % palette.length], emoji: '', sort: editPeople.value.length, hidden: false, keywords: '' })
  newName.value = ''
  await reload()
}
async function patch(c, fields) {
  await api.patchCalendar(c.key, fields)
  await reload()
}
function translit(s) {
  const map = { а:'a',б:'b',в:'v',г:'g',д:'d',е:'e',ё:'e',ж:'zh',з:'z',и:'i',й:'y',к:'k',л:'l',м:'m',н:'n',о:'o',п:'p',р:'r',с:'s',т:'t',у:'u',ф:'f',х:'h',ц:'c',ч:'ch',ш:'sh',щ:'sch',ъ:'',ы:'y',ь:'',э:'e',ю:'yu',я:'ya' }
  return s.toLowerCase().split('').map((ch) => map[ch] ?? ch).join('').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
}
</script>

<style scoped>
.settings { max-width: 820px; width: 100%; margin: 0 auto; padding: 20px 20px 48px; }
section { background: var(--surface); border-radius: var(--radius-l); box-shadow: var(--shadow); padding: 18px 20px; margin-bottom: 18px; }
h2 { font-size: 19px; margin: 0 0 10px; }
.sources { list-style: none; padding: 0; margin: 0 0 12px; display: flex; flex-direction: column; gap: 6px; }
.sources li { display: flex; flex-direction: column; }
.err { color: var(--now); overflow-wrap: anywhere; }
.people { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
.person { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
input:not([type='checkbox']):not([type='color']), select { border: 1px solid var(--line); border-radius: var(--radius-m); background: var(--surface); padding: 7px 10px; }
input[type='color'] { width: 38px; height: 34px; border: 1px solid var(--line); border-radius: var(--radius-m); padding: 2px; background: var(--surface); }
.emoji { width: 54px; text-align: center; }
.name { flex: 1; min-width: 140px; }
.chk { display: inline-flex; align-items: center; gap: 5px; color: var(--ink-2); white-space: nowrap; }
.account { display: flex; flex-direction: column; gap: 10px; max-width: 420px; }
.account label { display: flex; flex-direction: column; gap: 4px; font-weight: 600; }
.account label input { font-weight: 400; }
.account .btn { align-self: flex-start; }
.ok { color: #22a06b; margin: 0; }
.account .err { margin: 0; }
.add { display: flex; gap: 8px; flex-wrap: wrap; }
.add input { flex: 1; min-width: 200px; }
.table { display: flex; flex-direction: column; gap: 4px; }
.crow { display: grid; grid-template-columns: 12px 1fr auto; align-items: center; gap: 6px 10px; padding: 10px 0; border-bottom: 1px solid var(--line); }
.crow .owners { grid-column: 2 / -1; }
.flags { display: flex; gap: 12px; flex-wrap: wrap; }
.keywords { flex-basis: 100%; font-size: 14px; }
.crow.hidden .cname { color: var(--ink-3); text-decoration: line-through; }
.swatch { width: 12px; height: 12px; border-radius: 50%; }
.cname { display: flex; flex-direction: column; font-weight: 600; min-width: 0; overflow-wrap: anywhere; }
.cname small { font-weight: 400; }
.link { display: block; background: var(--surface-2); padding: 8px 12px; border-radius: var(--radius-m); overflow-wrap: anywhere; }
.small { font-size: 13px; }
@media (max-width: 760px) {
  .settings { padding: 12px 12px 36px; }
  .crow { grid-template-columns: 12px 1fr; }
  .crow .flags, .crow .owners { grid-column: 2; }
}
</style>
