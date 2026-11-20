<template>
  <div v-if="items.length" class="uw" :class="{ open }">
    <button class="head" :aria-expanded="open" @click="open = !open">
      <span class="t">Необычно на неделе</span>
      <span class="n">{{ items.length }}</span>
      <span class="peek">{{ open ? '' : items[0].text + (items.length > 1 ? ' …' : '') }}</span>
      <span class="chev" aria-hidden="true">{{ open ? '⌃' : '›' }}</span>
    </button>
    <ul v-if="open">
      <li v-for="(i, k) in items" :key="k" :class="i.kind">{{ i.text }}</li>
    </ul>
  </div>
</template>

<script setup>
// «Необычная неделя» (v0.21): пропуски и сдвиги серий, «не идёт», поздние события детей — /api/unusual (backend/app/unusual.py).
import { ref, watch } from 'vue'
import { api } from '../lib/api'
import { state } from '../lib/store'
import { isoDate, startOfWeek } from '../lib/dates'

const props = defineProps({ cursor: { type: Date, required: true } })
const items = ref([])
const open = ref(false)
let seq = 0

async function load() {
  const my = ++seq
  try {
    const r = await api.unusual(isoDate(startOfWeek(props.cursor)))
    if (my === seq) items.value = r.items || []
  } catch { if (my === seq) items.value = [] }   // вспомогательная полоса — без ошибок на экране
}
watch(() => [isoDate(startOfWeek(props.cursor)), state.revision], load, { immediate: true })
</script>

<style scoped>
.uw { margin: 0 16px 8px; border-radius: 12px; background: var(--fill); font-size: 13px; }
.head { display: flex; align-items: center; gap: 8px; width: 100%; padding: 8px 12px; border: 0; background: none; color: var(--ink);
  font: inherit; text-align: left; cursor: pointer; min-height: 40px; }
.t { font-weight: 600; white-space: nowrap; }
.n { min-width: 20px; height: 20px; border-radius: 10px; background: var(--accent, #ff3b30); color: #fff; font-size: 12px;
  display: inline-flex; align-items: center; justify-content: center; padding: 0 6px; }
.peek { flex: 1; min-width: 0; color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chev { color: var(--ink-3); font-size: 16px; line-height: 1; }
ul { list-style: none; margin: 0; padding: 0 12px 10px; max-height: 40vh; overflow: auto; }
li { padding: 4px 0; border-top: 1px solid var(--sep, rgba(127,127,127,.2)); color: var(--ink); }
li.absent, li.missing { color: var(--ink-2); }
</style>
