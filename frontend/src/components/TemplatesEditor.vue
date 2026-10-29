<template>
  <div>
    <p v-if="!kids.length" class="group-note">Отметьте ребёнка в карточке человека — тогда здесь можно задать, кто его обычно возит.</p>
    <template v-else>
      <template v-if="suggestions.length">
        <h3 class="group-title">Похоже на правило</h3>
        <div class="group">
          <div v-for="(sg, i) in suggestions" :key="i" class="row stack">
            <span class="lbl">{{ kidName(sg.child_id) }}, {{ DAYS[sg.weekday].toLowerCase() }}: «{{ sg.match }}»
              <small class="muted block">
                {{ sg.dropoff ? 'отвозит ' + name(sg.dropoff) : '' }}{{ sg.dropoff && sg.pickup ? ', ' : '' }}{{ sg.pickup ? 'забирает ' + name(sg.pickup) : '' }}
                — вы назначали так {{ sg.count }} раза
              </small></span>
            <div class="line">
              <button class="btn filled" @click="accept(sg)">Сделать правилом</button>
              <button class="btn" @click="suggestions.splice(i, 1)">Не нужно</button>
            </div>
          </div>
        </div>
      </template>
      <div v-if="rows.length" class="group">
        <div v-for="t in rows" :key="t.id" class="row stack tpl">
          <div class="line">
            <select v-if="kids.length > 1" v-model="t.child_id" class="sel" aria-label="Ребёнок" @change="save(t)">
              <option v-for="k in kids" :key="k.id" :value="k.id">{{ k.name }}</option>
            </select>
            <select v-model.number="t.weekday" class="sel" aria-label="День недели" @change="save(t)">
              <option v-for="(d, i) in DAYS" :key="i" :value="i">{{ d }}</option>
            </select>
            <input v-model="t.match" class="inline grow words" placeholder="любое событие или слова: кружок, бассейн"
                   aria-label="Слова в названии" @change="save(t)" />
            <button class="x" aria-label="Удалить шаблон" @click="remove(t)">×</button>
          </div>
          <div class="line">
            <label>Отвезти
              <select v-model="t.dropoff" class="sel" @change="save(t)">
                <option value="">не задано</option>
                <option v-for="a in adults" :key="a.id" :value="a.id">{{ a.name }}</option>
                <option value="-">не нужно</option>
              </select>
            </label>
            <label>Забрать
              <select v-model="t.pickup" class="sel" @change="save(t)">
                <option value="">не задано</option>
                <option v-for="a in adults" :key="a.id" :value="a.id">{{ a.name }}</option>
                <option value="-">не нужно</option>
              </select>
            </label>
          </div>
        </div>
      </div>
      <p v-if="!rows.length" class="group-note">Шаблонов пока нет.</p>
      <div class="group add"><div class="row"><button class="btn" @click="add">＋ Добавить шаблон</button></div></div>
    </template>
    <p class="group-note">
      Шаблон — значение «по умолчанию»: «по вторникам везёт Толя, забирает Оля». Подставляется во все события ребёнка
      в этот день недели (с указанными словами — только в подходящие). Если в карточке события выбрано другое, оно важнее;
      замена на один день делается там же.
    </p>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '../lib/api'
import { state, reload } from '../lib/store'

const DAYS = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
const rows = ref([])
const people = computed(() => (state.config?.people || []).filter((p) => !p.id.startsWith('_') && !p.hidden))
const kids = computed(() => people.value.filter((p) => p.needs_escort))
const adults = computed(() => people.value.filter((p) => !p.needs_escort))

const suggestions = ref([])
const name = (id) => people.value.find((p) => p.id === id)?.name || id
const kidName = (id) => name(id)
async function accept(sg) {
  await api.saveTemplate({ child_id: sg.child_id, weekday: sg.weekday, match: sg.match, dropoff: sg.dropoff || '', pickup: sg.pickup || '' })
  suggestions.value = suggestions.value.filter((x) => x !== sg)
  await load()
  reload()
}
const loadSuggestions = () => api.templateSuggestions().then((r) => (suggestions.value = r)).catch(() => {})
const load = () => api.templates().then((r) => (rows.value = r)).catch(() => {})
watch(() => state.config?.people, () => { load(); loadSuggestions() }, { immediate: true })

async function save(t) {
  await api.saveTemplate({ id: t.id, child_id: t.child_id, weekday: t.weekday, match: t.match || '', dropoff: t.dropoff || '', pickup: t.pickup || '' })
  reload()
}
async function add() {
  const wd = (new Date().getDay() + 6) % 7
  await api.saveTemplate({ child_id: kids.value[0].id, weekday: wd, match: '', dropoff: '', pickup: '' })
  await load()
}
async function remove(t) {
  await api.deleteTemplate(t.id)
  await load()
  reload()
}
</script>

<style scoped>
.tpl .line { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.tpl label { display: flex; align-items: center; gap: 6px; font-size: 14px; color: var(--ink-2); }
.words { min-width: 140px; text-align: left; }
.x { border: 0; background: none; color: var(--ink-3); font-size: 22px; line-height: 1; padding: 4px 8px; }
.x:hover { color: var(--red); }
.add { margin-top: 10px; }
.block { display: block; }
</style>
