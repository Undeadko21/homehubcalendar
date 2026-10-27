<template>
  <div>
    <div v-if="list.length" class="group">
      <div v-for="b in list" :key="b.id" class="row">
        <span class="grow-t">{{ b.name }}</span>
        <span class="muted">{{ b.day }} {{ MONTHS[b.month - 1] }}<template v-if="b.year"> {{ b.year }}</template></span>
        <button class="x" aria-label="Удалить" @click="remove(b)">×</button>
      </div>
    </div>
    <form class="group add" @submit.prevent="add">
      <div class="row stack">
        <input v-model="name" class="inline grow" placeholder="Имя, например «Бабушка»" aria-label="Имя" />
        <div class="line">
          <input v-model.number="day" class="num" type="number" min="1" max="31" placeholder="число" aria-label="День" />
          <select v-model.number="month" class="sel" aria-label="Месяц">
            <option v-for="(m, i) in MONTHS" :key="i" :value="i + 1">{{ m }}</option>
          </select>
          <input v-model.number="year" class="num" type="number" min="1900" max="2100" placeholder="год" aria-label="Год рождения (необязательно)" />
          <button class="btn filled" :disabled="!name.trim() || !day">Добавить</button>
        </div>
      </div>
    </form>
    <p v-if="error" class="group-note err">{{ error }}</p>
    <p class="group-note">
      Год можно не указывать. События календаря на весь день со словами «день рождения», «ДР» или «birthday»
      тоже попадают в отсчёт сами.
    </p>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { api } from '../lib/api'
import { reload } from '../lib/store'

const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
const list = ref([])
const name = ref('')
const day = ref(null)
const month = ref(new Date().getMonth() + 1)
const year = ref(null)
const error = ref('')

const load = () => api.birthdays(1).then((r) => (list.value = r.all)).catch(() => {})
load()

async function add() {
  error.value = ''
  try {
    await api.saveBirthday({ name: name.value, month: month.value, day: day.value, year: year.value || null })
    name.value = ''; day.value = null; year.value = null
    await load()
    reload()
  } catch (e) { error.value = e.message }
}
async function remove(b) {
  await api.deleteBirthday(b.id)
  await load()
  reload()
}
</script>

<style scoped>
.grow-t { flex: 1; min-width: 0; font-weight: 500; }
.line { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.x { border: 0; background: none; color: var(--ink-3); font-size: 22px; line-height: 1; padding: 4px 8px; }
.x:hover { color: var(--red); }
.add { margin-top: 10px; }
.err { color: var(--red); }
</style>
