<template>
  <Sheet :open="!!w" label="Конфликты при переносе" @close="answer(false)">
    <div v-if="w" class="ask">
      <h2>{{ w.e.title }}</h2>
      <p class="faint">На новом месте что-то не сходится:</p>
      <div class="group">
        <div v-for="(x, i) in w.items" :key="i" class="row"><span class="dot"></span><span>{{ x.text }}</span></div>
      </div>
      <div class="group">
        <div class="row"><button class="btn link" @click="answer(true)">Всё равно перенести</button></div>
        <div class="row"><button class="btn" @click="answer(false)">Не переносить</button></div>
      </div>
    </div>
  </Sheet>
</template>

<script setup>
import { computed } from 'vue'
import { state } from '../lib/store'
import Sheet from './Sheet.vue'

const w = computed(() => state.moveWarn)
function answer(ok) {
  const cur = state.moveWarn
  state.moveWarn = null
  cur?.resolve(ok)
}
</script>

<style scoped>
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--red, #ff3b30); flex: none; margin-top: 7px; }
.row { display: flex; gap: 10px; align-items: flex-start; }
</style>
