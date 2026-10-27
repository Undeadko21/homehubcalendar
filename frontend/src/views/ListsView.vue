<template>
  <div class="lists">
    <div v-if="lists.length" class="tabs">
      <div class="seg" role="tablist" aria-label="Списки">
        <button v-for="l in lists" :key="l.id" role="tab" :aria-selected="l.id === currentId"
                :class="{ on: l.id === currentId }" @click="currentId = l.id">
          {{ l.name }}<small v-if="open(l)"> {{ open(l) }}</small>
        </button>
      </div>
      <button class="btn" @click="adding = !adding">＋ Список</button>
    </div>
    <form v-if="adding || !lists.length" class="group add-list" @submit.prevent="createList">
      <div class="row">
        <input v-model="newList" class="inline grow" placeholder="Название списка, например «Дача»" aria-label="Название нового списка" />
        <button class="btn filled" :disabled="!newList.trim()">Создать</button>
      </div>
    </form>

    <template v-if="current">
      <form class="group add" @submit.prevent="addItem">
        <div class="row">
          <input v-model="text" class="inline grow" :placeholder="current.name === 'Покупки' ? 'Что купить?' : 'Что добавить?'"
                 aria-label="Новая запись" autocomplete="off" enterkeyhint="done" />
          <button class="btn filled" :disabled="!text.trim()">Добавить</button>
        </div>
      </form>

      <p v-if="!current.items.length" class="empty">Список пуст.</p>
      <div v-else class="group items">
        <div v-for="i in current.items" :key="i.id" class="row item" :class="{ done: i.done }">
          <button class="check" :aria-label="i.done ? 'Вернуть в список' : 'Отметить выполненным'" :aria-pressed="i.done" @click="toggle(i)">
            <svg v-if="i.done" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 12.5l4 4 8-9" /></svg>
          </button>
          <span class="txt" @click="toggle(i)">{{ i.text }}</span>
          <button class="x" aria-label="Удалить" @click="remove(i)">×</button>
        </div>
      </div>

      <div class="manage">
        <button v-if="current.items.some((i) => i.done)" class="btn" @click="clearDone">Убрать выполненные</button>
        <button class="btn" @click="rename">Переименовать</button>
        <button class="btn danger" @click="removeList">Удалить список</button>
      </div>
    </template>
    <p v-if="error" class="err">{{ error }}</p>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../lib/api'
import { state } from '../lib/store'

const lists = ref([])
const currentId = ref(null)
const text = ref('')
const adding = ref(false)
const newList = ref('')
const error = ref('')
const current = computed(() => lists.value.find((l) => l.id === currentId.value) || null)
const open = (l) => l.items.filter((i) => !i.done).length || ''

// Список общий для всей семьи — подтягиваем чужие изменения.
async function load() {
  try {
    lists.value = await api.lists()
    if (!current.value) currentId.value = lists.value[0]?.id ?? null
    error.value = ''
  } catch (e) { error.value = 'Не удалось загрузить: ' + e.message }
}
let timer
onMounted(() => { load(); timer = setInterval(load, 20000) })
onUnmounted(() => clearInterval(timer))
watch(() => state.revision, load)

async function guard(fn) {
  try { await fn(); error.value = '' } catch (e) { error.value = 'Не удалось сохранить: ' + e.message }
  await load()
}
function addItem() {
  const t = text.value.trim()
  if (!t) return
  text.value = ''
  return guard(() => api.addItem(current.value.id, t))
}
function toggle(i) {
  i.done = !i.done
  return guard(() => api.patchItem(i.id, { done: i.done }))
}
function remove(i) { return guard(() => api.deleteItem(i.id)) }
function clearDone() { return guard(() => api.clearDone(current.value.id)) }
function rename() {
  const name = prompt('Название списка', current.value.name)
  if (name && name.trim()) return guard(() => api.renameList(current.value.id, name))
}
function removeList() {
  if (!confirm(`Удалить список «${current.value.name}» вместе с записями?`)) return
  const id = current.value.id
  currentId.value = null
  return guard(() => api.deleteList(id))
}
async function createList() {
  const name = newList.value.trim()
  if (!name) return
  newList.value = ''
  adding.value = false
  await guard(async () => { currentId.value = (await api.addList(name)).id })
}
</script>

<style scoped>
.lists { padding: 12px 16px 32px; max-width: 760px; display: flex; flex-direction: column; gap: 14px; }
.tabs { display: flex; align-items: center; gap: 8px; justify-content: space-between; flex-wrap: wrap; }
.tabs .seg { flex-wrap: wrap; }
.tabs small { color: var(--ink-3); font-weight: 400; }
.add .row, .add-list .row { gap: 8px; }
.item { gap: 12px; }
.check {
  width: 24px; height: 24px; border-radius: 50%; flex: none; padding: 0; display: grid; place-items: center;
  border: 1.5px solid var(--ink-3); background: none; color: #fff;
}
.item.done .check { background: var(--tint); border-color: var(--tint); }
.check svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; }
.txt { flex: 1; min-width: 0; overflow-wrap: anywhere; cursor: pointer; }
.item.done .txt { color: var(--ink-3); text-decoration: line-through; }
.x { border: 0; background: none; color: var(--ink-3); font-size: 22px; line-height: 1; padding: 4px 8px; }
.x:hover { color: var(--red); }
.manage { display: flex; gap: 4px; flex-wrap: wrap; }
.danger { color: var(--red); }
.err { color: var(--red); font-size: 14px; }
</style>
