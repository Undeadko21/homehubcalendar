<template>
  <button v-if="voiceSupported" type="button" class="mic" :class="{ on: active }" :disabled="disabled"
          :aria-label="active ? 'Слушаю… нажмите, чтобы остановить' : 'Сказать голосом'" :title="active ? 'Слушаю…' : 'Сказать голосом'"
          @click="toggle">
    <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5.5 11a6.5 6.5 0 0013 0M12 17.5V21M8.5 21h7" /></svg>
  </button>
</template>

<script setup>
// Кнопка микрофона: распознанная фраза уходит в событие `text`, ошибка — в `error`.
import { ref } from 'vue'
import { voiceSupported, listen, stop } from '../lib/voice'

defineProps({ disabled: Boolean })
const emit = defineEmits(['text', 'error'])
const active = ref(false)

async function toggle() {
  if (active.value) { stop(); return }
  active.value = true
  try { emit('text', await listen()) } catch (e) { emit('error', e.message) } finally { active.value = false }
}
</script>

<style scoped>
.mic {
  flex: none; width: 44px; border: 0; border-radius: 12px; background: var(--fill); color: var(--tint);
  display: grid; place-items: center; padding: 0;
}
.mic svg { width: 22px; height: 22px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.mic.on { background: var(--red); color: #fff; animation: pulse 1.2s ease-in-out infinite; }
@keyframes pulse { 50% { box-shadow: 0 0 0 6px color-mix(in srgb, var(--red) 25%, transparent); } }
</style>
