<template>
  <div>
    <div v-if="!s" class="group"><div class="row"><span class="muted">Загружаю…</span></div></div>
    <template v-else>
      <div v-if="s.problems.length" class="group warn">
        <div v-for="p in s.problems" :key="p" class="row"><span class="dotr"></span><span class="lbl">{{ p }}</span></div>
      </div>
      <div v-else class="group"><div class="row"><span class="ok">●</span><span class="lbl">Всё в порядке</span></div></div>

      <h3 class="group-title">Календарь</h3>
      <div class="group">
        <div v-for="x in s.sources" :key="x.source_id" class="row">
          <span class="lbl">{{ x.source_id }}</span>
          <span v-if="x.last_error" class="val err">{{ x.last_error }}</span>
          <span v-else class="val muted">{{ x.last_ok ? ago(x.last_ok) : 'ещё не обновлялось' }}</span>
        </div>
        <div class="row"><span class="lbl">Период опроса</span><span class="val muted">каждые {{ s.sync_interval }} мин</span></div>
        <div class="row"><span class="lbl">В базе</span>
          <span class="val muted">{{ s.counts.calendars }} календ., {{ s.counts.objects }} записей</span></div>
      </div>

      <h3 class="group-title">Облако</h3>
      <div class="group">
        <div class="row"><span class="lbl">Снимок для телефона и Алисы</span>
          <span v-if="!s.cloud.configured" class="val muted">не подключено</span>
          <span v-else-if="s.cloud.last_error" class="val err">{{ s.cloud.last_error }}</span>
          <span v-else class="val muted">{{ s.cloud.last_ok ? ago(s.cloud.last_ok) : 'скоро' }}</span></div>
        <div v-if="s.cloud.ops_error" class="row"><span class="lbl">Команды с телефона</span><span class="val err">{{ s.cloud.ops_error }}</span></div>
      </div>

      <h3 class="group-title">Резервная копия</h3>
      <div class="group">
        <div class="row"><span class="lbl">Последняя копия</span>
          <span v-if="!s.backup.configured" class="val muted">нужно облако</span>
          <span v-else-if="s.backup.last_error" class="val err">{{ s.backup.last_error }}</span>
          <span v-else class="val muted">{{ s.backup.last_ok ? ago(s.backup.last_ok) + ', ' + kb(s.backup.size) : 'ещё не было' }}</span></div>
        <div v-if="s.backup.count" class="row"><span class="lbl">Хранится копий</span><span class="val muted">{{ s.backup.count }} из {{ s.backup.keep }}</span></div>
        <div class="row"><button class="btn" :disabled="busy || !s.backup.configured" @click="backup">{{ busy ? 'Копирую…' : 'Сделать копию сейчас' }}</button></div>
      </div>
      <div v-if="s.backup.verified" class="group">
        <div class="row"><span class="lbl">Проверка копии</span>
          <span v-if="s.backup.verified.ok" class="val muted">{{ ago(s.backup.verified.at) }}: открывается, людей {{ s.backup.verified.people }}, записей {{ s.backup.verified.objects }}</span>
          <span v-else class="val err">{{ s.backup.verified.error }}</span></div>
      </div>
      <div class="group">
        <div class="row"><button class="btn link" :disabled="busy || !s.backup.configured" @click="verify()">Проверить свежую копию</button></div>
        <div class="row"><button class="btn link" :disabled="busy || !s.backup.configured" @click="showFiles">{{ files ? 'Обновить список' : 'Восстановить из копии…' }}</button></div>
        <template v-if="files">
          <div v-if="!files.length" class="row"><span class="muted">Копий на Диске нет</span></div>
          <div v-for="f in files" :key="f.name" class="row stack">
            <div class="between"><span class="lbl">{{ nameDate(f.name) }}</span><span class="val muted">{{ kb(f.size) }}</span></div>
            <div v-if="confirm !== f.name" class="acts">
              <button class="btn link" :disabled="busy" @click="verify(f.name)">Проверить</button>
              <button class="btn danger" :disabled="busy" @click="confirm = f.name">Восстановить…</button>
            </div>
            <div v-else class="acts">
              <span class="small err">Текущие данные будут заменены. Страховочная копия сохранится на сервере.</span>
              <button class="btn danger" :disabled="busy" @click="restore(f.name)">Да, заменить</button>
              <button class="btn" :disabled="busy" @click="confirm = ''">Отмена</button>
            </div>
          </div>
        </template>
      </div>
      <p class="group-note">
        Раз в сутки около 03:30 база (события, люди, шаблоны, списки, настройки) шифруется и кладётся на Яндекс.Диск в
        папку приложения «backups»; хранятся последние {{ s.backup.keep }}. Расшифровать копию можно ключом из
        кода подключения (поле «k», он же HOMEHUB_KEY навыка Алисы): <code>backend/tools/restore_backup.py</code>.
      </p>

      <h3 class="group-title">Перенос настроек</h3>
      <div class="group">
        <div class="row">
          <a class="btn link" href="/api/export" download>Скачать настройки (файл)</a>
        </div>
        <div class="row">
          <label class="btn link file">Загрузить настройки из файла…
            <input type="file" accept="application/json,.json" hidden @change="importFile" />
          </label>
        </div>
      </div>
      <p class="group-note">
        В файле: люди, привязка календарей, шаблоны и поездки, дни рождения, каникулы, списки, настройки напоминаний.
        Событий, паролей и токенов в нём нет — они вернутся после подключения Яндекса. При загрузке текущие люди, шаблоны и списки заменяются.
      </p>
      <p v-if="note" class="group-note">{{ note }}</p>

      <h3 class="group-title">Скорость</h3>
      <div class="group">
        <div v-if="!perf" class="row"><button class="btn link" @click="loadPerf">Показать время ответов</button></div>
        <template v-else>
          <div v-if="!perf.routes.length" class="row"><span class="muted">Пока нет замеров</span></div>
          <div v-for="r in perf.routes.slice(0, 8)" :key="r.route" class="row">
            <span class="lbl mono">{{ r.route.replace('/api/', '') }}</span>
            <span class="val" :class="r.p95 >= perf.slow_ms ? 'err' : 'muted'">{{ r.avg }} / {{ r.p95 }} мс<template v-if="r.errors"> · ошибок {{ r.errors }}</template></span>
          </div>
          <div v-for="(x, i) in perf.slow.slice(0, 6)" :key="'s' + i" class="row stack">
            <small class="muted block">{{ fmt(x.at) }} · {{ x.route.replace('/api/', '') }} · {{ x.ms }} мс{{ x.query ? ' · ' + x.query : '' }}</small>
          </div>
        </template>
      </div>
      <p class="group-note">Среднее / 95-й процентиль по запросам с последнего запуска сервера; медленными считаются запросы дольше {{ perf ? perf.slow_ms : 700 }} мс.</p>

      <h3 class="group-title">Сервер</h3>
      <div class="group">
        <div class="row"><span class="lbl">Версия</span><span class="val muted">{{ s.version }}</span></div>
        <div class="row"><span class="lbl">Работает с</span><span class="val muted">{{ fmt(s.started) }}</span></div>
        <div v-if="s.slow_requests" class="row"><span class="lbl">Медленных запросов</span><span class="val err">{{ s.slow_requests }}</span></div>
        <div class="row"><span class="lbl">Размер базы</span><span class="val muted">{{ kb(s.db_size) }}</span></div>
        <div class="row"><span class="lbl">Ошибок в браузерах и приложении</span>
          <span class="val" :class="s.client_errors ? 'err' : 'muted'">{{ s.client_errors }}</span></div>
        <div v-if="s.last_client_error" class="row stack"><small class="muted block">последняя: {{ s.last_client_error.message }}</small></div>
      </div>
    </template>
    <p v-if="err" class="group-note err">{{ err }}</p>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { api } from '../lib/api'

const s = ref(null)
const busy = ref(false)
const err = ref('')
const note = ref('')
const files = ref(null)
const confirm = ref('')
const perf = ref(null)
const nameDate = (n) => {
  const m = n.match(/(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)/)
  return m ? `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}` : n
}
const fmt = (d) => new Date(d).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
const kb = (n) => (n == null ? '—' : n > 1048576 ? (n / 1048576).toFixed(1) + ' МБ' : Math.max(1, Math.round(n / 1024)) + ' КБ')
function ago(d) {
  const m = Math.round((Date.now() - new Date(d).getTime()) / 60000)
  if (m < 1) return 'только что'
  if (m < 60) return m + ' мин назад'
  if (m < 1440) return Math.round(m / 60) + ' ч назад'
  return fmt(d)
}
const load = () => api.system().then((r) => { s.value = r }).catch((e) => { err.value = e.message })
async function backup() {
  busy.value = true
  try { await api.runBackup() } catch (e) { err.value = e.message }
  busy.value = false
  load()
}
async function showFiles() {
  busy.value = true; err.value = ''
  try { files.value = (await api.backupFiles()).files } catch (e) { err.value = e.message }
  busy.value = false
}
async function verify(name) {
  busy.value = true; err.value = ''; note.value = ''
  try {
    const r = await api.backupVerify(name)
    note.value = r.ok ? `Копия ${nameDate(r.name)} в порядке: людей ${r.people}, календарей ${r.calendars}, записей ${r.objects}.` : ''
    if (!r.ok) err.value = r.error
  } catch (e) { err.value = e.message }
  busy.value = false
  load()
}
async function restore(name) {
  busy.value = true; err.value = ''; note.value = ''
  try {
    const r = await api.backupRestore(name)
    note.value = `Восстановлено из копии ${nameDate(r.name)} (людей ${r.people}, записей ${r.objects}). Страница обновится…`
    confirm.value = ''
    setTimeout(() => location.reload(), 2000)
  } catch (e) { err.value = e.message }
  busy.value = false
}
const loadPerf = () => api.perf().then((r) => { perf.value = r }).catch((e) => { err.value = e.message })
async function importFile(ev) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  if (!file) return
  err.value = ''; note.value = ''
  try {
    const blob = JSON.parse(await file.text())
    const r = await api.importSettings(blob)
    note.value = 'Настройки загружены: ' + Object.entries(r.counts).map(([k, v]) => `${k} ${v}`).join(', ') + '. Обновите страницу.'
  } catch (e) {
    err.value = e.message
  }
}
let t
onMounted(() => { load(); t = setInterval(load, 20000) })
onUnmounted(() => clearInterval(t))
</script>

<style scoped>
.ok { color: #34c759; }
.dotr { width: 8px; height: 8px; border-radius: 50%; background: var(--red); flex: none; }
.warn { border: 1px solid var(--red); }
.err { color: var(--red); }
code { font-size: 12px; }
.acts { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.between { display: flex; justify-content: space-between; gap: 8px; width: 100%; }
.danger { color: var(--red); }
.mono { font-family: ui-monospace, monospace; font-size: 13px; }
.small { font-size: 13px; }
</style>
