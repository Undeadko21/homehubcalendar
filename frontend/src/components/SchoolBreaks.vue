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
const fmt = (d) => new Date(d + 'T12:00').toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })

api.school().then((r) => (list.value = r.breaks)).catch(() => {})

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
.add { margin-top: 10px; }
.date { font: inherit; color: inherit; background: var(--fill); border: 0; border-radius: 8px; padding: 6px 8px; }
.err { color: var(--red); }
</style>
