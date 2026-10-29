<template>
  <Sheet :open="!!ask" label="Перенести повторяющееся событие" @close="state.moveAsk = null">
    <div v-if="ask" class="ask">
      <h2>{{ ask.e.title }}</h2>
      <p class="faint">Событие повторяется. Что перенести?</p>
      <div class="group">
        <div class="row"><button class="btn link" :disabled="busy" @click="go('once')">Только это ({{ ask.label }})</button></div>
        <div class="row"><button class="btn link" :disabled="busy" @click="go('following')">Это и следующие (с {{ ask.label }})</button></div>
        <div class="row"><button class="btn link" :disabled="busy" @click="go('series')">Всю серию (сдвинуть все повторы)</button></div>
        <div class="row"><button class="btn" :disabled="busy" @click="state.moveAsk = null">Отмена</button></div>
      </div>
    </div>
  </Sheet>
</template>

<script setup>
import { computed, ref } from 'vue'
import { state } from '../lib/store'
import { confirmMove } from '../lib/moveEvent'
import Sheet from './Sheet.vue'

const ask = computed(() => state.moveAsk)
const busy = ref(false)
async function go(scope) {
  busy.value = true
  try { await confirmMove(scope) } finally { busy.value = false }
}
</script>
