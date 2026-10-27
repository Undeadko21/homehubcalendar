<template>
  <div class="settings">
    <!-- Учётная запись -->
    <template v-for="acc in accounts" :key="acc.id">
      <h3 class="group-title">Яндекс.Календарь</h3>
      <form class="group" @submit.prevent="saveAccount(acc)">
        <label class="row">
          <span class="lbl">Логин</span>
          <input v-model="acc.username" class="inline" type="email" autocomplete="username" autocapitalize="off" placeholder="ivanov@yandex.ru" />
        </label>
        <label class="row">
          <span class="lbl">Пароль</span>
          <input v-model="acc.password" class="inline" type="password" autocomplete="new-password"
                 :placeholder="acc.has_password ? 'сохранён' : 'пароль приложения'" />
        </label>
        <div class="row">
          <button class="btn filled" :disabled="acc.busy || !acc.username">{{ acc.busy ? 'Проверяю…' : 'Сохранить и подключить' }}</button>
        </div>
      </form>
      <p v-if="acc.result" class="group-note" :class="acc.result.ok ? 'ok' : 'err'">
        {{ acc.result.ok ? `Подключено: календарей ${acc.result.calendars}, записей ${acc.result.objects}.` : 'Не удалось подключиться: ' + acc.result.error }}
      </p>
      <p v-else class="group-note">
        Нужен <strong>пароль приложения</strong>, а не основной пароль:
        <a href="https://id.yandex.ru/security/app-passwords" target="_blank" rel="noopener">id.yandex.ru → Пароли приложений</a>, тип «Календарь».
        Хранится только на вашем сервере.
      </p>
    </template>

    <!-- Синхронизация -->
    <h3 class="group-title">Синхронизация</h3>
    <div class="group">
      <div v-for="s in sources" :key="s.source_id" class="row">
        <span class="lbl">{{ s.source_id }}</span>
        <span v-if="s.last_error" class="val err">{{ s.last_error }}</span>
        <span v-else class="val muted">{{ s.last_ok ? fmt(s.last_ok) : 'ещё не обновлялось' }}</span>
      </div>
      <div class="row">
        <button class="btn" :disabled="busy" @click="sync">{{ busy ? 'Обновляю…' : 'Обновить сейчас' }}</button>
      </div>
    </div>

    <!-- Люди -->
    <h3 class="group-title">Люди</h3>
    <div class="group">
      <button v-for="p in editPeople" :key="p.id" class="row person-row" @click="openPerson(p)">
        <span class="avatar" :style="{ background: p.color }">{{ p.emoji || p.name[0] }}</span>
        <span class="pmain">
          <span class="pname">{{ p.name }}<span v-if="p.needs_escort" class="tag">ребёнок</span><span v-if="p.hidden" class="tag">скрыт</span></span>
          <span v-if="p.keywords" class="psub">автопривязка: {{ p.keywords }}</span>
        </span>
        <span class="chev" aria-hidden="true">›</span>
      </button>
      <form class="row" @submit.prevent="addPerson">
        <input v-model="newName" class="inline grow" placeholder="Добавить человека, например «Бабушка»" aria-label="Имя нового человека" />
        <button class="btn" :disabled="!newName.trim()">Добавить</button>
      </form>
    </div>
    <p class="group-note">Нажмите на человека, чтобы поменять цвет, отметить ребёнка или задать слова для автопривязки.</p>

    <!-- Поездки -->
    <h3 class="group-title">Отвезти и забрать</h3>
    <div class="group">
      <label class="row">
        <span class="lbl">Отвезти: минут до начала</span>
        <input v-model.number="escort.before_minutes" class="num" type="number" min="0" max="240" step="5" @change="saveEscort" />
      </label>
      <label class="row">
        <span class="lbl">Забрать: минут после конца</span>
        <input v-model.number="escort.after_minutes" class="num" type="number" min="0" max="240" step="5" @change="saveEscort" />
      </label>
      <label class="row">
        <span class="lbl">Слова «дома»</span>
        <input v-model="escort.home_words" class="inline" placeholder="дома" @change="saveEscort" />
      </label>
      <label class="row">
        <span class="lbl">Домашний адрес</span>
        <input v-model="escort.home_address" class="inline" placeholder="например: Ленина, 5" @change="saveEscort" />
      </label>
    </div>
    <p class="group-note">
      Столько времени взрослый должен быть свободен, чтобы отвезти или забрать ребёнка: в эти минуты
      проверяются конфликты. Кто отвозит, назначается в карточке события ребёнка.
      Событие считается «дома», если в названии или месте есть одно из слов (через запятую) или
      адрес; «все вместе» — если в нём участвует кто-то из взрослых. Это всегда можно поменять в карточке.
    </p>

    <h3 class="group-title">Время в дороге</h3>
    <div class="group">
      <label class="row">
        <span class="lbl">Запас к дороге, минут</span>
        <input v-model.number="escort.travel_buffer" class="num" type="number" min="0" max="60" step="5" @change="saveEscort" />
      </label>
      <div v-for="(pl, i) in escort.places" :key="i" class="row place">
        <input v-model="pl.words" class="inline grow" placeholder="слова: бассейн, секция" aria-label="Слова в названии или месте" @change="saveEscort" />
        <input v-model.number="pl.minutes" class="num" type="number" min="0" max="240" step="5" aria-label="Минут в пути" @change="saveEscort" />
        <span class="muted small">мин</span>
        <button class="x" aria-label="Удалить" @click="removePlace(i)">×</button>
      </div>
      <div class="row"><button class="btn" @click="addPlace">＋ Место</button></div>
    </div>
    <p class="group-note">
      Если у события (или в его месте) встречается слово из правила, окно «отвезти» = дорога + запас до начала,
      а «забрать» — столько же после конца. Для отдельного события время в пути можно задать в его карточке.
      Без правила работают минуты из блока выше.
    </p>

    <h3 class="group-title">Шаблоны поездок по дням недели</h3>
    <TemplatesEditor />

    <h3 class="group-title">Дни рождения</h3>
    <BirthdaysEditor />

    <h3 class="group-title">Облако: связь вне дома</h3>
    <CloudSettings />

    <template v-if="inApp">
      <h3 class="group-title">Напоминания</h3>
      <RemindersSettings />
    </template>

    <!-- Календари -->
    <h3 class="group-title">Календари</h3>
    <p v-if="!editCals.length" class="group-note">Календари появятся после первой синхронизации.</p>
    <div v-for="c in editCals" :key="c.key" class="group cal" :class="{ hidden: c.hidden }">
      <div class="row">
        <span class="swatch" :style="{ background: colorOf(c) }"></span>
        <span class="lbl cname">{{ c.name }}</span>
      </div>
      <div class="row stack">
        <span class="small muted">{{ c.people.length ? 'Чьи события' : 'Нет владельца: события попадут в «Без владельца»' }}</span>
        <PeoplePicker v-model="c.people" :label="'Чей календарь ' + c.name" @update:model-value="(v) => patch(c, { people: v })" />
      </div>
      <label class="row">
        <span class="lbl">Только «занят», без деталей</span>
        <input v-model="c.private" type="checkbox" class="switch" @change="patch(c, { private: c.private })" />
      </label>
      <label class="row">
        <span class="lbl">Скрыть календарь</span>
        <input v-model="c.hidden" type="checkbox" class="switch" @change="patch(c, { hidden: c.hidden })" />
      </label>
    </div>

    <!-- Экран -->
    <!-- Приложение для Android -->
    <h3 class="group-title">Приложение для Android</h3>
    <div class="group">
      <template v-if="inApp">
        <div class="row">
          <span class="lbl">Установлено</span>
          <span class="val muted">версия {{ appVersionInstalled }}</span>
        </div>
        <div class="row"><span class="lbl">Сервер</span><span class="val muted">{{ hostName }}</span></div>
        <div class="row">
          <span class="lbl">Виджет <small class="muted block">{{ widgetState }}</small></span>
          <button v-if="canPin" class="btn filled" @click="pinWidget">Добавить на экран</button>
        </div>
        <div class="row"><button class="btn" @click="changeServer">Сменить сервер</button></div>
      </template>
      <div v-if="appInfo?.available" class="row">
        <span class="lbl">Версия {{ appInfo.versionName }} <small class="muted block">{{ Math.round(appInfo.size / 1024) }} КБ{{ canUpdate && !hasUpdate ? ' · у вас последняя' : '' }}</small></span>
        <button v-if="canUpdate" class="btn filled" :disabled="!hasUpdate" @click="updateApp">{{ hasUpdate ? 'Обновить' : 'Актуальна' }}</button>
        <a v-else class="btn filled" href="/app.apk" download>Скачать</a>
      </div>
      <div v-else-if="appInfo" class="row"><span class="muted small">Приложение ещё не собрано на этом сервере.</span></div>
    </div>
    <p class="group-note">
      Откройте эту страницу на телефоне в домашней Wi-Fi сети и нажмите «Скачать». Android спросит разрешение
      ставить приложения из браузера — разрешите. Виджет «Семейный день» добавляется кнопкой в приложении
      (⚙ → «Добавить на экран») или вручную: долгое нажатие на пустом месте рабочего стола → «Виджеты» →
      найдите «Календарь» с красно-белой иконкой (на Xiaomi — раздел «Виджеты Android» внизу списка).
    </p>

    <h3 class="group-title">Экран на стене</h3>
    <div class="group">
      <div class="row"><code class="link">{{ kioskUrl }}</code></div>
    </div>
    <p class="group-note">
      Откройте ссылку на планшете в полноэкранном режиме: ночью экран приглушается, данные обновляются сами.
      Добавьте <code>&amp;rotate=60</code>, чтобы каждую минуту переключаться между «Сегодня» и «Лентой».
    </p>

    <p class="group-note version">Версия {{ state.config?.version }}</p>

    <!-- Карточка человека -->
    <Sheet :open="!!editing" :title="editing?.name || ''" @close="closePerson">
      <template #actions>
        <button class="btn done" @click="closePerson">Готово</button>
      </template>
      <div v-if="editing" class="pedit">
        <div class="group">
          <label class="row">
            <span class="lbl">Имя</span>
            <input v-model="editing.name" class="inline" @change="savePerson(editing)" />
          </label>
          <label class="row">
            <span class="lbl">Значок</span>
            <input v-model="editing.emoji" class="inline" maxlength="4" placeholder="🙂" @change="savePerson(editing)" />
          </label>
          <div class="row stack">
            <span class="lbl">Цвет</span>
            <div class="swatches" role="radiogroup" aria-label="Цвет">
              <button v-for="col in PALETTE" :key="col" role="radio" :aria-checked="editing.color === col"
                      class="sw" :class="{ on: editing.color === col }" :style="{ background: col }"
                      :aria-label="col" @click="pickColor(col)"></button>
              <label class="sw custom" :class="{ on: !PALETTE.includes(editing.color) }" title="Свой цвет">
                <input v-model="editing.color" type="color" @change="savePerson(editing)" />
              </label>
            </div>
          </div>
        </div>

        <div class="group">
          <div class="row">
            <span class="lbl">Порядок колонок <small class="muted block">соседние колонки удобнее для общих событий</small></span>
            <button class="btn" :disabled="!canMove(editing, -1)" @click="move(editing, -1)">Выше</button>
            <button class="btn" :disabled="!canMove(editing, 1)" @click="move(editing, 1)">Ниже</button>
          </div>
        </div>

        <div class="group">
          <label class="row">
            <span class="lbl">Ребёнок <small class="muted block">его нужно отвозить и забирать</small></span>
            <input v-model="editing.needs_escort" type="checkbox" class="switch" @change="savePerson(editing)" />
          </label>
          <label class="row">
            <span class="lbl">Скрыть из календаря</span>
            <input v-model="editing.hidden" type="checkbox" class="switch" @change="savePerson(editing)" />
          </label>
        </div>

        <h3 class="group-title">Слова для автопривязки</h3>
        <div class="group">
          <div class="row">
            <input v-model="editing.keywords" class="inline grow" placeholder="Например: Марк, бассейн, садик" @change="savePerson(editing)" />
          </div>
        </div>
        <p class="group-note">Если слово есть в названии события из любого календаря, событие появится и у этого человека.</p>

        <div class="group danger">
          <button class="row del" @click="removePerson(editing)">Удалить человека</button>
        </div>
      </div>
    </Sheet>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { api } from '../lib/api'
import { state, reload, syncNow } from '../lib/store'
import PeoplePicker from '../components/PeoplePicker.vue'
import Sheet from '../components/Sheet.vue'
import TemplatesEditor from '../components/TemplatesEditor.vue'
import BirthdaysEditor from '../components/BirthdaysEditor.vue'
import RemindersSettings from '../components/RemindersSettings.vue'
import CloudSettings from '../components/CloudSettings.vue'

// Системные цвета Apple
const PALETTE = ['#ff3b30', '#ff9500', '#ffcc00', '#34c759', '#00c7be', '#007aff', '#5856d6', '#af52de', '#ff2d55', '#a2845e']

const busy = ref(false)
const newName = ref('')
const sources = computed(() => state.status?.sources || [])
const editPeople = ref([])
const editCals = ref([])
const accounts = ref([])
const editing = ref(null)
const escort = reactive({ before_minutes: 30, after_minutes: 30, home_words: 'дома', home_address: '', travel_buffer: 5, places: [] })

watch(() => state.config, (c) => {
  editPeople.value = (c?.people || []).filter((p) => !p.id.startsWith('_'))
    .map((p) => ({ ...p, hidden: !!p.hidden, needs_escort: !!p.needs_escort, keywords: p.keywords || '' }))
  editCals.value = (c?.calendars || []).map((x) => ({ ...x, people: [...(x.people || [])], hidden: !!x.hidden, private: !!x.private }))
  const prev = Object.fromEntries(accounts.value.map((a) => [a.id, a]))
  accounts.value = (c?.accounts || []).map((a) => ({ ...a, password: '', busy: false, result: prev[a.id]?.result || null }))
  Object.assign(escort, c?.escort || {})
}, { immediate: true })

const kioskUrl = computed(() => `${location.origin}/?kiosk&view=today`)

// Приложение для Android (внутри приложения доступен мост window.HomeHubApp)
const inApp = typeof window !== 'undefined' && !!window.HomeHubApp
const appVersionInstalled = inApp ? (() => { try { return window.HomeHubApp.version() } catch { return '?' } })() : ''
const hostName = location.host
const appInfo = ref(null)
api.appInfo().then((v) => (appInfo.value = v)).catch(() => (appInfo.value = { available: false }))
const canUpdate = inApp && !!window.HomeHubApp.updateApp  // в приложении 1.6+
const hasUpdate = computed(() => canUpdate && appInfo.value?.available && Number(appInfo.value.versionCode) > Number(bridge('versionCode', 0)))
function updateApp() { try { window.HomeHubApp.updateApp() } catch {} }
function changeServer() { try { window.HomeHubApp.changeServer() } catch {} }
const bridge = (name, fallback) => { try { return window.HomeHubApp?.[name] ? window.HomeHubApp[name]() : fallback } catch { return fallback } }
const canPin = ref(inApp && bridge('canPinWidget', false))
const hasWidget = ref(inApp && bridge('hasWidget', false))
const widgetState = computed(() => hasWidget.value ? 'уже на рабочем столе' : canPin.value ? 'ещё не добавлен' : 'добавьте вручную — см. ниже')
function pinWidget() {
  bridge('pinWidget', false)
  setTimeout(() => { hasWidget.value = bridge('hasWidget', false) }, 4000)
}
const fmt = (s) => new Date(s).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
const colorOf = (c) => editPeople.value.find((p) => p.id === c.people[0])?.color || c.color || '#8e8e93'

async function sync() {
  busy.value = true
  try { await syncNow() } finally { busy.value = false }
}
async function saveAccount(acc) {
  acc.busy = true
  acc.result = null
  try {
    acc.result = await api.saveAccount(acc.id, acc.username, acc.password || null)
    acc.password = ''
    await reload()
  } catch (e) {
    acc.result = { ok: false, error: e.message }
  } finally {
    acc.busy = false
  }
}
function openPerson(p) { editing.value = { ...p } }
// Порядок людей = порядок колонок. Переставляем соседей и сохраняем порядок всем.
function canMove(p, dir) {
  const i = editPeople.value.findIndex((x) => x.id === p.id)
  return i >= 0 && i + dir >= 0 && i + dir < editPeople.value.length
}
async function move(p, dir) {
  const list = [...editPeople.value]
  const i = list.findIndex((x) => x.id === p.id)
  ;[list[i], list[i + dir]] = [list[i + dir], list[i]]
  for (const [k, x] of list.entries()) {
    const src = x.id === p.id ? editing.value : x
    if (Number(x.sort) !== k || x.id === p.id) await savePersonRaw({ ...src, sort: k })
  }
  editing.value = { ...editing.value, sort: list.findIndex((x) => x.id === p.id) }
  await reload()
}
function closePerson() { editing.value = null }
function pickColor(col) {
  editing.value.color = col
  savePerson(editing.value)
}
async function savePerson(p) {
  await savePersonRaw(p)
  await reload()
}
async function savePersonRaw(p) {
  await api.savePerson({
    id: p.id, name: p.name, color: p.color, emoji: p.emoji || '', sort: Number(p.sort) || 0,
    hidden: !!p.hidden, keywords: p.keywords || '', needs_escort: !!p.needs_escort,
  })
}
async function removePerson(p) {
  if (!confirm(`Удалить «${p.name}»? Его календари и события останутся у других владельцев или без владельца.`)) return
  await api.deletePerson(p.id)
  editing.value = null
  await reload()
}
async function addPerson() {
  const name = newName.value.trim()
  const id = translit(name) || 'p' + Date.now()
  await api.savePerson({ id, name, color: PALETTE[(editPeople.value.length + 5) % PALETTE.length], emoji: '',
    sort: editPeople.value.length, hidden: false, keywords: '', needs_escort: false })
  newName.value = ''
  await reload()
}
function addPlace() { escort.places = [...(escort.places || []), { words: '', minutes: 20 }] }
function removePlace(i) { escort.places.splice(i, 1); saveEscort() }
async function saveEscort() {
  await api.saveEscortSettings({
    before_minutes: Number(escort.before_minutes) || 0,
    after_minutes: Number(escort.after_minutes) || 0,
    home_words: escort.home_words || '',
    home_address: escort.home_address || '',
    travel_buffer: Number(escort.travel_buffer) || 0,
    places: (escort.places || []).filter((p) => (p.words || '').trim()).map((p) => ({ words: p.words.trim(), minutes: Number(p.minutes) || 0 })),
  })
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
.settings { max-width: 680px; width: 100%; margin: 0 auto; padding: 4px 20px 48px; }
.group { background: var(--surface-2); }
.cal { margin-bottom: 12px; }
.cal.hidden .cname { color: var(--ink-3); text-decoration: line-through; }
.lbl { flex: 1; min-width: 0; }
.block { display: block; font-weight: 400; font-size: 13px; }
.val { text-align: right; font-size: 14px; overflow-wrap: anywhere; max-width: 60%; }
.err { color: var(--red); }
.ok { color: var(--ok); }
.inline { border: 0; background: none; text-align: right; flex: 1; min-width: 0; padding: 4px 0; outline: none; }
.inline::placeholder { color: var(--ink-3); }
.grow { text-align: left; }
.num { width: 72px; border: 0; background: var(--fill); border-radius: 8px; padding: 6px 8px; text-align: right; }
.row.stack { flex-direction: column; align-items: stretch; gap: 8px; padding-top: 10px; padding-bottom: 12px; }
.small { font-size: 13px; }
a.btn.filled { text-decoration: none; }
.person-row { width: 100%; border: 0; background: none; text-align: left; color: inherit; }
.person-row:hover { background: var(--fill); }
.avatar { width: 32px; height: 32px; border-radius: 50%; display: grid; place-items: center; color: #fff; font-weight: 600; flex: none; font-size: 16px; }
.pmain { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.pname { font-weight: 500; }
.psub { font-size: 12px; color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tag { font-size: 12px; color: var(--ink-2); background: var(--fill); border-radius: 5px; padding: 1px 6px; margin-left: 6px; }
.chev { color: var(--ink-3); font-size: 22px; line-height: 1; }
.swatch { width: 12px; height: 12px; border-radius: 50%; flex: none; }
.cname { font-weight: 600; }
.link { overflow-wrap: anywhere; font-size: 13px; }
.version { margin-top: 24px; }
.done { font-weight: 600; }

.switch {
  appearance: none; width: 51px; height: 31px; border-radius: 16px; background: var(--fill); position: relative;
  transition: background .2s; flex: none; margin: 0; cursor: pointer;
}
.switch::after {
  content: ''; position: absolute; top: 2px; left: 2px; width: 27px; height: 27px; border-radius: 50%;
  background: #fff; box-shadow: 0 2px 6px rgba(0,0,0,.2); transition: transform .2s;
}
.switch:checked { background: var(--ok); }
.switch:checked::after { transform: translateX(20px); }

.place .x { border: 0; background: none; color: var(--ink-3); font-size: 22px; line-height: 1; padding: 4px 8px; }
.pedit .group { margin-top: 14px; }
.pedit .group-title { margin-top: 22px; }
.swatches { display: flex; flex-wrap: wrap; gap: 10px; }
.sw { width: 30px; height: 30px; border-radius: 50%; border: 0; padding: 0; position: relative; cursor: pointer; }
.sw.on { box-shadow: 0 0 0 2px var(--surface-2), 0 0 0 4px var(--ink-2); }
.sw.custom { background: conic-gradient(#ff3b30, #ffcc00, #34c759, #00c7be, #007aff, #af52de, #ff3b30); overflow: hidden; }
.sw.custom input { opacity: 0; width: 100%; height: 100%; cursor: pointer; }
.danger { margin-top: 24px; }
.del { width: 100%; border: 0; background: none; color: var(--red); justify-content: center; font-weight: 500; }
@media (max-width: 899px) { .settings { padding: 0 12px 36px; } }
</style>
