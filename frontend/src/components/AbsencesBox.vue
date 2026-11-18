<template>
  <div>
    <div v-if="list.length" class="group">
      <div v-for="a in list" :key="a.id" class="row">
        <span class="ava" :style="{ background: who(a.person)?.color }">{{ who(a.person)?.emoji || who(a.person)?.name?.[0] }}</span>
        <span class="grow-t">{{ who(a.person)?.name || a.person }} — {{ a.note }}</span>
        <span class="muted">{{ range(a) }}</span>
        <button class="x" aria-label="Удалить" @click="remove(a.id)">×</button>
      </div>
    </div>
    <form class="group add" @submit.prevent="add">
      <div class="row stack">
        <div class="chips" role="radiogroup" aria-label="Кто">
          <button v-for="p in ppl" :key="p.id" type="button" class="choice skip" role="radio" :aria-checked="person === p.id"
                  :class="{ on: person === p.id }" @click="person = p.id">{{ p.emoji }} {{ p.name }}</button>
        </div>
        <div class="chips" role="radiogroup" aria-label="Причина">
          <button v-for="n in NOTES" :key="n" type="button" class="choice skip" role="radio" :aria-checked="note === n"
                  :class="{ on: note === n }" @click="note = n">{{ n }}</button>
        </div>
        <div class="line">
          <label class="small muted">с <input v-model="from" class="date" type="date" /></label>
          <label class="small muted">по <input v-model="to" class="date" type="date" /></label>
          <button class="btn filled" :disabled="!person || !from">Добавить</button>
        </div>
      </div>
    </form>
    <p v-if="error" class="group-note err">{{ error }}</p>
    <p class="group-note">
      В эти дни события человека показываются приглушёнными с пометкой, у детей не нужен водитель и поездка не появляется
      у взрослых, напоминаний о них нет. Отметить один день можно и в карточке события — «Не идёт».
    </p>
  </div>
</template>

<script setup>
// «Болеет / не идёт»: человек пропускает свои события в эти даты (absences.py на сервере).
import { computed, ref } from 'vue'
import { api } from '../lib/api'
import { state, reload, toast } from '../lib/store'
import { isoDate } from '../lib/dates'

const NOTES = ['болеет', 'уехал(а)', 'не идёт']
const list = ref([])
const person = ref('')
const note = ref('болеет')
const from = ref(isoDate(new Date()))
const to = ref('')
const error = ref('')
const ppl = computed(() => (state.config?.people || []).filter((p) => !p.id.startsWith('_') && !p.hidden)
  .sort((a, b) => (b.needs_escort ? 1 : 0) - (a.needs_escort ? 1 : 0)))
const who = (id) => (state.config?.people || []).find((p) => p.id === id)
const fmt = (d) => new Date(d + 'T12:00').toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
const range = (a) => (a.from === a.to ? fmt(a.from) : `${fmt(a.from)} – ${fmt(a.to)}`)

api.absences().then((r) => { list.value = r.items }).catch(() => {})

async function save(next) {
  error.value = ''
  try {
    list.value = (await api.saveAbsences(next)).items
    reload()
    return true
  } catch (e) { error.value = 'Не удалось сохранить: ' + e.message; return false }
}
async function add() {
  if (await save([...list.value, { person: person.value, from: from.value, to: to.value || from.value, note: note.value }])) {
    toast('Отмечено')
    to.value = ''
  }
}
const remove = (id) => save(list.value.filter((a) => a.id !== id))
</script>

<style scoped>
.grow-t { flex: 1; min-width: 0; font-weight: 500; }
.ava { width: 26px; height: 26px; border-radius: 50%; display: inline-grid; place-items: center; color: #fff; font-size: 14px; font-weight: 600; flex: none; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.choice { border: 1px solid var(--line); background: var(--surface); color: var(--ink-2); border-radius: 999px; padding: 6px 12px; font: inherit; font-size: 14px; cursor: pointer; }
.choice.on { background: var(--tint); border-color: var(--tint); color: #fff; font-weight: 600; }
.line { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.x { border: 0; background: none; color: var(--ink-3); font-size: 22px; line-height: 1; padding: 4px 8px; }
.x:hover { color: var(--red); }
.add { margin-top: 10px; }
.date { font: inherit; color: inherit; background: var(--fill); border: 0; border-radius: 8px; padding: 6px 8px; }
.err { color: var(--red); }
</style>
