<template>
  <div>
    <h3 class="group-title">Взять с собой</h3>
    <div v-if="lst" class="group">
      <label v-for="i in lst.items" :key="i.id" class="row item" :class="{ done: i.done }">
        <input type="checkbox" :checked="i.done" @change="toggle(i)" />
        <span class="t">{{ i.text }}</span>
      </label>
      <form class="row add" @submit.prevent="add">
        <input v-model="text" class="inline grow" placeholder="Добавить вещь" aria-label="Добавить вещь" />
        <button class="btn" :disabled="!text.trim()">Добавить</button>
      </form>
    </div>
    <div v-else-if="picking" class="group">
      <button class="row pick" @click="create"><span class="plus">＋</span> Новый список «{{ newName }}»</button>
      <button v-for="l in lists" :key="l.id" class="row pick" @click="attach(l.id)">{{ l.name }} <span class="faint">· {{ l.items.length }}</span></button>
    </div>
    <button v-else class="btn link" @click="openPick">＋ Список вещей</button>
    <p class="group-note">
      <template v-if="lst">Неотмеченное приходит в напоминании о событии и «Пора выезжать».<template v-if="base.recurring"> Отметки сбрасываются к следующему разу.</template>
        <button class="btn link sm" @click="detach">Отвязать</button></template>
      <template v-else>Например для «Плавания»: шапочка, очки, полотенце — придут в напоминании.</template>
    </p>
  </div>
</template>

<script setup>
// Список вещей у события (eventlists.py): создать или привязать список, отмечать прямо из карточки.
import { computed, ref, watch } from 'vue'
import { api } from '../lib/api'
import { toast } from '../lib/store'
import { haptic } from '../lib/haptic'

const props = defineProps({ e: { type: Object, required: true } })
const lst = ref(null)
const lists = ref([])
const picking = ref(false)
const text = ref('')
// у карточки поездки — вхождение исходного события (у поездки start — начало окна, а не события)
const base = computed(() => props.e.duty?.parent || props.e)
const occ = computed(() => (base.value.recurring ? base.value.start : null))
const newName = computed(() => `${base.value.title}: взять`)

async function load() {
  picking.value = false
  try { lst.value = (await api.eventList(props.e.uid, occ.value)).list } catch { lst.value = null }
}
watch(() => props.e.id, load, { immediate: true })

async function openPick() {
  picking.value = true
  try { lists.value = await api.lists() } catch { lists.value = [] }
}
async function attach(id) {
  try { lst.value = (await api.setEventList({ uid: props.e.uid, list_id: id })).list; picking.value = false } catch (err) { toast(err.message) }
}
async function create() {
  try { lst.value = (await api.setEventList({ uid: props.e.uid, new_name: newName.value })).list; picking.value = false } catch (err) { toast('Не удалось: ' + err.message) }
}
async function detach() {
  try { await api.setEventList({ uid: props.e.uid }); lst.value = null; toast('Список отвязан (сам список остался в «Списках»)') } catch (err) { toast('Не удалось: ' + err.message) }
}
async function toggle(i) {
  i.done = !i.done
  haptic('tap')
  try { await api.patchItem(i.id, { done: i.done }) } catch (err) { i.done = !i.done; toast('Не удалось: ' + err.message) }
}
async function add() {
  const t = text.value.trim()
  if (!t) return
  text.value = ''
  try { await api.addItem(lst.value.id, t); await load() } catch (err) { toast('Не удалось: ' + err.message) }
}
</script>

<style scoped>
.group { background: var(--surface-2); }
.group-title { margin: 22px 4px 6px; }
.group-note { margin: 6px 4px 0; }
.item { gap: 10px; cursor: pointer; }
.item input { width: 20px; height: 20px; flex: none; accent-color: var(--tint); }
.item.done .t { color: var(--ink-3); text-decoration: line-through; }
.add { gap: 8px; }
.pick { width: 100%; border: 0; background: none; font: inherit; color: var(--ink); text-align: left; cursor: pointer; }
.pick .plus { color: var(--tint); font-weight: 700; }
.sm { font-size: 13px; padding: 0 4px; }
</style>
