<template>
  <div>
    <div v-if="list.length" class="group">
      <div v-for="(b, i) in list" :key="i" class="row">
        <span class="grow-t">{{ b.name }}</span>
        <span class="muted">{{ fmt(b.from) }} – {{ fmt(b.to) }}</span>
        <button class="x" aria-label="Удалить" @click="remove(i)">×</button>
      </div>
    </div>
    <form class="group add" @submit.prevent="add">
      <div class="row stack">
        <input v-model="name" class="inline grow" placeholder="Например «Осенние каникулы»" aria-label="Название" />
        <div class="line">
          <label class="small muted">с <input v-model="from" class="date" type="date" /></label>
          <label class="small muted">по <input v-model="to" class="date" type="date" /></label>
          <button class="btn filled" :disabled="!from || !to || to < from">Добавить</button>
        </div>
      </div>
    </form>
    <div class="group hide-box">
      <label class="row"><span class="grow-t">Скрывать школьные события на каникулах</span><input v-model="hide" type="checkbox" @change="saveHide" /></label>
      <div v-if="hide" class="row stack">
        <input v-model="words" class="inline grow" placeholder="школ, урок" aria-label="Слова" @change="saveHide" />
        <span class="small muted">События с этими словами в названии или месте не показываются в даты каникул (например «Отвезти в школу»).</span>
      </div>
    </div>
    <p v-if="error" class="group-note err">{{ error }}</p>
    <p class="group-note">
      Школьные каникулы у каждого региона свои, поэтому даты задаёте вы. Они подписываются на «Сегодня», в ленте и
      в повестке рядом с праздниками, но выходными днями не считаются.
    </p>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { api } from '../lib/api'
import { reload } from '../lib/store'

const list = ref([])
const name = ref('')
const from = ref('')
const to = ref('')
const error = ref('')
const hide = ref(true)
const words = ref('школ')
const fmt = (d) => new Date(d + 'T12:00').toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })

api.school().then((r) => { list.value = r.breaks; hide.value = r.hide !== false; words.value = r.hide_words ?? 'школ' }).catch(() => {})

async function saveHide() {
  error.value = ''
  try { await api.saveSchoolHide(hide.value, words.value); reload() } catch (e) { error.value = e.message }
}

async function save(next) {
  error.value = ''
  try {
    list.value = (await api.saveSchool(next)).breaks
    reload()
  } catch (e) { error.value = e.message }
}
async function add() {
  await save([...list.value, { name: name.value, from: from.value, to: to.value }])
  name.value = ''; from.value = ''; to.value = ''
}
const remove = (i) => save(list.value.filter((_, j) => j !== i))
</script>

<style scoped>
.grow-t { flex: 1; min-width: 0; font-weight: 500; }
.line { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.x { border: 0; background: none; color: var(--ink-3); font-size: 22px; line-height: 1; padding: 4px 8px; }
.x:hover { color: var(--red); }
.add, .hide-box { margin-top: 10px; }
.date { font: inherit; color: inherit; background: var(--fill); border: 0; border-radius: 8px; padding: 6px 8px; }
.err { color: var(--red); }
</style>
