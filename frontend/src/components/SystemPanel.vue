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
      <p class="group-note">
        Раз в сутки около 03:30 база (события, люди, шаблоны, списки, настройки) шифруется и кладётся на Яндекс.Диск в
        папку приложения «backups»; хранятся последние {{ s.backup.keep }}. Расшифровать копию можно ключом из
        кода подключения (поле «k», он же HOMEHUB_KEY навыка Алисы): <code>backend/tools/restore_backup.py</code>.
      </p>

      <h3 class="group-title">Сервер</h3>
      <div class="group">
        <div class="row"><span class="lbl">Версия</span><span class="val muted">{{ s.version }}</span></div>
        <div class="row"><span class="lbl">Работает с</span><span class="val muted">{{ fmt(s.started) }}</span></div>
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
</style>
