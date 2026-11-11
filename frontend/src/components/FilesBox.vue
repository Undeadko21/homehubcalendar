<template>
  <div class="group files">
    <div v-for="f in files" :key="f.id" class="row file">
      <span class="fi" aria-hidden="true">{{ f.url ? '🔗' : f.mime.startsWith('image/') ? '🖼' : '📄' }}</span>
      <a :href="f.url || `/api/event-files/${f.id}/raw`" target="_blank" rel="noopener" class="fname">
        {{ f.name || f.url }}<small v-if="!f.url" class="faint"> · {{ sizeText(f.size) }}</small>
      </a>
      <button class="x" :disabled="busy" aria-label="Удалить вложение" @click="remove(f)">×</button>
    </div>
    <p v-if="!files.length && !adding" class="row faint small nofiles">{{ empty }}</p>
    <form v-if="adding" class="row linkform" @submit.prevent="saveLink">
      <input v-model="linkUrl" class="in" type="url" placeholder="https://…" aria-label="Ссылка" required />
      <input v-model="linkName" class="in" placeholder="Название (необязательно)" aria-label="Название ссылки" />
      <button class="btn filled sm" :disabled="busy || !linkUrl.trim()">Добавить</button>
      <button type="button" class="btn sm" @click="adding = false">Отмена</button>
    </form>
    <div class="row actions">
      <label class="btn link" :class="{ off: busy }">
        {{ uploading ? 'Загружаю…' : '＋ Файл или фото' }}
        <input type="file" multiple hidden :disabled="busy" @change="upload" />
      </label>
      <button class="btn link" :disabled="busy" @click="adding = true; linkUrl = ''; linkName = ''">＋ Ссылка</button>
    </div>
    <p v-if="error" class="row err">{{ error }}</p>
  </div>
</template>

<script setup>
// Вложения и ссылки: событие (uid события) или дело/покупка (uid `item:<id>`). Хранятся на домашнем сервере.
import { ref, watch } from 'vue'
import { api } from '../lib/api'

const props = defineProps({ uid: { type: String, required: true }, empty: { type: String, default: 'Пока ничего нет.' } })
const emit = defineEmits(['changed'])
const files = ref([])
const adding = ref(false)
const uploading = ref(false)
const busy = ref(false)
const error = ref('')
const linkUrl = ref('')
const linkName = ref('')
const sizeText = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1).replace('.', ',') + ' МБ' : Math.max(1, Math.round(n / 1024)) + ' КБ')

async function load() {
  const uid = props.uid
  try {
    const list = await api.eventFiles(uid)
    if (props.uid === uid) files.value = list
  } catch { files.value = [] }
}
watch(() => props.uid, () => { adding.value = false; error.value = ''; files.value = []; load() }, { immediate: true })

async function act(fn) {
  busy.value = true
  error.value = ''
  try { await fn() } catch (err) { error.value = err.message }
  busy.value = false
  await load()
  emit('changed', files.value.length)
}
function upload(ev) {
  const picked = [...(ev.target.files || [])]
  ev.target.value = ''
  if (!picked.length) return
  uploading.value = true
  return act(async () => {
    try {
      for (const f of picked) {
        if (f.size > 15 * 1024 * 1024) throw new Error(`«${f.name}» больше 15 МБ`)
        await api.uploadEventFile(props.uid, f)
      }
    } finally { uploading.value = false }
  })
}
const saveLink = () => act(async () => { await api.addEventLink(props.uid, linkUrl.value.trim(), linkName.value.trim()); adding.value = false })
const remove = (f) => act(() => api.deleteEventFile(f.id))
</script>

<style scoped>
.files { background: var(--surface-2); }
.file { gap: 10px; align-items: center; }
.fi { flex: none; width: 22px; text-align: center; }
.fname { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.x { border: 0; background: none; color: var(--ink-3); font-size: 20px; line-height: 1; padding: 4px 8px; flex: none; }
.actions { gap: 18px; }
label.btn { cursor: pointer; }
label.off { opacity: .5; pointer-events: none; }
.linkform { flex-wrap: wrap; gap: 8px; }
.linkform .in { flex: 1 1 180px; min-width: 0; font: inherit; padding: 7px 10px; border-radius: 8px; border: .5px solid var(--line); background: var(--surface); color: var(--ink); }
.nofiles { padding-top: 10px; padding-bottom: 4px; font-size: 13px; margin: 0; }
.err { color: var(--red); font-size: 13px; margin: 0; }
</style>
